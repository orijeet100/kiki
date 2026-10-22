// The orb: a port of the Speaking Orb the web UI vendors (src/kiki/speaking-orb.js, MIT,
// Copyright (c) 2026 Ship Notes; the notice is at the end of this file). Same Fibonacci-sphere
// particle field, same five shapes and the same per-particle maths as its paint(); the halo and
// the point sprite follow its 2D path and its fragment shader. Here the CPU draws it: each frame
// the particles are added up into the orb's own pixel buffer on the second core, and LVGL shows
// the newest finished frame, redrawing only the orb's rectangle.

#pragma GCC optimize("O2")  // the orb's inner loops; Arduino builds with -Os

static constexpr int ORB_W = 420, ORB_H = 360;    // the orb's pixels; the sphere is laid out as on
static constexpr float ORB_UNIT = 410.0f / 720;   // a 410 px canvas (the web's 720-unit space)
static constexpr int PARTICLES = 3000;            // measured: see the [orb] log line
static constexpr int ORB_FRAME_US = 25000;        // 40 fps
// Arduino's PI is a double, and this chip's FPU is single precision only: one PI in a per-particle
// sum made it software double maths. The orb uses these instead.
static constexpr float PI_F = 3.14159265f, TAU_F = 6.28318531f;
static constexpr uint8_t ORB_BG = 8;              // the canvas token, 0x080808
static constexpr int ORB_RADIUS_STEPS = 1112;     // quarter pixels from the centre to a corner
// Drawn at half resolution and scaled 2x by the P4's PPA on the way to the panel: a quarter of
// the pixels to work out (the pixel pass was most of each frame).
static constexpr int ORB_RENDER_SCALE = 2;
static constexpr int RENDER_W = ORB_W / ORB_RENDER_SCALE, RENDER_H = ORB_H / ORB_RENDER_SCALE;
static constexpr float RENDER_UNIT = ORB_UNIT / ORB_RENDER_SCALE;
static constexpr int ORB_HALO_MAX = (int)((305 + 25) * RENDER_UNIT) + 2;  // the halo's widest reach

// ui.html's --orb-<state> tokens: primary, gradient-violet, accent-blue, gradient-magenta, success.
static const float SHAPE_RGB[SHAPE_COUNT][3] = {
    {255, 255, 255}, {0x6a, 0x4c, 0xf5}, {0x00, 0x99, 0xff}, {0xd4, 0x4d, 0xf0}, {0x22, 0xc5, 0x5e}};

// What the screen asks for; the render task reads it once a frame, under orbMutex.
struct OrbRequest {
  OrbShape shape = SHAPE_LISTENING;
  float level = 0;                          // the listening ripple's height, as the web's level attribute
  float scale = .84f, opacity = .5f, gray = 0;  // ui.html's CSS for idle and error, eased like its transitions
  std::vector<SpokenWord> words;            // the reply being spoken, for the fake voice envelope
  double lineStart = 0;
  bool lineDone = true, visible = true, waitingForVoice = false;
  uint32_t lineVersion = 0;
};

OrbRequest orbRequest;
SemaphoreHandle_t orbMutex;
OrbSeed *orbSeeds;
uint16_t *orbRadius;         // distance from the centre in quarter pixels, one quadrant (the rest mirror it)
uint16_t *haloPixels;        // the halo's RGB565 by distance and dither cell, made once a frame
int64_t orbStageUs[2];       // particles, pixels: for the [orb] log
uint16_t *orbFrames[3];      // RGB565: one shown, one ready, one being drawn
int orbShown = 0, orbReady = -1;
volatile int orbFramesShown = 0;  // frames LVGL actually put on screen, for the [orb] log
float dotProfile[256], sparkProfile[256];  // the shader's two radial profiles, by r squared

double secondsNow() { return esp_timer_get_time() / 1e6; }
float clamp01(float v) { return v < 0 ? 0 : v > 1 ? 1 : v; }
float smoothstep(float a, float b, float v) {
  float p = clamp01((v - a) / (b - a));
  return p * p * (3 - 2 * p);
}
float wrapPhase(double radians) { return (float)fmod(radians, 2 * PI); }  // keeps sinf's argument small

// ---------- the field (seedsFor) and the voice envelope (syl, pulseEnv, estimate) ----------

