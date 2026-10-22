// Kiki's own web UI on the Tab5 (v0.14, ADRs 0027-0031). The Tab5 is only a client of the laptop:
//  - screen: `python -m kiki.screen` sends the page as JPEG frames (4-byte length, then the
//    JPEG); the hardware decoder unpacks them, and touches go back as "down|move|up x y".
//  - mic: one UDP packet per 20 ms of 16 kHz mono audio to Kiki's voice loop (KIKI_MIC=tab5),
//    sent from its own task so drawing a frame or a slow connect never drops audio.
//  - speaker: Kiki's chime and replies arrive as 16 kHz mono over TCP (KIKI_SPEAKER=tab5).
//    Mic and speaker take turns: M5Unified gives each its own clock on the same wires, and
//    running both at once played garbled, loud noise. The mic pauses while the Tab5 speaks.
//  - volume: a bar along the bottom of the screen, applied to the samples here, saved across
//    restarts.
// Every network step is printed to the Serial Monitor (115200).
#include <M5Unified.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include "driver/jpeg_decode.h"
#include "secrets.h"

static constexpr int W = 720, H = 1280;
static constexpr uint16_t SCREEN_PORT = 8767, MIC_PORT = 8768, SPEAKER_PORT = 8769;
static constexpr size_t MAX_JPEG = 1024 * 1024;
static constexpr uint32_t AUDIO_RATE = 16000;
static constexpr size_t MIC_SAMPLES = 320;  // 20 ms
static constexpr int MIC_SLOTS = 16;        // 320 ms of slack while a frame is drawn
static constexpr size_t SPK_SAMPLES = 640;  // 40 ms, the size Kiki sends audio in
static constexpr int SPK_SLOTS = 4, SPK_CHANNEL = 0;
static constexpr size_t SPK_FIFO_BYTES = AUDIO_RATE * 2 * 4;  // 4 s
static constexpr size_t SPK_START_BYTES = SPK_SAMPLES * 2 * 4;  // start once 160 ms are in
// Volume is applied to the samples, so the bar is linear and has a hard ceiling: M5Unified
// runs at fixed settings where a full-scale sample comes out just under the speaker's digital
// range (2 x boost 8 x 255^2 x 255^2 / 2^36 = 0.98), so nothing can clip. Its default boost of 4
// stopped at half the range, too quiet; the speaker chip's own volume is already at maximum.
// Starts near silent; "vol" is a new setting so no makeLouderAtVolume level from before carries over.
static constexpr uint8_t DEFAULT_VOLUME = 13, MAX_VOLUME = 255;  // 13 = 5%
static constexpr int BAR_Y = H - 80, TRACK_X = 170, TRACK_W = W - 170 - 120;

jpeg_decoder_handle_t decoder;
uint8_t *jpeg;
uint16_t *pixels;
size_t jpegCap, pixelsCap;
WiFiClient screenLink;
WiFiUDP micOut;
Preferences prefs;
uint32_t frameLen = 0, got = 0, frames = 0;
bool inFrame = false, touchingBar = false;
uint32_t nextScreenTry = 0, lastMove = 0;
uint8_t volume;

int16_t *micBuf[MIC_SLOTS];
int micNext = 0;
QueueHandle_t micReady;

// ---------- volume bar ----------

void drawVolumeBar() {
  M5.Display.startWrite();
  M5.Display.fillRect(0, BAR_Y, W, H - BAR_Y, M5.Display.color888(9, 9, 9));
  M5.Display.drawFastHLine(0, BAR_Y, W, M5.Display.color888(38, 38, 38));
  M5.Display.setTextSize(1);
  M5.Display.setFont(&fonts::FreeSans12pt7b);
  M5.Display.setTextColor(M5.Display.color888(153, 153, 153));
  M5.Display.setTextDatum(middle_left);
  M5.Display.drawString("Volume", 28, BAR_Y + 40);
  int knob = TRACK_X + TRACK_W * volume / MAX_VOLUME;
  M5.Display.fillRoundRect(TRACK_X, BAR_Y + 37, TRACK_W, 6, 3, M5.Display.color888(38, 38, 38));
  M5.Display.fillRoundRect(TRACK_X, BAR_Y + 37, knob - TRACK_X, 6, 3, M5.Display.color888(0, 153, 255));
  M5.Display.fillSmoothCircle(knob, BAR_Y + 40, 16, TFT_WHITE);
  M5.Display.setTextDatum(middle_right);
  M5.Display.drawString(String(volume * 100 / MAX_VOLUME) + "%", W - 28, BAR_Y + 40);
  M5.Display.endWrite();
}

