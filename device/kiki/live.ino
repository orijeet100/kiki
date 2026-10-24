// The Cart filling, live (v0.19, FR-0.42): while Kiki fills the Instacart Cart, the extension sends
// Chrome's screencast of Kiki's tab to Kiki, and the Tab5 shows the newest frame where the orb is.
// networkTask fetches it (GET /instacart/frame) into liveJpeg; the loop decodes it in hardware and
// puts it on the panel. liveJpegBytes hands the buffer over: networkTask writes only while it's 0.
// While it shows, the screen is view only: a blocker over everything but the volume bar takes
// every touch, and the keyboard, History and the item sheet close first, so nothing covers the
// frame or opens over it. The orb stays off for the whole time (showNewestOrbFrame), whatever
// else turns it back on.

static constexpr size_t LIVE_MAX_JPEG = 256 * 1024;  // Kiki's MAX_FRAME_BYTES
static constexpr int LIVE_H = 360;                   // the orb's slot (ORB_H); Chrome sends at most 720x360
static constexpr uint32_t LIVE_EVERY_MS = 150;

jpeg_decoder_handle_t liveDecoder;
uint8_t *liveJpeg;
uint16_t *livePixels;
size_t liveJpegCap, livePixelsCap;
std::atomic<uint32_t> liveJpegBytes{0};
volatile bool liveView = false;  // set by the loop from Kiki's events, read by networkTask
lv_obj_t *liveBlocker;

// After startScreen(): the blocker sits above the item sheet, built there.
void startLiveView() {
  liveBlocker = makeBox(lv_layer_top());
  lv_obj_set_size(liveBlocker, W, H - 88);  // the volume bar (88 px) stays in reach: Kiki speaks when the fill ends
  lv_obj_add_flag(liveBlocker, LV_OBJ_FLAG_CLICKABLE);  // a touch lands here, and nowhere under it
  lv_obj_add_flag(liveBlocker, LV_OBJ_FLAG_HIDDEN);
  jpeg_decode_engine_cfg_t engine = {};
  engine.timeout_ms = 200;
  jpeg_new_decoder_engine(&engine, &liveDecoder);
  jpeg_decode_memory_alloc_cfg_t in = {JPEG_DEC_ALLOC_INPUT_BUFFER}, out = {JPEG_DEC_ALLOC_OUTPUT_BUFFER};
  liveJpeg = (uint8_t *)jpeg_alloc_decoder_mem(LIVE_MAX_JPEG, &in, &liveJpegCap);
  livePixels = (uint16_t *)jpeg_alloc_decoder_mem(W * (LIVE_H + 16) * 2, &out, &livePixelsCap);  // rows padded to 16
}

// "Filling cart, 4 of 12" turns it on; the fill's turn, any state but thinking, or losing Kiki
// turns it off. A rename being typed is dropped; a quantity still settling is sent.
void setLiveView(bool on) {
  if (on == liveView) return;
  liveView = on;
  if (on) {
    closeKeyboard();
    closeHistory();
    closeItemSheet();
    lv_indev_reset(nullptr, nullptr);  // a finger already down lets go of what it pressed
    lv_obj_remove_flag(liveBlocker, LV_OBJ_FLAG_HIDDEN);
  } else {
    lv_obj_add_flag(liveBlocker, LV_OBJ_FLAG_HIDDEN);
  }
  lv_area_t area;
  orbAreaCoords(&area);
  lv_obj_invalidate_area(lv_screen_active(), &area);  // LVGL clears the slot: the orb's edges, or the last frame
  Serial.printf("[live] %s\n", on ? "showing the Cart filling" : "back to the orb");
}

// Runs on networkTask only.
void fetchLiveFrame() {
  static uint32_t nextAt = 0;
  if (!liveView || liveJpegBytes || millis() < nextAt) return;
  nextAt = millis() + LIVE_EVERY_MS;
  HTTPClient http;
  http.setTimeout(1000);
  http.begin(kikiUrl("/instacart/frame"));
  int status = http.GET(), size = http.getSize();
  if (status == 200 && size > 0 && (size_t)size <= liveJpegCap && http.getStream().readBytes(liveJpeg, size) == (size_t)size)
    liveJpegBytes = size;
  http.end();
}

// Called from loop(), after the orb.
void showLiveFrame() {
  static uint32_t frames = 0;
  uint32_t bytes = liveJpegBytes;
  if (!bytes) return;
  jpeg_decode_picture_info_t info;
  if (liveView && !orbCovered() && jpeg_decoder_get_info(liveJpeg, bytes, &info) == ESP_OK && info.width <= W &&
      info.height <= LIVE_H) {
    jpeg_decode_cfg_t cfg = {};
    cfg.output_format = JPEG_DECODE_OUT_FORMAT_RGB565;
    cfg.rgb_order = JPEG_DEC_RGB_ELEMENT_ORDER_BGR;  // little-endian 565, what the panel's framebuffer holds
    cfg.conv_std = JPEG_YUV_RGB_CONV_STD_BT601;
    uint32_t out = 0, start = millis();
    esp_err_t err = jpeg_decoder_process(liveDecoder, &cfg, liveJpeg, bytes, (uint8_t *)livePixels, livePixelsCap, &out);
    if (err == ESP_OK) {
      int stride = (info.width + 15) & ~15;  // the decoder's rows are whole 16 px blocks
      lv_area_t area;
      orbAreaCoords(&area);
      blitToPanel(livePixels, stride, info.height, area.x1 + (W - stride) / 2, area.y1 + (LIVE_H - info.height) / 2, 1);
      if (++frames % 20 == 1)
        Serial.printf("[live] frame %lu: %lux%lu, %lu KB, %lu ms\n", frames, info.width, info.height, bytes / 1024, millis() - start);
    } else {
      Serial.printf("[live] decode failed: %s\n", esp_err_to_name(err));
    }
  }
  liveJpegBytes = 0;
}