double seedNoise(double n) {
  double x = sin(n * 12.9898) * 43758.5453;
  return x - floor(x);
}

void makeOrbSeeds() {
  // a dense Fibonacci sphere shows moire stripes, so past 1000 points each one gets a small fixed nudge
  double jitter = PARTICLES > 1000 ? (1 - 1000.0 / PARTICLES) * 1.6 / sqrt(PARTICLES) : 0;
  for (int i = 0; i < PARTICLES; i++) {
    double y0 = 1 - 2 * (i + .5) / PARTICLES, a = i * 2.399963229728653 + (seedNoise(i) - .5) * jitter * 6;
    double y = fmax(-1, fmin(1, y0 + (seedNoise(i + .37) - .5) * jitter)), rr = sqrt(1 - y * y);
    orbSeeds[i] = {(float)(cos(a) * rr), (float)y, (float)(sin(a) * rr), (float)a, (float)i / PARTICLES,
                   (float)sin(a), (float)cos(a)};
  }
}

// rough syllables, only to fake a voice envelope: there's no audio level from the laptop
uint8_t countSyllables(String word) {
  word.toLowerCase();
  String letters;
  for (char c : word)
    if (c >= 'a' && c <= 'z') letters += c;
  if (letters.endsWith("e")) letters.remove(letters.length() - 1);
  int groups = 0;
  bool inVowels = false;
  for (char c : letters) {
    bool vowel = strchr("aeiouy", c);
    if (vowel && !inVowels) groups++;
    inVowels = vowel;
  }
  return max(1, groups);
}

// estimate(): each word lasts by its syllables, with a pause after punctuation.
std::vector<SpokenWord> estimateWords(const String &text) {
  std::vector<SpokenWord> words;
  float t = 0;
  int from = 0;
  while (from < (int)text.length()) {
    int to = text.indexOf(' ', from);
    if (to < 0) to = text.length();
    String word = text.substring(from, to);
    from = to + 1;
    if (word.isEmpty()) continue;
    bool pause = strchr(",.!?", word[word.length() - 1]);
    uint8_t syllables = countSyllables(word);
    float duration = .09f + .075f * syllables + (pause ? .18f : 0);
    words.push_back({t, t + duration - (pause ? .18f : 0), syllables});
    t += duration;
  }
  return words;
}

float pulseEnvelope(const std::vector<SpokenWord> &words, float t) {
  float e = 0;
  for (const SpokenWord &w : words) {
    if (t < w.start - .05f || t > w.end + .15f) continue;
    float len = max(.08f, w.end - w.start), k = clamp01((t - w.start) / len) * w.syllables;
    float within = k - floorf(k);
    e = max(e, (.55f + .45f * sinf(PI_F * clamp01(within * 1.15f))) * clamp01((t - w.start + .05f) / .05f) *
                   clamp01((w.end + .15f - t) / .15f));
  }
  return e;
}

// ---------- one frame (paint) ----------

static const float BAND_TILT[3][4] = {
    {cosf(.32f + 1), sinf(.32f + 1), cosf(0), sinf(0)},
    {cosf(-.72f + 1), sinf(-.72f + 1), cosf(1.02f), sinf(1.02f)},
    {cosf(1.08f + 1), sinf(1.08f + 1), cosf(-.82f), sinf(-.82f)}};

// Point sprites land in fast internal RAM, one band of rows at a time: random writes into the
// 900 KB PSRAM buffer this used to be missed the cache on nearly every pixel (150 ms a frame).
static constexpr int BAND_ROWS = 20;  // 33 KB of internal RAM; more starved Wi-Fi
ScreenParticle *screenParticles;  // PSRAM, read in order
uint16_t bandDots[BAND_ROWS * RENDER_W], bandSparks[BAND_ROWS * RENDER_W];  // 8.8 fixed point
float sineTable[1025];
float ringFalloff[256];  // exp(-x) for x in 0..9, the speaking rings' gaussian

// sinf costs ~0.5 us here; the orb only needs a few digits.
inline float fastSin(float x) {
  float t = x * (1024 / TAU_F);
  int i = (int)floorf(t);
  float f = t - i;
  i &= 1023;
  return sineTable[i] + (sineTable[i + 1] - sineTable[i]) * f;
}
inline float fastCos(float x) { return fastSin(x + PI_F / 2); }