void setVolumeFromTouch(int x) {
  uint8_t v = constrain((x - TRACK_X) * MAX_VOLUME / TRACK_W, 0, MAX_VOLUME);
  if (v == volume) return;
  volume = v;  // playKikiAudioTask applies it to the next chunk
  drawVolumeBar();
}

// ---------- mic ----------

// Runs on the mic's capture task: hand the full buffer to sendMicPacketsTask and queue the next one.
void onMicBufferFilled(void *, void *data, size_t) {
  xQueueSend(micReady, &data, 0);
  M5.Mic.record(micBuf[micNext], MIC_SAMPLES, AUDIO_RATE);
  micNext = (micNext + 1) % MIC_SLOTS;
}

void sendMicPacketsTask(void *) {
  uint32_t sent = 0, peak = 0, lastReport = millis();
  for (;;) {
    void *buf;
    if (!xQueueReceive(micReady, &buf, pdMS_TO_TICKS(100))) continue;
    int16_t *s = (int16_t *)buf;
    for (size_t i = 0; i < MIC_SAMPLES; i++) peak = max(peak, (uint32_t)abs(s[i]));
    if (WiFi.status() == WL_CONNECTED && micOut.beginPacket(KIKI_HOST, MIC_PORT)) {
      micOut.write((uint8_t *)buf, MIC_SAMPLES * 2);
      sent += micOut.endPacket();
    }
    if (millis() - lastReport > 5000) {  // should be ~250; the peak helps tune the gain
      Serial.printf("[mic] %lu packets sent in 5 s, peak level %lu / 32767\n", sent, peak);
      lastReport = millis();
      sent = peak = 0;
    }
  }
}

// Starts the mic and queues its first two recordings; onMicBufferFilled keeps it going from then on.
void startMic() {
  M5.Mic.begin();
  for (int i = 0; i < 2; i++) {
    M5.Mic.record(micBuf[micNext], MIC_SAMPLES, AUDIO_RATE);
    micNext = (micNext + 1) % MIC_SLOTS;
  }
}

// ---------- speaker ----------

// Makes speech makeLouderAtVolume without clipping: Piper's loudest syllables already reach full scale, so
// the quiet parts are lifted instead. A 2x boost (+6 dB), then a limiter that pulls any sample
// over LIMIT back down at once (the peak follower includes the sample itself, so nothing gets
// past) and lets go over ~60 ms. Then the volume bar. Can sound slightly squashed; that's the
// price of the extra loudness.
void makeLouderAtVolume(int16_t *samples) {
  static constexpr float BOOST = 2.0f, LIMIT = 0.95f;
  static const float RELEASE = expf(-1.0f / (0.06f * AUDIO_RATE));
  static float peak = 0;
  for (size_t i = 0; i < SPK_SAMPLES; i++) {
    float x = samples[i] / 32768.0f * BOOST;
    peak = max(fabsf(x), peak * RELEASE);
    if (peak > LIMIT) x *= LIMIT / peak;
    samples[i] = (int16_t)(x * 32767.0f * volume / MAX_VOLUME);
  }
}

// The mic and the speaker can't run together (see the top), so they hand the audio bus over.
void switchToSpeaker() {
  M5.Mic.end();
  M5.Speaker.begin();
  M5.Speaker.setVolume(255);  // fixed: the bar's volume is in the samples
  Serial.println("[audio] speaker on, mic paused");
}

void switchToMic() {
  M5.Speaker.end();
  startMic();
  Serial.println("[audio] mic on");
}

