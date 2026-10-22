// Throwaway hardware check for the Tab5: screen, touch, mic and speaker.
#include <M5Unified.h>

static constexpr uint32_t RATE = 16000;
static constexpr size_t SAMPLES = RATE * 3;  // 3 seconds
static int16_t *rec;

void say(const char *text) {
  M5.Display.fillScreen(TFT_BLACK);
  M5.Display.setCursor(0, 40);
  M5.Display.println(text);
  Serial.println(text);
}

void setup() {
  M5.begin();
  Serial.begin(115200);
  M5.Display.setTextSize(4);
  rec = (int16_t *)ps_malloc(SAMPLES * sizeof(int16_t));
  M5.Speaker.setVolume(200);
  M5.Speaker.tone(880, 150);
  say(" Kiki device check\n\n Tap the screen,\n then speak for 3 s.");
}

void loop() {
  M5.update();
  if (!M5.Touch.getDetail().wasPressed()) return;

  // Mic and speaker share the audio bus, so only one runs at a time.
  M5.Speaker.end();
  M5.Mic.begin();
  say(" Recording...\n speak now");
  M5.Mic.record(rec, SAMPLES, RATE);
  while (M5.Mic.isRecording()) delay(10);
  M5.Mic.end();

  M5.Speaker.begin();
  say(" Playing back...");
  M5.Speaker.playRaw(rec, SAMPLES, RATE);
  while (M5.Speaker.isPlaying()) delay(10);
  say(" Done.\n\n Tap to try again.");
}