// Adds one point sprite to the band: the shader's dot (bright core, faint skirt) and white spark.
inline void splatIntoBand(const ScreenParticle &p, int bandTop) {
  float inverse = 1 / (p.radius * p.radius);
  int x0 = max(0, (int)floorf(p.x - p.radius)), x1 = min(RENDER_W - 1, (int)ceilf(p.x + p.radius));
  int y0 = max(bandTop, (int)floorf(p.y - p.radius)), y1 = min(bandTop + BAND_ROWS - 1, (int)ceilf(p.y + p.radius));
  float dotStrength = p.alpha * 256, sparkStrength = p.spark * 256;
  for (int y = y0; y <= y1; y++) {
    float dy = y + .5f - p.y;
    uint16_t *dots = bandDots + (y - bandTop) * RENDER_W, *sparks = bandSparks + (y - bandTop) * RENDER_W;
    for (int x = x0; x <= x1; x++) {
      float dx = x + .5f - p.x, q = (dx * dx + dy * dy) * inverse;
      if (q >= 1) continue;
      int i = (int)(q * 255);
      dots[x] = min(65535, dots[x] + (int)(dotStrength * dotProfile[i]));
      if (p.spark > 0) sparks[x] = min(65535, sparks[x] + (int)(sparkStrength * sparkProfile[i]));
    }
  }
}

