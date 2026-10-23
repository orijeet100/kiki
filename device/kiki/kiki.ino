// Kiki on the Tab5, drawn natively with LVGL (v0.15, ADR 0033). Same app as the streamed page in
// device/stream, without a browser on the laptop: the Tab5 draws the UI itself.
//  - events.ino: Kiki's live events (GET /events) drive the screen; taps on the List
//    (POST /item) and typed commands (POST /command) go back.
//  - screen.ino: the UI from docs/ui.md in DESIGN.md's tokens, at 1.5x the web's px sizes so it
//    reads across a kitchen, plus the Tab5's own volume bar and keyboard.
//  - audio.ino: mic and speaker take turns and stream to Kiki's voice loop, exactly as in
//    device/stream (KIKI_MIC=tab5, KIKI_SPEAKER=tab5).
// Build and flash: device/kiki/build.ps1. Every network step is printed to the Serial Monitor.
#include <M5Unified.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <lvgl.h>
#include "driver/ppa.h"
#include <lgfx/v1/platforms/esp32p4/Panel_DSI.hpp>  // the panel's framebuffer, for the PPA
#include <deque>
#include <vector>
#include "secrets.h"

#ifndef KIKI_TZ
#define KIKI_TZ "UTC0"  // POSIX TZ for the run times in History; set it in secrets.h
#endif

static constexpr int W = 720, H = 1280;
static constexpr uint16_t MIC_PORT = 8768, SPEAKER_PORT = 8769;
static constexpr size_t MAX_RUNS = 50;     // the History sheet holds the last 50, like the web UI
static constexpr uint32_t DONE_MS = 1800;  // the green check after a run without an error

// ---------- what the screen shows, filled from Kiki's events ----------

struct Item {
  String name;
  int quantity;
  bool needed;
  bool changed;  // new or different since the last list: gets the blue ring for 1.5 s
};

struct Chip {
  String text;
  bool failed;
};

struct Run {
  String time, source, latency, heard, said, error, details;
  std::vector<Chip> chips;
};

enum class Link { Connecting, Live, Reconnecting };  // the event stream, as the top bar shows it

// Requests the screen hands to networkTask (events.ino), and its answers.
enum class PostKind { Flip, Command };

struct Post {  // networkTask deletes the strings
  PostKind kind;
  String *json, *subject;  // subject: the item's name, or the command's text
};

struct PostResult {  // the loop deletes the string
  PostKind kind;
  int status;
  String *subject;
};

// The orb's types (orb.ino). Declared here because Arduino puts its generated prototypes
// before the first function, and the orb's functions take these.
enum OrbShape { SHAPE_LISTENING, SHAPE_THINKING, SHAPE_SEARCHING, SHAPE_SPEAKING, SHAPE_DONE, SHAPE_COUNT };

struct OrbSeed {
  float x, y, z, a, u, sa, ca;
};

struct SpokenWord {
  float start, end;
  uint8_t syllables;
};

struct ScreenParticle {
  float x, y, radius, alpha, spark;  // where it lands, and its dot and spark strengths
};

struct OrbMotion {
  double t;
  float weights[SHAPE_COUNT], env, level, scale, opacity, gray;
  std::vector<double> onsets;
};

std::vector<Item> items;
std::deque<Run> runs;  // newest first
String kikiState = "idle";
bool runJustFinished = false;  // the next idle shows the check mark first
Link eventLink = Link::Connecting;
Preferences prefs;
uint8_t volume;

// The ArduinoJson pool for big events (the snapshot carries 50 runs) lives in PSRAM.
struct SpiRamAllocator : ArduinoJson::Allocator {
  void *allocate(size_t n) override { return heap_caps_malloc(n, MALLOC_CAP_SPIRAM); }
  void deallocate(void *p) override { heap_caps_free(p); }
  void *reallocate(void *p, size_t n) override { return heap_caps_realloc(p, n, MALLOC_CAP_SPIRAM); }
} spiRam;

// ---------- test hooks over USB serial ----------

