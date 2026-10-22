// Mic and speaker, the same path as device/stream/stream.ino (keep the two in step):
//  - mic: one UDP packet per 20 ms of 16 kHz mono to Kiki's voice loop, from its own task so
//    drawing never drops audio.
//  - speaker: Kiki's chime and replies arrive as 16 kHz mono over TCP.
//    Mic and speaker take turns: M5Unified gives each its own clock on the same wires, and
//    running both at once played garbled, loud noise. The mic pauses while the Tab5 speaks.
// Volume is applied to the samples, so the bar is linear and has a hard ceiling: M5Unified
// runs at fixed settings where a full-scale sample comes out just under the speaker's digital
// range (2 x boost 8 x 255^2 x 255^2 / 2^36 = 0.98), so nothing can clip. Starts near silent.

static constexpr uint32_t AUDIO_RATE = 16000;
static constexpr size_t MIC_SAMPLES = 320;  // 20 ms
static constexpr int MIC_SLOTS = 16;        // 320 ms of slack
static constexpr size_t SPK_SAMPLES = 640;  // 40 ms, the size Kiki sends audio in
static constexpr int SPK_SLOTS = 4, SPK_CHANNEL = 0;
static constexpr size_t SPK_FIFO_BYTES = AUDIO_RATE * 2 * 4;    // 4 s
static constexpr size_t SPK_START_BYTES = SPK_SAMPLES * 2 * 4;  // start once 160 ms are in
static constexpr uint8_t MAX_VOLUME = 255;  // the default, 13 (5%), is in setup()

WiFiUDP micOut;
volatile bool playSilenceForTest = false;  // "silence" over serial: tests the speaker path without a sound
int16_t *micBuf[MIC_SLOTS];
int micNext = 0;
QueueHandle_t micReady;

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

// Makes speech louder without clipping: Piper's loudest syllables already reach full scale, so
// the quiet parts are lifted instead. A 2x boost (+6 dB), then a limiter that pulls any sample
// over LIMIT back down at once (the peak follower includes the sample itself, so nothing gets
// past) and lets go over ~60 ms. Then the volume bar.
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

void switchToSpeaker() {
  M5.Mic.end();
  bool started = M5.Speaker.begin();
  M5.Speaker.setVolume(255);  // fixed: the bar's volume is in the samples
  Serial.printf("[audio] speaker %s, mic paused (internal DMA free %u, largest %u)\n", started ? "on" : "FAILED",
                heap_caps_get_free_size(MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL),
                heap_caps_get_largest_free_block(MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL));
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
    if (playSilenceForTest) {
      playSilenceForTest = false;
      size_t bytes = min(SPK_FIFO_BYTES - count, SPK_SAMPLES * 2 * 12);  // 0.48 s of zeros, whole chunks
      for (size_t i = 0; i < bytes; i++) fifo[(head + count + i) % SPK_FIFO_BYTES] = 0;
      count += bytes;
      lastData = millis();
      Serial.println("[test] 0.5 s of silence through the speaker path");
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
      orbVoiceStarted(true);  // the reply's envelope follows the sound from here
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
    if (count && count < SPK_SAMPLES * 2 && millis() - lastData > 200) count = 0;  // a part chunk nothing will finish
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

void startAudio() {
  micReady = xQueueCreate(MIC_SLOTS, sizeof(void *));
  for (int i = 0; i < MIC_SLOTS; i++) micBuf[i] = (int16_t *)heap_caps_malloc(MIC_SAMPLES * 2, MALLOC_CAP_INTERNAL);
  M5.Mic.setBufferReleaseCallback(nullptr, onMicBufferFilled);
  auto speaker = M5.Speaker.config();
  speaker.magnification = 8;  // see the volume note at the top
  M5.Speaker.config(speaker);
  startMic();  // the speaker stays off until Kiki says something
  xTaskCreate(sendMicPacketsTask, "mic", 4096, nullptr, 3, nullptr);
  xTaskCreate(playKikiAudioTask, "speaker", 4096, nullptr, 3, nullptr);
}