void paintOrb(uint16_t *out, const OrbMotion &m) {
  int64_t stage = esp_timer_get_time();
  const float *w = m.weights;
  float rgb[3] = {0, 0, 0};
  for (int s = 0; s < SHAPE_COUNT; s++)
    for (int c = 0; c < 3; c++) rgb[c] += SHAPE_RGB[s][c] * w[s];
  float ws = w[SHAPE_SPEAKING], env = m.env, unit = RENDER_UNIT * m.scale;
  float cx = RENDER_W / 2.0f, cy = RENDER_H / 2.0f;

  // the particles, exactly as speaking-orb.js lays them out
  const int ring = (int)roundf(PARTICLES * .65f);
  const float fine = max(.5f, powf(1000.0f / PARTICLES, .55f));
  const float light = min(1.0f, powf(1000.0f / (PARTICLES * fine * fine), .35f));
  const double t = m.t;
  const float spin = wrapPhase(t * .23), cs = cosf(spin), sn = sinf(spin), wave = 8 + m.level * 22;
  const float p3 = wrapPhase(t * 3), p2 = wrapPhase(t * 2), p57 = wrapPhase(t * .57), p48 = wrapPhase(t * .48);
  const float p14 = wrapPhase(t * 1.4), p11 = wrapPhase(t * 1.1), p08 = wrapPhase(t * .8), p22 = wrapPhase(t * 2.2);
  const float p16 = wrapPhase(t * 1.6);
  float bandPhase[3];
  for (int b = 0; b < 3; b++) bandPhase[b] = wrapPhase(t * (.7 + b * .2));
  float ringHeight[8], ringGain[8];
  int rings = 0;
  for (double onset : m.onsets) {
    if (rings == 8) break;
    float age = t - onset;
    ringHeight[rings] = -1.15f + age * 2.1f;
    ringGain[rings++] = powf(1 - age / 1.2f, 2);
  }

  for (int i = 0; i < PARTICLES; i++) {
    const OrbSeed &p = orbSeeds[i];
    float vx = 0, vy = 0, vz = 0, lit = 0;
    float sx = p.x * cs + p.z * sn, sz = p.z * cs - p.x * sn;  // the spinning sphere
    if (w[SHAPE_LISTENING] > .001f) {
      float r = (192 + fastSin(p.y * 11 - p3 + p.a * .03f) * wave + fastSin(p.a * .17f + p2) * 5) * w[SHAPE_LISTENING];
      vx += sx * r;
      vy += p.y * r;
      vz += sz * r;
    }
    if (w[SHAPE_THINKING] > .001f) {
      float theta = p.u * TAU_F * 3 + p57, phi = p.u * TAU_F * 8 - p48, rt = 137 + 41 * fastCos(phi) + 24 * p.sa;
      float bx = rt * fastCos(theta), bz = rt * fastSin(theta), by = 65 * fastSin(phi) + 17 * p.y;
      vx += bx * w[SHAPE_THINKING];
      vy += (by * .77f - bz * .52f) * w[SHAPE_THINKING];
      vz += (by * .52f + bz * .77f) * w[SHAPE_THINKING];
    }
    if (w[SHAPE_SEARCHING] > .001f) {
      int band = i % 3;
      float angle = p.u * TAU_F * 5 + bandPhase[band], radius = 196 + 11 * p.sa;
      float bx = fastCos(angle) * radius, by = fastSin(angle) * radius;
      float by2 = by * BAND_TILT[band][0], bz = by * BAND_TILT[band][1];
      vx += (bx * BAND_TILT[band][2] - by2 * BAND_TILT[band][3]) * w[SHAPE_SEARCHING];
      vy += (bx * BAND_TILT[band][3] + by2 * BAND_TILT[band][2]) * w[SHAPE_SEARCHING];
      vz += bz * w[SHAPE_SEARCHING];
    }
    if (w[SHAPE_SPEAKING] > .001f) {
      // the voice inflates a soft lobed sphere, every syllable sends a lit ring from chin to crown
      float lobe = fastSin(sx * 2.3f + p14) * fastSin(p.y * 2.9f - p11) * fastCos(sz * 2.1f + p08);
      float r = 184 + 16 * env + lobe * (5 + 19 * env) + fastSin(p.y * 7 - p22) * 3 * env;
      for (int k = 0; k < rings; k++) {  // exp(-d^2) from a table, and only near the ring: expf here
        float d = (p.y - ringHeight[k]) / .15f, dd = d * d;  // made speaking the slowest look
        if (dd >= 9) continue;
        float g = ringFalloff[(int)(dd * (255 / 9.0f))] * ringGain[k];
        r += 7 * g;
        lit += g;
      }
      vx += sx * r * w[SHAPE_SPEAKING];
      vy += p.y * r * w[SHAPE_SPEAKING];
      vz += sz * r * w[SHAPE_SPEAKING];
      lit *= w[SHAPE_SPEAKING];
    }
    if (w[SHAPE_DONE] > .001f) {  // a ring, and a check mark inside it
      if (i < ring) {
        float q = (float)i / ring * TAU_F, rr = 173 + 9 * p.sa;
        vx += fastCos(q) * rr * w[SHAPE_DONE];
        vy += fastSin(q) * rr * w[SHAPE_DONE];
        vz += 8 * p.sa * w[SHAPE_DONE];
      } else {
        float q = (float)(i - ring) / (PARTICLES - ring);
        bool first = q < .38f;
        float v = first ? q / .38f : (q - .38f) / .62f;
        vx += ((first ? -81 + 58 * v : -23 + 116 * v) + 6 * p.sa) * w[SHAPE_DONE];
        vy += ((first ? 57 * v : 57 - 133 * v) + 6 * p.ca) * w[SHAPE_DONE];
      }
    }
    float depth = (vz + 240) / 480, persp = 850 / (850 - vz), alpha = .22f + .72f * depth + .35f * env * ws;
    float r = (.8f + depth * 1.35f) * (.75f + .25f * fastSin(p.a + p16)) * fine * (1 + .5f * min(1.0f, lit));
    float d = r * 9 * unit, size = max(d, 2.0f), k = min(1.0f, d * d / (size * size));  // small-point fade
    float a = min(1.0f, (alpha + 1.2f * lit) * light);
    float spark = vz > 75 || lit > .25f ? (max(alpha - .5f, 0.0f) + lit * .8f) * .75f * light : 0;
    screenParticles[i] = {cx + vx * persp * unit, cy + vy * persp * unit, size / 2, a * k, spark * k};
  }

  // The halo (the 2D path's soft radial wash of the orb's colour) as a table by distance, already
  // faded by ui.html's opacity, so each pixel below is a lookup, not a divide.
  static uint16_t halo[3][ORB_RADIUS_STEPS];
  float glow = .075f + .05f * env * ws, haloRadius = (305 + 25 * env * ws) * unit, o = m.opacity;
  for (int step = 0; step < ORB_RADIUS_STEPS; step++) {
    float d = step / 4.0f / haloRadius;
    float a = d < .57f ? glow - glow * .53f * (d / .57f) : d < 1 ? glow * .47f * (1 - (d - .57f) / .43f) : 0;
    for (int c = 0; c < 3; c++) halo[c][step] = (uint16_t)((ORB_BG + (rgb[c] - ORB_BG) * a * o) * 64);
  }
  orbStageUs[0] += esp_timer_get_time() - stage;
  stage = esp_timer_get_time();

  // Band by band: add up the sprites, then halo + sprites, ui.html's CSS opacity and error
  // grayscale, a 4x4 dither against banding, out to RGB565. Most pixels have no sprite on them:
  // they take their colour from haloPixels, made once a frame for every distance and dither cell.
  static const uint8_t BAYER[16] = {0, 8, 2, 10, 12, 4, 14, 6, 3, 11, 1, 9, 15, 7, 13, 5};
  const uint32_t opacity = (uint32_t)(o * 256), gray = (uint32_t)(m.gray * 256);
  const uint32_t colour[3] = {(uint32_t)rgb[0], (uint32_t)rgb[1], (uint32_t)rgb[2]};
  auto toRgb565 = [gray](uint32_t r, uint32_t g, uint32_t b, uint32_t dither) -> uint16_t {
    if (r > 255) r = 255;
    if (g > 255) g = 255;
    if (b > 255) b = 255;
    if (gray) {
      uint32_t l = (54 * r + 183 * g + 19 * b) >> 8;
      r = (r * (256 - gray) + l * gray) >> 8;
      g = (g * (256 - gray) + l * gray) >> 8;
      b = (b * (256 - gray) + l * gray) >> 8;
    }
    r = min<uint32_t>(255, r + (dither >> 1));
    g = min<uint32_t>(255, g + (dither >> 2));
    b = min<uint32_t>(255, b + (dither >> 1));
    return (r >> 3) << 11 | (g >> 2) << 5 | (b >> 3);
  };
  for (int step = 0; step < ORB_RADIUS_STEPS; step++)
    for (int cell = 0; cell < 16; cell++)
      haloPixels[step * 16 + cell] = toRgb565(halo[0][step] >> 6, halo[1][step] >> 6, halo[2][step] >> 6, BAYER[cell]);

  // Each particle filed under the one or two bands it touches (a counting sort): going through
  // all of them for every band read a megabyte of PSRAM a frame.
  static constexpr int BANDS = RENDER_H / BAND_ROWS;
  static uint16_t bandStart[BANDS + 1], bandFill[BANDS], bandMembers[PARTICLES * 2];
  auto bandRange = [](const ScreenParticle &p, int &first, int &last) {
    first = max(0, (int)floorf(p.y - p.radius) / BAND_ROWS);
    last = min(BANDS - 1, (int)ceilf(p.y + p.radius) / BAND_ROWS);
  };
  memset(bandFill, 0, sizeof bandFill);
  for (int i = 0; i < PARTICLES; i++) {
    int first, last;
    bandRange(screenParticles[i], first, last);
    for (int b = first; b <= last; b++) bandFill[b]++;
  }
  bandStart[0] = 0;
  for (int b = 0; b < BANDS; b++) bandStart[b + 1] = bandStart[b] + bandFill[b];
  memset(bandFill, 0, sizeof bandFill);
  for (int i = 0; i < PARTICLES; i++) {
    int first, last;
    bandRange(screenParticles[i], first, last);
    for (int b = first; b <= last; b++) bandMembers[bandStart[b] + bandFill[b]++] = i;
  }

  for (int bandTop = 0; bandTop < RENDER_H; bandTop += BAND_ROWS) {
    memset(bandDots, 0, sizeof bandDots);
    memset(bandSparks, 0, sizeof bandSparks);
    int band = bandTop / BAND_ROWS;
    for (int k = bandStart[band]; k < bandStart[band + 1]; k++) splatIntoBand(screenParticles[bandMembers[k]], bandTop);
    for (int y = bandTop; y < bandTop + BAND_ROWS; y++) {
      const int bayerRow = (y & 3) * 4;
      const uint16_t *dots = bandDots + (y - bandTop) * RENDER_W, *sparks = bandSparks + (y - bandTop) * RENDER_W;
      const uint16_t *radius = orbRadius + (y < RENDER_H / 2 ? RENDER_H / 2 - 1 - y : y - RENDER_H / 2) * (RENDER_W / 2);
      uint16_t *pixel = out + y * RENDER_W;
      // past the largest halo (speaking, full size) the frame is always the canvas colour: skip it
      int dy = y < RENDER_H / 2 ? RENDER_H / 2 - y : y - RENDER_H / 2 + 1, reach = dy < ORB_HALO_MAX ? (int)sqrtf(ORB_HALO_MAX * ORB_HALO_MAX - dy * dy) + 1 : 0;
      for (int x = max(0, RENDER_W / 2 - reach); x < min(RENDER_W, RENDER_W / 2 + reach); x++) {
        int step = radius[x < RENDER_W / 2 ? RENDER_W / 2 - 1 - x : x - RENDER_W / 2], cell = bayerRow + (x & 3);
        uint32_t dot = dots[x], spark = sparks[x];
        if (!(dot | spark)) {
          pixel[x] = haloPixels[step * 16 + cell];
          continue;
        }
        uint32_t white = 255 * spark, value[3];
        for (int c = 0; c < 3; c++) value[c] = (halo[c][step] + (((colour[c] * dot + white) >> 8) * opacity >> 2)) >> 6;
        pixel[x] = toRgb565(value[0], value[1], value[2], BAYER[cell]);
      }
    }
  }
  orbStageUs[1] += esp_timer_get_time() - stage;
}