// Reads Kiki's audio into a FIFO and keeps two 40 ms chunks queued on the speaker. Playback
// starts once 160 ms are in (Kiki stays about that far ahead), so Wi-Fi hiccups don't cut the
// sound. A gap is the FIFO running dry while Kiki is still talking; each reply logs its count.
void playKikiAudioTask(void *) {
  static int16_t slots[SPK_SLOTS][SPK_SAMPLES];
  uint8_t *fifo = (uint8_t *)heap_caps_malloc(SPK_FIFO_BYTES, MALLOC_CAP_SPIRAM);
  size_t head = 0, count = 0;  // FIFO read position and bytes held
  int slot = 0;
  bool playing = false, speakerOn = false;
  uint32_t lastData = 0, gaps = 0, chunks = 0;
  WiFiClient link;
  for (;;) {
    if (!link.connected()) {
      count = 0;
      playing = false;
      if (speakerOn) {  // never leave the mic paused
        switchToMic();
        speakerOn = false;
      }
      if (WiFi.status() == WL_CONNECTED && link.connect(KIKI_HOST, SPEAKER_PORT, 500)) {
        Serial.printf("[speaker] connected to %s:%d\n", KIKI_HOST, SPEAKER_PORT);
      } else {
        vTaskDelay(pdMS_TO_TICKS(3000));
        continue;
      }
    }
    while (link.available() && count < SPK_FIFO_BYTES) {
      size_t tail = (head + count) % SPK_FIFO_BYTES;
      size_t room = min(SPK_FIFO_BYTES - count, SPK_FIFO_BYTES - tail);
      int n = link.read(fifo + tail, room);
      if (n <= 0) break;
      count += n;
      lastData = millis();
    }
    if (!playing && (count >= SPK_START_BYTES || (count && millis() - lastData > 60))) {
      playing = true;
      if (!speakerOn) {
        switchToSpeaker();
        speakerOn = true;
      }
    }
    while (playing && count >= SPK_SAMPLES * 2 && M5.Speaker.isPlaying(SPK_CHANNEL) < 2) {
      uint8_t *dst = (uint8_t *)slots[slot];
      for (size_t i = 0; i < SPK_SAMPLES * 2; i++) dst[i] = fifo[(head + i) % SPK_FIFO_BYTES];
      makeLouderAtVolume(slots[slot]);
      head = (head + SPK_SAMPLES * 2) % SPK_FIFO_BYTES;
      count -= SPK_SAMPLES * 2;
      M5.Speaker.playRaw(slots[slot], SPK_SAMPLES, AUDIO_RATE, false, 1, SPK_CHANNEL);
      slot = (slot + 1) % SPK_SLOTS;  // 4 slots, at most 2 queued: never overwrite a playing one
      chunks++;
    }
    if (playing && count < SPK_SAMPLES * 2) {
      playing = false;
      if (millis() - lastData < 30) gaps++;  // ran dry with more on the way
    }
    if (speakerOn && !playing && !count && !M5.Speaker.isPlaying() && millis() - lastData > 200) {
      switchToMic();  // done talking: listen again
      speakerOn = false;
    }
    if (chunks && !count && millis() - lastData > 1000) {  // a reply has finished
      Serial.printf("[speaker] played %lu ms, %lu gaps\n", chunks * 40, gaps);
      chunks = gaps = 0;
    }
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}

// ---------- screen ----------

void connectScreenLink() {
  if (screenLink.connected() || millis() < nextScreenTry) return;
  inFrame = false;
  if (screenLink.connect(KIKI_HOST, SCREEN_PORT, 500)) {
    screenLink.setNoDelay(true);
    Serial.printf("[screen] connected to %s:%d\n", KIKI_HOST, SCREEN_PORT);
  } else {
    Serial.println("[screen] can't connect: is `python -m kiki.screen` running?");
    nextScreenTry = millis() + 3000;
  }
}

void decodeAndShowFrame() {
  jpeg_decode_cfg_t cfg = {};
  cfg.output_format = JPEG_DECODE_OUT_FORMAT_RGB565;
  cfg.rgb_order = JPEG_DEC_RGB_ELEMENT_ORDER_RGB;  // big-endian 565, what pushImage expects
  cfg.conv_std = JPEG_YUV_RGB_CONV_STD_BT601;
  uint32_t out = 0, start = millis();
  esp_err_t err = jpeg_decoder_process(decoder, &cfg, jpeg, frameLen, (uint8_t *)pixels, pixelsCap, &out);
  if (err != ESP_OK) {
    Serial.printf("[screen] decode failed: %s\n", esp_err_to_name(err));
    return;
  }
  uint32_t decoded = millis();
  M5.Display.pushImage(0, 0, W, BAR_Y, pixels);  // the bottom strip is the volume bar's
  if (++frames % 30 == 1)
    Serial.printf("[screen] frame %lu: %lu KB, %lu ms decode, %lu ms show\n", frames, frameLen / 1024,
                  decoded - start, millis() - decoded);
}

void receiveFrames() {
  while (screenLink.available()) {
    if (!inFrame) {
      if (screenLink.available() < 4) return;
      uint8_t h[4];
      screenLink.read(h, 4);
      frameLen = (uint32_t)h[0] << 24 | h[1] << 16 | h[2] << 8 | h[3];
      if (frameLen > jpegCap) {
        Serial.printf("[screen] frame too big (%lu bytes), reconnecting\n", frameLen);
        screenLink.stop();
        return;
      }
      got = 0;
      inFrame = true;
    }
    int n = screenLink.read(jpeg + got, frameLen - got);
    if (n <= 0) return;
    got += n;
    if (got == frameLen) {
      inFrame = false;
      decodeAndShowFrame();
      screenLink.print("shown\n");  // the laptop sends the next frame only now
    }
  }
}

// Touches on the volume bar stay on the Tab5; everything else goes to the page.
void handleTouch() {
  auto t = M5.Touch.getDetail();
  if (t.wasPressed()) touchingBar = t.y >= BAR_Y;
  if (touchingBar) {
    if (t.isPressed()) setVolumeFromTouch(t.x);
    if (t.wasReleased()) {
      prefs.putUChar("vol", volume);
      Serial.printf("[volume] %d of %d\n", volume, MAX_VOLUME);
    }
    return;
  }
  const char *kind = nullptr;
  if (t.wasPressed()) kind = "down";
  else if (t.wasReleased()) kind = "up";
  else if (t.isPressed() && millis() - lastMove > 30) kind = "move";  // ~30 moves a second
  if (!kind || !screenLink.connected()) return;
  if (kind[0] == 'm') lastMove = millis();
  screenLink.printf("%s %d %d\n", kind, t.x, t.y);
  if (kind[0] != 'm') Serial.printf("[touch] %s %d %d\n", kind, t.x, t.y);
}

// Test hooks over USB serial: "tap x y" acts like a finger, "shot" sends the screen as RGB.
void handleSerialTestCommands() {
  if (!Serial.available()) return;
  String cmd = Serial.readStringUntil('\n');
  int x, y;
  if (sscanf(cmd.c_str(), "tap %d %d", &x, &y) == 2 && screenLink.connected()) {
    Serial.printf("[test] tap %d %d\n", x, y);
    screenLink.printf("down %d %d\nup %d %d\n", x, y, x, y);
  } else if (cmd.startsWith("shot")) {
    Serial.setTxTimeoutMs(2000);  // a screenshot is 2.7 MB and someone is reading it: wait for them
    static uint8_t line[W * 3];
    Serial.printf("SHOT %d %d\n", W, H);
    for (int r = 0; r < H; r++) {
      M5.Display.readRectRGB(0, r, W, 1, line);
      Serial.write(line, sizeof line);
    }
    Serial.setTxTimeoutMs(0);
  }
}

void setup() {
  M5.begin();
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);  // never wait for the laptop to read the log: it froze the mic for 2 s a line
  prefs.begin("kiki");
  volume = prefs.getUChar("vol", DEFAULT_VOLUME);

  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setTextSize(3);
  M5.Display.drawString("Kiki: connecting...", 40, 600);
  drawVolumeBar();

  jpeg_decode_engine_cfg_t engine = {};
  engine.timeout_ms = 200;
  jpeg_new_decoder_engine(&engine, &decoder);
  jpeg_decode_memory_alloc_cfg_t in = {JPEG_DEC_ALLOC_INPUT_BUFFER}, out = {JPEG_DEC_ALLOC_OUTPUT_BUFFER};
  jpeg = (uint8_t *)jpeg_alloc_decoder_mem(MAX_JPEG, &in, &jpegCap);
  pixels = (uint16_t *)jpeg_alloc_decoder_mem(W * H * 2, &out, &pixelsCap);

  micReady = xQueueCreate(MIC_SLOTS, sizeof(void *));
  for (int i = 0; i < MIC_SLOTS; i++) micBuf[i] = (int16_t *)heap_caps_malloc(MIC_SAMPLES * 2, MALLOC_CAP_INTERNAL);
  M5.Mic.setBufferReleaseCallback(nullptr, onMicBufferFilled);
  auto spk = M5.Speaker.config();
  spk.magnification = 8;  // see DEFAULT_VOLUME
  M5.Speaker.config(spk);
  startMic();  // the speaker stays off until Kiki says something
  xTaskCreate(sendMicPacketsTask, "mic", 4096, nullptr, 3, nullptr);
  xTaskCreate(playKikiAudioTask, "speaker", 4096, nullptr, 3, nullptr);

  Serial.printf("[wifi] connecting to %s\n", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  WiFi.setSleep(false);  // power saving dropped a quarter of the mic packets, with long gaps
}

void loop() {
  M5.update();
  handleSerialTestCommands();
  handleTouch();
  if (WiFi.status() == WL_CONNECTED) {
    connectScreenLink();
    receiveFrames();
  }
  delay(1);
}