extern volatile bool playSilenceForTest;  // audio.ino

// "tap x y" presses the screen through the same input LVGL reads from the finger, so it reaches
// every control a finger does; "silence" plays 0.48 s of zeros through the speaker path (the mic
// hand-over, without a sound); "shot" sends the screen as RGB, each row behind a marker.
void handleSerialTestCommands() {
  if (!Serial.available()) return;
  String command = Serial.readStringUntil('\n');
  int x, y, dy;
  if (sscanf(command.c_str(), "drag %d %d %d", &x, &y, &dy) == 3) {  // "drag x y dy": a vertical swipe
    Serial.printf("[test] drag %d %d by %d\n", x, y, dy);
    pressScreenAlong(x, y, x, y + dy, 400);
  } else if (sscanf(command.c_str(), "tapitem %d", &x) == 1) {  // "tapitem n": a finger on the List's row n
    tapListRow(x);
  } else if (sscanf(command.c_str(), "tap %d %d", &x, &y) == 2) {
    Serial.printf("[test] tap %d %d\n", x, y);
    pressScreenFor(x, y, 250);
  } else if (command.startsWith("orbspeak")) {  // the speaking look on a sample reply, without a sound
    orbSays("Milk, onions, bananas, walnuts, chia seeds, paneer, apples, blueberry, bread and eggs.");
  } else if (command.startsWith("redraw")) {
    measureFullRedraw();
  } else if (command.startsWith("silence")) {
    playSilenceForTest = true;
  } else if (command.startsWith("shot")) {
    Serial.setTxTimeoutMs(2000);
    static uint8_t line[W * 3];
    Serial.printf("SHOT %d %d\n", W, H);
    for (int row = 0; row < H; row++) {  // each row behind a marker and its number, so a reader can resync
      M5.Display.readRectRGB(0, row, W, 1, line);
      uint8_t marker[4] = {0xA5, 0x5A, (uint8_t)(row & 0xFF), (uint8_t)(row >> 8)};
      Serial.write(marker, 4);
      Serial.write(line, sizeof line);
    }
    Serial.setTxTimeoutMs(0);
  }
}

void setup() {
  M5.begin();
  Serial.begin(115200);
  Serial.setTxTimeoutMs(0);  // never wait for the laptop to read the log: it froze the mic for 2 s a line
  setenv("TZ", KIKI_TZ, 1);
  tzset();
  prefs.begin("kiki");
  volume = prefs.getUChar("vol", 13);  // shared with device/stream; 13 = 5%, near silent
  Serial.printf("[volume] starts at %d of 255\n", volume);

  startScreen();
  startAudio();
  startNetwork();

  Serial.printf("[wifi] connecting to %s\n", WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  WiFi.setSleep(false);  // power saving dropped a quarter of the mic packets, with long gaps
}

// ---------- measuring: the loop's slowest step, every 5 s ----------
// Everything the screen does happens in loop(), so any step that waits stalls the whole screen;
// a frame is 16 ms.
uint32_t stepStartMs = 0, slowestStepMs = 0, loopsCounted = 0, stallReportMs = 0;
const char *slowestStep = "";

void endStep(const char *step) {
  uint32_t now = millis();
  if (now - stepStartMs > slowestStepMs) {
    slowestStepMs = now - stepStartMs;
    slowestStep = step;
  }
  stepStartMs = now;
}

void reportStalls() {
  loopsCounted++;
  if (millis() - stallReportMs < 5000) return;
  Serial.printf("[loop] slowest step %lu ms (%s), %lu loops in 5 s\n", slowestStepMs, slowestStep, loopsCounted);
  stallReportMs = millis();
  slowestStepMs = loopsCounted = 0;
}

void loop() {
  stepStartMs = millis();
  M5.update();
  handleSerialTestCommands();
  endStep("touch");
  handleNetworkNews();  // the network itself is networkTask's (events.ino)
  endStep("events");
  showNewestOrbFrame();
  endStep("orb");
  lv_timer_handler();
  endStep("lvgl");
  reportStalls();
  delay(2);
}