// ---------- the render task (tick) ----------

const char *dominantLook(const float *weights) {
  static const char *const names[SHAPE_COUNT] = {"listening", "thinking", "searching", "speaking", "done"};
  int best = 0;
  for (int s = 1; s < SHAPE_COUNT; s++)
    if (weights[s] > weights[best]) best = s;
  return names[best];
}

void renderOrbTask(void *) {
  OrbMotion m{};
  m.weights[SHAPE_LISTENING] = 1;
  m.scale = .84f;
  m.opacity = .5f;
  OrbRequest seen;
  uint32_t lineVersion = ~0u;
  double last = secondsNow(), statsSince = last;
  float previousEnv = 0;
  int frames = 0;
  int64_t paintUs = 0;
  for (;;) {
    int64_t frameStart = esp_timer_get_time();
    xSemaphoreTake(orbMutex, portMAX_DELAY);
    seen.shape = orbRequest.shape;
    seen.level = orbRequest.level;
    seen.scale = orbRequest.scale;
    seen.opacity = orbRequest.opacity;
    seen.gray = orbRequest.gray;
    seen.visible = orbRequest.visible;
    if (orbRequest.lineVersion != lineVersion) {
      lineVersion = orbRequest.lineVersion;
      seen.words = orbRequest.words;
      seen.lineStart = orbRequest.lineStart;
      seen.lineDone = false;
    }
    xSemaphoreGive(orbMutex);
    if (!seen.visible) {  // hidden behind the keyboard: no point drawing
      vTaskDelay(pdMS_TO_TICKS(100));
      last = secondsNow();
      continue;
    }

    double now = secondsNow();
    float dt = min(now - last, .05);
    last = now;
    m.t += dt;
    float k = 1 - expf(-dt * 7);
    for (int s = 0; s < SHAPE_COUNT; s++) m.weights[s] += ((s == seen.shape ? 1 : 0) - m.weights[s]) * k;
    m.level = seen.level;
    m.scale += (seen.scale - m.scale) * (1 - expf(-dt / .22f));  // ui.html: transform .8s ease-out
    m.opacity += (seen.opacity - m.opacity) * (1 - expf(-dt / .18f));  // opacity .6s
    m.gray += (seen.gray - m.gray) * (1 - expf(-dt / .18f));

    float raw = 0;
    if (!seen.words.empty()) {
      float lineTime = now - seen.lineStart;
      raw = pulseEnvelope(seen.words, lineTime);
      if (!seen.lineDone && lineTime > seen.words.back().end + .1f) {
        seen.lineDone = true;  // the reply is over: back to rest, as say() does
        xSemaphoreTake(orbMutex, portMAX_DELAY);
        if (orbRequest.shape == SHAPE_SPEAKING && orbRequest.lineVersion == lineVersion) orbRequest.shape = SHAPE_LISTENING;
        if (orbRequest.lineVersion == lineVersion) orbRequest.waitingForVoice = false;  // a chime later isn't its voice
        xSemaphoreGive(orbMutex);
      }
    }
    previousEnv = m.env;
    float frames60 = dt * 60;  // the web eases per 60 Hz frame; same feel at any frame rate
    m.env += (raw - m.env) * (1 - powf(1 - (raw > m.env ? .55f : .18f), frames60));
    // a syllable is a fast rise in the envelope; each one sends a bright ring up the sphere
    if (m.env - previousEnv > .06f * frames60 && (m.onsets.empty() || m.t - m.onsets.back() > .12)) m.onsets.push_back(m.t);
    while (!m.onsets.empty() && m.t - m.onsets.front() >= 1.2) m.onsets.erase(m.onsets.begin());

    static double lastEnvLog = 0;
    if (m.weights[SHAPE_SPEAKING] > .5f && m.t - lastEnvLog > .2) {
      lastEnvLog = m.t;
      Serial.printf("[orb] speaking: envelope %.2f, %d rings\n", m.env, (int)m.onsets.size());
    }
    xSemaphoreTake(orbMutex, portMAX_DELAY);
    int target = 0;
    while (target == orbShown || target == orbReady) target++;
    xSemaphoreGive(orbMutex);
    paintOrb(orbFrames[target], m);
    xSemaphoreTake(orbMutex, portMAX_DELAY);
    orbReady = target;
    xSemaphoreGive(orbMutex);

    int64_t spent = esp_timer_get_time() - frameStart;
    paintUs += spent;
    frames++;
    if (now - statsSince >= 2) {
      Serial.printf("[orb] %s: %d particles, %.1f ms a frame (particles %.1f, pixels %.1f), %.1f fps drawn, %.1f shown\n",
                    dominantLook(m.weights), PARTICLES, paintUs / 1000.0 / frames, orbStageUs[0] / 1000.0 / frames,
                    orbStageUs[1] / 1000.0 / frames, frames / (now - statsSince), orbFramesShown / (now - statsSince));
      statsSince = now;
      frames = 0;
      paintUs = 0;
      orbStageUs[0] = orbStageUs[1] = 0;
      orbFramesShown = 0;
    }
    // at least 4 ms off the core every frame: drawing flat out starved the mic of a quarter of its packets
    vTaskDelay(pdMS_TO_TICKS(max<int64_t>(4, (ORB_FRAME_US - spent) / 1000 + 1)));
  }
}

// ---------- what the screen calls ----------

// Called from loop(), the task that owns the panel: puts the newest finished frame on screen. It goes
// straight to the panel rather than through LVGL, which would re-blend the whole rectangle each
// time; the rows under Kiki's caption are left to LVGL, and nothing is pushed while History or
// the keyboard covers the orb.
void showNewestOrbFrame() {
  xSemaphoreTake(orbMutex, portMAX_DELAY);
  int ready = orbReady;
  bool visible = orbRequest.visible;
  if (ready >= 0) {
    orbShown = ready;
    orbReady = -1;
  }
  xSemaphoreGive(orbMutex);
  if (ready < 0 || !visible || orbCovered()) return;
  lv_area_t area;
  orbAreaCoords(&area);
  int rows = (ORB_H - orbRowsUnderCaption()) / ORB_RENDER_SCALE;
  int left = area.x1 + (lv_area_get_width(&area) - ORB_W) / 2;
  if (rows > 0) blitToPanel(orbFrames[ready], RENDER_W, rows, left, area.y1, ORB_RENDER_SCALE);
  orbFramesShown++;
}

// shape and level as ui.html's ORB_SHAPES; dimmed = its idle CSS, faded = its error CSS
void setOrbLook(OrbShape shape, float level, bool dimmed, bool faded) {
  xSemaphoreTake(orbMutex, portMAX_DELAY);
  orbRequest.shape = shape;
  orbRequest.level = level;
  orbRequest.scale = dimmed || faded ? .84f : 1;
  orbRequest.opacity = faded ? .4f : dimmed ? .5f : 1;
  orbRequest.gray = faded ? 1 : 0;
  xSemaphoreGive(orbMutex);
}

// A reply: the orb speaks it (say()), its envelope paced from the words; startNow restarts the clock
// when Kiki's voice actually starts, so the swelling lines up with the sound.
void orbSays(const String &text) {
  std::vector<SpokenWord> words = estimateWords(text);
  xSemaphoreTake(orbMutex, portMAX_DELAY);
  orbRequest.words = words;
  orbRequest.lineStart = secondsNow();
  orbRequest.lineVersion++;
  orbRequest.waitingForVoice = true;
  orbRequest.shape = SHAPE_SPEAKING;
  xSemaphoreGive(orbMutex);
}

// Restarts the reply's clock when its voice starts: when Kiki says "speaking" and, closer still,
// when the Tab5's own speaker starts playing it (~0.3 s later), so the swelling lines up with the
// sound. A chime is playback too, but it comes with no reply waiting, so it changes nothing.
void orbVoiceStarted(bool playingOnTab5) {
  xSemaphoreTake(orbMutex, portMAX_DELAY);
  if (orbRequest.waitingForVoice) {
    orbRequest.lineStart = secondsNow();
    orbRequest.lineVersion++;
    if (playingOnTab5) {
      orbRequest.waitingForVoice = false;
      Serial.println("[orb] the reply's clock restarts: the Tab5 started playing it");
    }
  }
  xSemaphoreGive(orbMutex);
}

void setOrbVisible(bool visible) {
  xSemaphoreTake(orbMutex, portMAX_DELAY);
  orbRequest.visible = visible;
  xSemaphoreGive(orbMutex);
}

void startOrb(lv_obj_t *parent) {
  orbMutex = xSemaphoreCreateMutex();
  orbSeeds = (OrbSeed *)heap_caps_malloc(sizeof(OrbSeed) * PARTICLES, MALLOC_CAP_SPIRAM);
  orbRadius = (uint16_t *)heap_caps_malloc(sizeof(uint16_t) * RENDER_W / 2 * RENDER_H / 2, MALLOC_CAP_SPIRAM);
  haloPixels = (uint16_t *)heap_caps_malloc(sizeof(uint16_t) * ORB_RADIUS_STEPS * 16, MALLOC_CAP_SPIRAM);
  for (uint16_t *&frame : orbFrames) {
    frame = (uint16_t *)heap_caps_aligned_alloc(64, sizeof(uint16_t) * RENDER_W * RENDER_H, MALLOC_CAP_SPIRAM | MALLOC_CAP_DMA);
    for (int p = 0; p < RENDER_W * RENDER_H; p++) frame[p] = (ORB_BG >> 3) << 11 | (ORB_BG >> 2) << 5 | (ORB_BG >> 3);
  }
  for (int i = 0; i <= 1024; i++) sineTable[i] = sinf(i * 2 * PI / 1024);
  for (int i = 0; i < 256; i++) ringFalloff[i] = expf(-i * 9.0f / 255);
  screenParticles = (ScreenParticle *)heap_caps_malloc(sizeof(ScreenParticle) * PARTICLES, MALLOC_CAP_SPIRAM);
  makeOrbSeeds();
  for (int y = 0; y < RENDER_H / 2; y++)
    for (int x = 0; x < RENDER_W / 2; x++)
      orbRadius[y * (RENDER_W / 2) + x] = (uint16_t)(hypotf(x + .5f, y + .5f) * 4);
  for (int i = 0; i < 256; i++) {  // fragment shader: dot and spark as functions of r
    float r = sqrtf(i / 255.0f);
    dotProfile[i] = (1 + (.065f - 1) * smoothstep(.17f, .23f, r)) * (1 - smoothstep(.9f, 1, r));
    sparkProfile[i] = (1 + (.065f - 1) * smoothstep(.08f, .12f, r)) * (1 - smoothstep(.17f, .2f, r));
  }
  // the second core, below the audio tasks (priority 3), so the orb never delays the mic or speaker
  xTaskCreatePinnedToCore(renderOrbTask, "orb", 8192, nullptr, 1, nullptr, 0);
}

/*
The orb's code above is a port of speaking-orb.js:

MIT License

Copyright (c) 2026 Ship Notes

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
*/
