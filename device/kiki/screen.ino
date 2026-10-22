// The UI, natively: docs/ui.md's layout in DESIGN.md's tokens (its Kiki overrides), drawn by
// LVGL into M5GFX. Sizes are the web UI's px x1.5 so it reads across a kitchen: one centered
// column 660 px wide with 30 px gutters. LVGL redraws only what changed (a full 720x1280 push
// takes 78 ms on this panel); the orb (orb.ino) is its own rectangle, redrawn every frame.

LV_FONT_DECLARE(inter_48);       // the state label: the screen's one display line
LV_FONT_DECLARE(inter_32_bold);  // wordmark and panel titles
LV_FONT_DECLARE(inter_24);       // body: items, the caption, text box, run text (+ keyboard symbols)
LV_FONT_DECLARE(inter_20);       // small: buttons, chips, counts, hints, times

// DESIGN.md's tokens. The panel is 16-bit, which keeps 5 bits of red and blue but 6 of green: a
// dark gray that isn't a multiple of 8 comes out greenish, so the surfaces are rounded to one.
const lv_color_t CANVAS = lv_color_hex(0x080808), SURFACE_1 = lv_color_hex(0x181818),
                 SURFACE_2 = lv_color_hex(0x202020), HAIRLINE = lv_color_hex(0x282828),
                 INK = lv_color_hex(0xffffff), INK_MUTED = lv_color_hex(0x999999),
                 ON_PRIMARY = lv_color_hex(0x000000), ACCENT_BLUE = lv_color_hex(0x0099ff),
                 SUCCESS = lv_color_hex(0x22c55e), ERROR_RED = lv_color_hex(0xff5c5c);

static constexpr int COLUMN_W = 660;
static constexpr int ROW_W = 285, ROW_H = 72;  // two columns in the list card's 600 px
static constexpr int LIST_MAX_H = 6 * ROW_H, LIST_MAX_H_TYPING = 3 * ROW_H;  // then it scrolls
static constexpr int SHEET_W = 620;
static const char *const SUGGESTIONS[] = {"add bread and two milks", "make it three milks", "what's on the list"};

lv_obj_t *connectionDot, *connectionLabel, *historyCountLabel;
lv_obj_t *orbArea, *captionLabel, *stateLabel, *lastRunRow;
lv_obj_t *listCountLabel, *listRows;
lv_obj_t *composer, *commandInput, *formErrorLabel, *keyboard;
lv_obj_t *volumePercentLabel;
lv_obj_t *historyBackdrop = nullptr, *historySheet = nullptr, *historyRunsList = nullptr;
lv_timer_t *doneTimer = nullptr, *ringTimer = nullptr, *captionTimer = nullptr;
std::vector<lv_obj_t *> listRowObjects;
std::vector<SpokenWord> captionWords;  // the reply's words and when each starts, from the orb's estimate
String captionText;
uint32_t captionStartMs = 0;

// ---------- building blocks ----------

// A plain container: none of the theme's look, no scrolling, until asked.
lv_obj_t *makeBox(lv_obj_t *parent) {
  lv_obj_t *box = lv_obj_create(parent);
  lv_obj_remove_style_all(box);
  lv_obj_remove_flag(box, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_set_size(box, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
  return box;
}

lv_obj_t *makeText(lv_obj_t *parent, const lv_font_t *font, lv_color_t color, const String &text) {
  lv_obj_t *label = lv_label_create(parent);
  lv_obj_set_style_text_font(label, font, 0);
  lv_obj_set_style_text_color(label, color, 0);
  lv_label_set_text(label, text.c_str());
  return label;
}

void stackChildren(lv_obj_t *box, lv_flex_flow_t flow, int gap, lv_flex_align_t main, lv_flex_align_t cross) {
  lv_obj_set_flex_flow(box, flow);
  lv_obj_set_flex_align(box, main, cross, cross);
  lv_obj_set_style_pad_row(box, gap, 0);
  lv_obj_set_style_pad_column(box, gap, 0);
}

void fill(lv_obj_t *obj, lv_color_t color, lv_style_selector_t selector = 0) {
  lv_obj_set_style_bg_color(obj, color, selector);
  lv_obj_set_style_bg_opa(obj, LV_OPA_COVER, selector);
}

// Framer's pill buttons: white primary, charcoal secondary; pressing darkens one step.
lv_obj_t *makePillButton(lv_obj_t *parent, const String &text, bool primary) {
  lv_obj_t *button = makeBox(parent);
  lv_obj_add_flag(button, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_set_style_radius(button, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_pad_hor(button, 24, 0);
  lv_obj_set_style_pad_ver(button, 15, 0);
  fill(button, primary ? INK : SURFACE_1);
  fill(button, primary ? lv_color_hex(0xd8d8d8) : SURFACE_2, LV_STATE_PRESSED);
  stackChildren(button, LV_FLEX_FLOW_ROW, 8, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
  makeText(button, &inter_20, primary ? ON_PRIMARY : INK, text);
  return button;
}

lv_obj_t *makeChip(lv_obj_t *parent, const Chip &chip, lv_color_t background) {
  lv_obj_t *box = makeBox(parent);
  fill(box, background);
  lv_obj_set_style_radius(box, 9, 0);
  lv_obj_set_style_pad_hor(box, 12, 0);
  lv_obj_set_style_pad_ver(box, 5, 0);
  makeText(box, &inter_20, chip.failed ? ERROR_RED : INK, chip.text);
  return box;
}

void onClick(lv_obj_t *obj, lv_event_cb_t handler, void *data = nullptr) {
  lv_obj_add_event_cb(obj, handler, LV_EVENT_CLICKED, data);
}

// ---------- input: the finger, or a "tap x y" from the serial port ----------

int16_t pressedFromX, pressedFromY, pressedToX, pressedToY;
uint32_t pressedSince = 0, pressedFor = 0;
uint32_t tapReleasedAt = 0;  // measuring: a test tap's release, until the first pixels it causes reach the panel

// A press from (x0, y0) moving to (x1, y1) over ms, as a finger would: a tap when they're the same.
void pressScreenAlong(int x0, int y0, int x1, int y1, uint32_t ms) {
  pressedFromX = x0;
  pressedFromY = y0;
  pressedToX = x1;
  pressedToY = y1;
  pressedSince = millis();
  pressedFor = ms;
}

void pressScreenFor(int x, int y, uint32_t ms) {
  pressScreenAlong(x, y, x, y, ms);
  tapReleasedAt = millis() + ms;
}

void measureFullRedraw() {
  uint32_t start = millis();
  lv_obj_invalidate(lv_screen_active());
  lv_refr_now(nullptr);
  Serial.printf("[measure] full-screen redraw: %lu ms\n", millis() - start);
}

void readTouch(lv_indev_t *, lv_indev_data_t *data) {
  uint32_t pressedMs = millis() - pressedSince;
  if (pressedMs < pressedFor) {
    float along = (float)pressedMs / pressedFor;
    data->point.x = pressedFromX + (int32_t)((pressedToX - pressedFromX) * along);
    data->point.y = pressedFromY + (int32_t)((pressedToY - pressedFromY) * along);
    data->state = LV_INDEV_STATE_PRESSED;
    return;
  }
  auto touch = M5.Touch.getDetail();
  data->state = touch.isPressed() ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
  if (touch.isPressed()) {
    data->point.x = touch.x;
    data->point.y = touch.y;
  }
}

// ---------- pixels to the panel: the P4's PPA copies (and scales) them into the DSI framebuffer ----------

ppa_client_handle_t pixelCopier = nullptr;
uint16_t *panelFramebuffer = nullptr;

// The framebuffer M5GFX hands the DSI controller (one buffer; it refreshes from it continuously).
void startPixelCopier() {
  panelFramebuffer = (uint16_t *)((lgfx::Panel_DSI *)M5.Display.getPanel())->config_detail().buffer;
  ppa_client_config_t client = {};
  client.oper_type = PPA_OPERATION_SRM;
  client.max_pending_trans_num = 1;
  if (!panelFramebuffer || ppa_register_client(&client, &pixelCopier) != ESP_OK) pixelCopier = nullptr;
  Serial.printf("[screen] PPA pixel copies %s\n", pixelCopier ? "on" : "off: M5GFX copies instead");
}

// Puts w x h pixels (rows of srcW) at (x, y), scaled by `scale`: the PPA's DMA does the copy, so
// the CPU is free; M5GFX's CPU copy if the PPA isn't there.
void blitToPanel(const uint16_t *pixels, int srcW, int rows, int x, int y, int scale) {
  if (pixelCopier) {
    ppa_srm_oper_config_t copy = {};
    copy.in.buffer = pixels;
    copy.in.pic_w = srcW;
    copy.in.pic_h = rows;
    copy.in.block_w = srcW;
    copy.in.block_h = rows;
    copy.in.srm_cm = PPA_SRM_COLOR_MODE_RGB565;
    copy.out.buffer = panelFramebuffer;
    copy.out.buffer_size = W * H * 2;
    copy.out.pic_w = W;
    copy.out.pic_h = H;
    copy.out.block_offset_x = x;
    copy.out.block_offset_y = y;
    copy.out.srm_cm = PPA_SRM_COLOR_MODE_RGB565;
    copy.rotation_angle = PPA_SRM_ROTATION_ANGLE_0;
    copy.scale_x = copy.scale_y = scale;
    copy.mode = PPA_TRANS_MODE_BLOCKING;
    if (ppa_do_scale_rotate_mirror(pixelCopier, &copy) == ESP_OK) return;
  }
  if (scale == 1) M5.Display.pushImage(x, y, srcW, rows, (const m5gfx::rgb565_t *)pixels);
  else M5.Display.pushImageRotateZoom(x, y, 0, 0, 0, scale, scale, srcW, rows, (const m5gfx::rgb565_t *)pixels);
}

void flushToPanel(lv_display_t *display, const lv_area_t *area, uint8_t *pixels) {
  if (tapReleasedAt && millis() >= tapReleasedAt) {
    Serial.printf("[measure] tap to pixels on the panel: %lu ms after release\n", millis() - tapReleasedAt);
    tapReleasedAt = 0;
  }
  blitToPanel((const uint16_t *)pixels, lv_area_get_width(area), lv_area_get_height(area), area->x1, area->y1, 1);
  lv_display_flush_ready(display);
}

uint32_t millisForLvgl() { return millis(); }

// ---------- state, caption, last run ----------

void orbAreaCoords(lv_area_t *area) { lv_obj_get_coords(orbArea, area); }

bool orbCovered() { return historySheet || !lv_obj_has_flag(keyboard, LV_OBJ_FLAG_HIDDEN); }

// The caption sits over the orb's lower halo; LVGL draws those rows while it shows.
int orbRowsUnderCaption() {
  if (captionText.isEmpty()) return 0;
  lv_area_t caption, orb;
  lv_obj_get_coords(captionLabel, &caption);
  lv_obj_get_coords(orbArea, &orb);
  return max(0, (int)(orb.y2 - caption.y1 + 1));
}

void showKikiState(const String &state, bool showDoneFirst) {
  static const char *const labels[][2] = {{"idle", "Idle"},
                                          {"listening", "Listening…"},
                                          {"thinking", "Thinking…"},
                                          {"speaking", "Speaking"},
                                          {"error", "Something went wrong"}};
  String label = state;
  for (auto &pair : labels)
    if (state == pair[0]) label = pair[1];
  lv_label_set_text(stateLabel, label.c_str());
  lv_obj_set_style_text_color(stateLabel, state == "error" ? ERROR_RED : INK, 0);
  if (state == "listening" || state == "thinking") showCaption("");  // a new command: the old reply goes
  if (state == "speaking") orbVoiceStarted(false);

  // ui.html's ORB_SHAPES, its idle and error CSS, and the check mark after a run without an error
  if (doneTimer) {
    lv_timer_delete(doneTimer);
    doneTimer = nullptr;
  }
  bool dimmed = state == "idle", faded = state == "error";
  OrbShape shape = state == "thinking" ? SHAPE_THINKING : state == "speaking" ? SHAPE_SPEAKING : SHAPE_LISTENING;
  float level = state == "listening" ? 1 : state == "thinking" || state == "speaking" ? .5f : 0;
  if (showDoneFirst) {
    setOrbLook(SHAPE_DONE, level, dimmed, faded);
    doneTimer = lv_timer_create(
        [](lv_timer_t *) {
          doneTimer = nullptr;
          setOrbLook(SHAPE_LISTENING, 0, kikiState == "idle", kikiState == "error");
        },
        DONE_MS, nullptr);
    lv_timer_set_repeat_count(doneTimer, 1);
  } else {
    setOrbLook(shape, level, dimmed, faded);
  }
}

// Kiki's reply appears word by word on the orb's timing, as the web UI's captions do.
void revealCaptionWords(lv_timer_t *timer) {
  float elapsed = (millis() - captionStartMs) / 1000.0f;
  int shownWords = 0;
  while (shownWords < (int)captionWords.size() && captionWords[shownWords].start <= elapsed) shownWords++;
  int end = 0;
  for (int i = 0; i < shownWords; i++) {
    int space = captionText.indexOf(' ', end + 1);
    end = space < 0 ? captionText.length() : space;
  }
  lv_label_set_text(captionLabel, captionText.substring(0, end).c_str());
  if (shownWords == (int)captionWords.size()) lv_timer_pause(timer);
}

void showCaption(const String &text) {
  captionText = text;
  captionWords = estimateWords(text);
  captionStartMs = millis();
  lv_label_set_text(captionLabel, "");
  if (!captionTimer) captionTimer = lv_timer_create(revealCaptionWords, 40, nullptr);
  if (text.isEmpty()) lv_timer_pause(captionTimer);
  else lv_timer_resume(captionTimer);
}

void useSuggestion(lv_event_t *event) {
  lv_textarea_set_text(commandInput, SUGGESTIONS[(intptr_t)lv_event_get_user_data(event)]);
  openKeyboard();
}

// One quiet line under the state: what Kiki heard, in quotes, then what it did; it opens
// History. Before the first run, three example commands that fill the text box.
void showLastRun() {
  lv_obj_clean(lastRunRow);
  if (runs.empty()) {
    lv_obj_remove_flag(lastRunRow, LV_OBJ_FLAG_CLICKABLE);
    for (intptr_t i = 0; i < 3; i++) {
      lv_obj_t *button = makePillButton(lastRunRow, SUGGESTIONS[i], false);
      onClick(button, useSuggestion, (void *)i);
    }
    return;
  }
  lv_obj_add_flag(lastRunRow, LV_OBJ_FLAG_CLICKABLE);
  const Run &last = runs.front();
  lv_obj_t *heard = makeText(lastRunRow, &inter_20, INK, "“" + last.heard + "”");
  lv_label_set_long_mode(heard, LV_LABEL_LONG_MODE_DOTS);
  lv_obj_set_style_max_width(heard, COLUMN_W - 40, 0);
  for (const Chip &chip : last.chips) makeChip(lastRunRow, chip, SURFACE_1);
  if (last.error.length()) makeChip(lastRunRow, {"error", true}, SURFACE_1);
}

// ---------- the List ----------

void flipItem(lv_event_t *event) {
  size_t index = (intptr_t)lv_event_get_user_data(event);
  if (index < items.size()) setNeeded(items[index]);
}

void styleRowAtRest(lv_obj_t *row) {
  lv_obj_set_style_bg_opa(row, LV_OPA_TRANSP, 0);
  lv_obj_set_style_border_side(row, LV_BORDER_SIDE_BOTTOM, 0);
  lv_obj_set_style_border_width(row, 1, 0);
  lv_obj_set_style_border_color(row, SURFACE_2, 0);
}

// A changed row lifts to surface 2 with a blue ring for 1.5 s (DESIGN.md, v0.9).
void clearChangedRows(lv_timer_t *) {
  ringTimer = nullptr;
  for (Item &item : items) item.changed = false;
  for (lv_obj_t *row : listRowObjects) styleRowAtRest(row);
}

void showList() {
  int32_t scrolledTo = lv_obj_get_scroll_y(listRows);
  lv_obj_clean(listRows);
  listRowObjects.clear();
  int needed = 0;
  for (const Item &item : items) needed += item.needed;
  lv_label_set_text(listCountLabel, items.empty() ? "" : (String(needed) + (needed == 1 ? " item" : " items")).c_str());

  if (items.empty()) {
    lv_obj_t *empty = makeBox(listRows);
    lv_obj_set_width(empty, LV_PCT(100));
    lv_obj_set_style_pad_ver(empty, 36, 0);
    stackChildren(empty, LV_FLEX_FLOW_COLUMN, 10, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    makeText(empty, &inter_24, INK, "Nothing on the list yet.");
    makeText(empty, &inter_20, INK_MUTED, "Say “hey jarvis, add milk”.");
  }

  bool anyChanged = false;
  for (size_t i = 0; i < items.size(); i++) {
    const Item &item = items[i];
    lv_obj_t *row = makeBox(listRows);
    lv_obj_set_size(row, ROW_W, ROW_H);
    lv_obj_add_flag(row, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_radius(row, 15, 0);
    lv_obj_set_style_pad_hor(row, 14, 0);
    stackChildren(row, LV_FLEX_FLOW_ROW, 12, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_CENTER);
    styleRowAtRest(row);
    fill(row, SURFACE_2, LV_STATE_PRESSED);
    if (!item.needed) lv_obj_set_style_opa(row, 115, 0);  // Not needed: dimmed to 45%
    if (item.changed) {
      fill(row, SURFACE_2);
      lv_obj_set_style_border_side(row, LV_BORDER_SIDE_FULL, 0);
      lv_obj_set_style_border_width(row, 2, 0);
      lv_obj_set_style_border_color(row, ACCENT_BLUE, 0);
      anyChanged = true;
    }
    String name = item.name;
    if (name.length()) name.setCharAt(0, toupper(name[0]));
    lv_obj_t *nameLabel = makeText(row, &inter_24, INK, name);
    lv_label_set_long_mode(nameLabel, LV_LABEL_LONG_MODE_DOTS);
    lv_obj_set_flex_grow(nameLabel, 1);
    String quantity = !item.needed ? "Not needed" : item.quantity > 1 ? "× " + String(item.quantity) : "";
    makeText(row, &inter_20, INK_MUTED, quantity);
    onClick(row, flipItem, (void *)(intptr_t)i);
    listRowObjects.push_back(row);
  }
  if (anyChanged) {
    if (ringTimer) lv_timer_delete(ringTimer);
    ringTimer = lv_timer_create(clearChangedRows, 1500, nullptr);
    lv_timer_set_repeat_count(ringTimer, 1);
  }
  lv_obj_update_layout(listRows);
  lv_obj_scroll_to_y(listRows, scrolledTo, LV_ANIM_OFF);
}

// The card takes the height of its rows, up to six rows; past that the rows scroll inside it.
void buildList(lv_obj_t *screen) {
  lv_obj_t *card = makeBox(screen);
  lv_obj_set_width(card, COLUMN_W);
  lv_obj_set_style_margin_top(card, 18, 0);
  fill(card, SURFACE_1);
  lv_obj_set_style_radius(card, 30, 0);
  lv_obj_set_style_pad_top(card, 26, 0);
  lv_obj_set_style_pad_hor(card, 30, 0);
  lv_obj_set_style_pad_bottom(card, 12, 0);
  stackChildren(card, LV_FLEX_FLOW_COLUMN, 6, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);

  lv_obj_t *head = makeBox(card);
  lv_obj_set_width(head, LV_PCT(100));
  stackChildren(head, LV_FLEX_FLOW_ROW, 12, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_END);
  makeText(head, &inter_32_bold, INK, "Grocery list");
  listCountLabel = makeText(head, &inter_20, INK_MUTED, "");

  listRows = makeBox(card);
  lv_obj_set_width(listRows, LV_PCT(100));
  lv_obj_set_style_max_height(listRows, LIST_MAX_H, 0);
  lv_obj_add_flag(listRows, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_set_scroll_dir(listRows, LV_DIR_VER);
  lv_obj_set_scrollbar_mode(listRows, LV_SCROLLBAR_MODE_OFF);
  lv_obj_set_flex_flow(listRows, LV_FLEX_FLOW_ROW_WRAP);
  lv_obj_set_style_pad_column(listRows, 30, 0);
  lv_obj_set_style_pad_row(listRows, 0, 0);

  lv_obj_t *spacer = makeBox(screen);  // keeps the text box docked at the bottom
  lv_obj_set_width(spacer, 1);
  lv_obj_set_flex_grow(spacer, 1);
}

// ---------- text box and keyboard ----------

void openKeyboard() {
  if (!lv_obj_has_flag(keyboard, LV_OBJ_FLAG_HIDDEN)) return;
  lv_obj_remove_flag(keyboard, LV_OBJ_FLAG_HIDDEN);
  lv_obj_add_flag(orbArea, LV_OBJ_FLAG_HIDDEN);  // make room: the box rises above the keyboard
  setOrbVisible(false);
  lv_obj_set_style_max_height(listRows, LIST_MAX_H_TYPING, 0);
  lv_obj_set_style_border_color(composer, ACCENT_BLUE, 0);
  lv_obj_add_state(commandInput, LV_STATE_FOCUSED);
  lv_obj_set_style_border_width(commandInput, 2, LV_PART_CURSOR);
}

void closeKeyboard() {
  if (lv_obj_has_flag(keyboard, LV_OBJ_FLAG_HIDDEN)) return;
  lv_obj_add_flag(keyboard, LV_OBJ_FLAG_HIDDEN);
  lv_obj_remove_flag(orbArea, LV_OBJ_FLAG_HIDDEN);
  setOrbVisible(true);
  lv_obj_set_style_max_height(listRows, LIST_MAX_H, 0);
  lv_obj_set_style_border_color(composer, HAIRLINE, 0);
  lv_obj_remove_state(commandInput, LV_STATE_FOCUSED);
  lv_obj_set_style_border_width(commandInput, 0, LV_PART_CURSOR);
}

void submitCommand() {
  String text = lv_textarea_get_text(commandInput);
  text.trim();
  if (text.isEmpty()) return;
  if (sendCommand(text)) {
    lv_textarea_set_text(commandInput, "");
    closeKeyboard();
  }
}

void showFormError(const String &text) {
  lv_label_set_text(formErrorLabel, text.c_str());
  if (text.isEmpty()) lv_obj_add_flag(formErrorLabel, LV_OBJ_FLAG_HIDDEN);
  else lv_obj_remove_flag(formErrorLabel, LV_OBJ_FLAG_HIDDEN);
}

void onTextBoxEvent(lv_event_t *event) {
  lv_event_code_t code = lv_event_get_code(event);
  if (code == LV_EVENT_CLICKED) openKeyboard();
  else if (code == LV_EVENT_READY) submitCommand();   // the keyboard's OK and Enter keys
  else if (code == LV_EVENT_CANCEL) closeKeyboard();  // its hide-keyboard key
}

void buildDock(lv_obj_t *screen) {
  lv_obj_t *dock = makeBox(screen);
  lv_obj_set_width(dock, COLUMN_W);
  lv_obj_set_style_margin_top(dock, 16, 0);
  lv_obj_set_style_pad_bottom(dock, 14, 0);
  stackChildren(dock, LV_FLEX_FLOW_COLUMN, 12, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER);

  composer = makeBox(dock);
  lv_obj_set_size(composer, LV_PCT(100), 84);
  fill(composer, SURFACE_1);
  lv_obj_set_style_radius(composer, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_border_width(composer, 1, 0);
  lv_obj_set_style_border_color(composer, HAIRLINE, 0);
  lv_obj_set_style_pad_left(composer, 14, 0);
  lv_obj_set_style_pad_right(composer, 8, 0);
  stackChildren(composer, LV_FLEX_FLOW_ROW, 8, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER);

  commandInput = lv_textarea_create(composer);
  lv_obj_remove_style_all(commandInput);
  lv_obj_set_flex_grow(commandInput, 1);
  lv_obj_set_style_pad_hor(commandInput, 14, 0);
  lv_textarea_set_one_line(commandInput, true);
  lv_textarea_set_max_length(commandInput, 200);
  lv_textarea_set_placeholder_text(commandInput, "Type a command");
  lv_obj_set_style_text_font(commandInput, &inter_24, 0);
  lv_obj_set_style_text_color(commandInput, INK, 0);
  lv_obj_set_style_text_color(commandInput, INK_MUTED, LV_PART_TEXTAREA_PLACEHOLDER);
  lv_obj_set_style_border_side(commandInput, LV_BORDER_SIDE_LEFT, LV_PART_CURSOR);
  lv_obj_set_style_border_width(commandInput, 0, LV_PART_CURSOR);  // 2 while typing: openKeyboard
  lv_obj_set_style_border_color(commandInput, ACCENT_BLUE, LV_PART_CURSOR);
  lv_obj_set_style_anim_duration(commandInput, 500, LV_PART_CURSOR);         // blink
  lv_obj_add_event_cb(commandInput, onTextBoxEvent, LV_EVENT_ALL, nullptr);

  lv_obj_t *send = makePillButton(composer, "Send", true);
  onClick(send, [](lv_event_t *) { submitCommand(); });

  formErrorLabel = makeText(dock, &inter_20, ERROR_RED, "");
  lv_obj_add_flag(formErrorLabel, LV_OBJ_FLAG_HIDDEN);
  makeText(dock, &inter_20, INK_MUTED, "Or say “hey jarvis”, then the command.");
}

void buildKeyboard(lv_obj_t *screen) {
  keyboard = lv_keyboard_create(screen);
  lv_obj_remove_style_all(keyboard);
  lv_obj_set_size(keyboard, W, 400);
  fill(keyboard, SURFACE_1);
  lv_obj_set_style_pad_all(keyboard, 12, 0);
  lv_obj_set_style_pad_row(keyboard, 10, 0);
  lv_obj_set_style_pad_column(keyboard, 10, 0);
  fill(keyboard, SURFACE_2, LV_PART_ITEMS);
  fill(keyboard, HAIRLINE, LV_PART_ITEMS | LV_STATE_PRESSED);
  fill(keyboard, SURFACE_2, LV_PART_ITEMS | LV_STATE_CHECKED);
  lv_obj_set_style_radius(keyboard, 15, LV_PART_ITEMS);
  lv_obj_set_style_text_font(keyboard, &inter_24, LV_PART_ITEMS);
  lv_obj_set_style_text_color(keyboard, INK, LV_PART_ITEMS);
  lv_keyboard_set_textarea(keyboard, commandInput);
  lv_obj_add_flag(keyboard, LV_OBJ_FLAG_HIDDEN);
}

// ---------- volume bar (the Tab5's own, along the bottom) ----------

void onVolumeEvent(lv_event_t *event) {
  lv_obj_t *slider = lv_event_get_target_obj(event);
  volume = lv_slider_get_value(slider);  // playKikiAudioTask applies it to the next chunk
  lv_label_set_text(volumePercentLabel, (String(volume * 100 / MAX_VOLUME) + "%").c_str());
  if (lv_event_get_code(event) == LV_EVENT_RELEASED) {
    prefs.putUChar("vol", volume);
    Serial.printf("[volume] saved %d of %d\n", volume, MAX_VOLUME);
  }
}

void buildVolumeBar(lv_obj_t *screen) {
  lv_obj_t *bar = makeBox(screen);
  lv_obj_set_size(bar, W, 88);
  fill(bar, SURFACE_1);
  lv_obj_set_style_pad_hor(bar, 30, 0);
  stackChildren(bar, LV_FLEX_FLOW_ROW, 26, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER);
  makeText(bar, &inter_20, INK_MUTED, "Volume");

  lv_obj_t *slider = lv_slider_create(bar);
  lv_obj_remove_style_all(slider);
  lv_obj_set_height(slider, 8);
  lv_obj_set_flex_grow(slider, 1);
  lv_obj_set_ext_click_area(slider, 36);  // the whole bar's height takes a finger
  fill(slider, HAIRLINE);
  fill(slider, ACCENT_BLUE, LV_PART_INDICATOR);
  fill(slider, INK, LV_PART_KNOB);
  lv_obj_set_style_radius(slider, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_radius(slider, LV_RADIUS_CIRCLE, LV_PART_INDICATOR);
  lv_obj_set_style_radius(slider, LV_RADIUS_CIRCLE, LV_PART_KNOB);
  lv_obj_set_style_pad_all(slider, 14, LV_PART_KNOB);
  lv_slider_set_range(slider, 0, MAX_VOLUME);
  lv_slider_set_value(slider, volume, LV_ANIM_OFF);
  lv_obj_add_event_cb(slider, onVolumeEvent, LV_EVENT_VALUE_CHANGED, nullptr);
  lv_obj_add_event_cb(slider, onVolumeEvent, LV_EVENT_RELEASED, nullptr);

  volumePercentLabel = makeText(bar, &inter_20, INK, String(volume * 100 / MAX_VOLUME) + "%");
  lv_obj_set_width(volumePercentLabel, 64);
  lv_obj_set_style_text_align(volumePercentLabel, LV_TEXT_ALIGN_RIGHT, 0);
}

// ---------- History sheet ----------

lv_obj_t *addRunLine(lv_obj_t *card, const char *tag) {
  lv_obj_t *line = makeBox(card);
  lv_obj_set_width(line, LV_PCT(100));
  stackChildren(line, LV_FLEX_FLOW_ROW, 14, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
  lv_obj_t *tagLabel = makeText(line, &inter_20, INK_MUTED, tag);
  lv_obj_set_width(tagLabel, 80);
  lv_obj_set_style_pad_top(tagLabel, 3, 0);  // sits on the 24 px line's baseline
  return line;
}

lv_obj_t *addWrappedText(lv_obj_t *parent, const lv_font_t *font, lv_color_t color, const String &text) {
  lv_obj_t *label = makeText(parent, font, color, text);
  lv_label_set_long_mode(label, LV_LABEL_LONG_MODE_WRAP);
  lv_obj_set_flex_grow(label, 1);
  return label;
}

lv_obj_t *addRunCard(lv_obj_t *list, const Run &run) {
  lv_obj_t *card = makeBox(list);
  lv_obj_set_width(card, LV_PCT(100));
  fill(card, SURFACE_2);
  lv_obj_set_style_radius(card, 22, 0);
  lv_obj_set_style_pad_all(card, 22, 0);
  stackChildren(card, LV_FLEX_FLOW_COLUMN, 10, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);

  lv_obj_t *meta = makeBox(card);
  lv_obj_set_width(meta, LV_PCT(100));
  stackChildren(meta, LV_FLEX_FLOW_ROW, 12, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_CENTER);
  makeText(meta, &inter_20, INK_MUTED, run.time + " · " + run.source);
  makeText(meta, &inter_20, INK_MUTED, run.latency);

  addWrappedText(addRunLine(card, "Heard"), &inter_24, INK, run.heard);
  lv_obj_t *chips = makeBox(addRunLine(card, "Did"));
  lv_obj_set_flex_grow(chips, 1);
  stackChildren(chips, LV_FLEX_FLOW_ROW_WRAP, 8, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
  for (const Chip &chip : run.chips) makeChip(chips, chip, SURFACE_1);
  addWrappedText(addRunLine(card, "Said"), &inter_24, INK, run.said);
  if (run.error.length()) lv_obj_set_width(addWrappedText(card, &inter_20, ERROR_RED, run.error), LV_PCT(100));
  lv_obj_set_width(addWrappedText(card, &inter_20, INK_MUTED, run.details), LV_PCT(100));
  return card;
}

// The sheet slides on a 16 ms timer of its own (an lv_anim on it never ran here), easing out like
// ui.html's sheet-in. Building 50 run cards at once froze the screen for seconds, so it opens with
// the first few and the same timer adds the rest a handful at a time.
lv_timer_t *sheetTimer = nullptr;
int32_t sheetFrom, sheetTo;
uint32_t sheetStartMs, sheetMs;
bool sheetClosing = false;
size_t historyCardsBuilt = 0;

void stepSheet(lv_timer_t *) {
  float p = min(1.0f, (millis() - sheetStartMs) / (float)sheetMs), eased = 1 - (1 - p) * (1 - p) * (1 - p);
  lv_obj_set_x(historySheet, sheetFrom + (int32_t)((sheetTo - sheetFrom) * eased));
  for (int n = 0; n < 4 && !sheetClosing && historyCardsBuilt < runs.size(); n++)
    addRunCard(historyRunsList, runs[historyCardsBuilt++]);
  if (p < 1 || (!sheetClosing && historyCardsBuilt < runs.size())) return;
  lv_timer_delete(sheetTimer);
  sheetTimer = nullptr;
  if (sheetClosing) {
    lv_obj_delete(historySheet);
    historySheet = historyRunsList = nullptr;
    sheetClosing = false;
    setOrbVisible(true);
  }
}

void slideSheet(int32_t from, int32_t to, uint32_t ms) {
  sheetFrom = from;
  sheetTo = to;
  sheetStartMs = millis();
  sheetMs = ms;
  if (!sheetTimer) sheetTimer = lv_timer_create(stepSheet, 16, nullptr);
}

void closeHistory() {
  if (!historySheet || sheetClosing) return;
  lv_obj_delete(historyBackdrop);
  historyBackdrop = nullptr;
  sheetClosing = true;
  slideSheet(lv_obj_get_x(historySheet), W, 260);
}

// All runs, newest first, in a sheet that slides in from the right; tap outside or × to close.
// The orb stops drawing underneath it.
void openHistory() {
  if (historySheet) return;
  closeKeyboard();
  setOrbVisible(false);
  historyBackdrop = makeBox(lv_layer_top());
  lv_obj_set_size(historyBackdrop, W, H);
  lv_obj_set_style_bg_color(historyBackdrop, CANVAS, 0);
  lv_obj_set_style_bg_opa(historyBackdrop, LV_OPA_70, 0);
  lv_obj_add_flag(historyBackdrop, LV_OBJ_FLAG_CLICKABLE);
  onClick(historyBackdrop, [](lv_event_t *) { closeHistory(); });

  historySheet = makeBox(lv_layer_top());
  lv_obj_set_size(historySheet, SHEET_W + 40, H);  // 40 px past the edge hides its right corners
  lv_obj_set_pos(historySheet, W, 0);
  lv_obj_add_flag(historySheet, LV_OBJ_FLAG_CLICKABLE);  // taps on it don't reach the backdrop
  fill(historySheet, SURFACE_1);
  lv_obj_set_style_radius(historySheet, 30, 0);
  lv_obj_set_style_pad_right(historySheet, 40, 0);
  stackChildren(historySheet, LV_FLEX_FLOW_COLUMN, 0, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);

  lv_obj_t *head = makeBox(historySheet);
  lv_obj_set_size(head, LV_PCT(100), 112);
  lv_obj_set_style_pad_hor(head, 30, 0);
  stackChildren(head, LV_FLEX_FLOW_ROW, 0, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_CENTER);
  makeText(head, &inter_32_bold, INK, "Runs");
  lv_obj_t *close = makeBox(head);
  lv_obj_set_size(close, 64, 64);
  lv_obj_add_flag(close, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_set_style_radius(close, LV_RADIUS_CIRCLE, 0);
  fill(close, SURFACE_2);
  fill(close, HAIRLINE, LV_STATE_PRESSED);
  lv_obj_center(makeText(close, &inter_32_bold, INK, "×"));
  onClick(close, [](lv_event_t *) { closeHistory(); });

  historyRunsList = makeBox(historySheet);
  lv_obj_set_width(historyRunsList, LV_PCT(100));
  lv_obj_set_flex_grow(historyRunsList, 1);
  lv_obj_add_flag(historyRunsList, LV_OBJ_FLAG_SCROLLABLE);
  lv_obj_set_scroll_dir(historyRunsList, LV_DIR_VER);
  lv_obj_set_scrollbar_mode(historyRunsList, LV_SCROLLBAR_MODE_OFF);
  lv_obj_set_style_pad_hor(historyRunsList, 30, 0);
  lv_obj_set_style_pad_bottom(historyRunsList, 30, 0);
  stackChildren(historyRunsList, LV_FLEX_FLOW_COLUMN, 18, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
  if (runs.empty()) makeText(historyRunsList, &inter_24, INK_MUTED, "No runs yet.");
  for (historyCardsBuilt = 0; historyCardsBuilt < runs.size() && historyCardsBuilt < 6; historyCardsBuilt++)
    addRunCard(historyRunsList, runs[historyCardsBuilt]);

  slideSheet(W, W - SHEET_W, 400);
}

void showRuns() {
  lv_label_set_text(historyCountLabel, runs.empty() ? "" : String(runs.size()).c_str());
  showLastRun();
}

// A run that arrives while History is open goes on top, as in the web UI.
void addNewestRunToHistory() {
  if (!historyRunsList || runs.empty()) return;
  if (runs.size() == 1) lv_obj_clean(historyRunsList);  // drops "No runs yet."
  lv_obj_move_to_index(addRunCard(historyRunsList, runs.front()), 0);
  historyCardsBuilt++;  // the cards still to build moved one place down in runs
}

// ---------- the top bar ----------

void showConnection(Link state) {
  lv_color_t color = state == Link::Live ? SUCCESS : state == Link::Reconnecting ? ERROR_RED : INK_MUTED;
  fill(connectionDot, color);
  lv_label_set_text(connectionLabel, state == Link::Live ? "live" : state == Link::Reconnecting ? "reconnecting…" : "connecting…");
  lv_obj_set_style_text_color(connectionLabel, state == Link::Reconnecting ? ERROR_RED : INK_MUTED, 0);
}

void buildTopBar(lv_obj_t *screen) {
  lv_obj_t *bar = makeBox(screen);
  lv_obj_set_size(bar, W, 88);
  lv_obj_set_style_pad_hor(bar, 30, 0);
  stackChildren(bar, LV_FLEX_FLOW_ROW, 0, LV_FLEX_ALIGN_SPACE_BETWEEN, LV_FLEX_ALIGN_CENTER);
  makeText(bar, &inter_32_bold, INK, "Kiki");

  lv_obj_t *actions = makeBox(bar);
  stackChildren(actions, LV_FLEX_FLOW_ROW, 20, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER);
  lv_obj_t *connection = makeBox(actions);
  stackChildren(connection, LV_FLEX_FLOW_ROW, 10, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER);
  connectionDot = makeBox(connection);
  lv_obj_set_size(connectionDot, 11, 11);
  lv_obj_set_style_radius(connectionDot, LV_RADIUS_CIRCLE, 0);
  connectionLabel = makeText(connection, &inter_20, INK_MUTED, "");

  lv_obj_t *history = makePillButton(actions, "History", false);
  historyCountLabel = makeText(history, &inter_20, INK_MUTED, "");
  onClick(history, [](lv_event_t *) { openHistory(); });
}

// ---------- start ----------

void startScreen() {
  lv_init();
  lv_tick_set_cb(millisForLvgl);
  lv_display_t *display = lv_display_create(W, H);
  static constexpr size_t BUFFER_BYTES = W * 160 * 2;  // 160 lines a pass
  startPixelCopier();
  lv_display_set_buffers(display, heap_caps_aligned_alloc(64, BUFFER_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_DMA), nullptr, BUFFER_BYTES,
                         LV_DISPLAY_RENDER_MODE_PARTIAL);
  lv_display_set_flush_cb(display, flushToPanel);
  lv_indev_t *touch = lv_indev_create();
  lv_indev_set_type(touch, LV_INDEV_TYPE_POINTER);
  lv_indev_set_read_cb(touch, readTouch);

  lv_obj_t *screen = lv_screen_active();
  fill(screen, CANVAS);
  lv_obj_set_style_text_color(screen, INK, 0);
  lv_obj_set_style_text_font(screen, &inter_24, 0);
  lv_obj_remove_flag(screen, LV_OBJ_FLAG_SCROLLABLE);
  stackChildren(screen, LV_FLEX_FLOW_COLUMN, 0, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER);

  buildTopBar(screen);
  orbArea = makeBox(screen);  // the orb, with Kiki's reply over its lower halo as on the web
  lv_obj_set_size(orbArea, W, ORB_H);
  startOrb(orbArea);
  captionLabel = makeText(orbArea, &inter_24, INK, "");
  lv_obj_set_width(captionLabel, COLUMN_W - 40);
  lv_label_set_long_mode(captionLabel, LV_LABEL_LONG_MODE_WRAP);
  lv_obj_set_style_text_align(captionLabel, LV_TEXT_ALIGN_CENTER, 0);
  lv_obj_align(captionLabel, LV_ALIGN_BOTTOM_MID, 0, -4);
  stateLabel = makeText(screen, &inter_48, INK, "");

  lastRunRow = makeBox(screen);
  lv_obj_set_width(lastRunRow, COLUMN_W);
  lv_obj_set_style_min_height(lastRunRow, 64, 0);
  lv_obj_set_style_margin_top(lastRunRow, 8, 0);
  lv_obj_set_style_pad_all(lastRunRow, 10, 0);
  lv_obj_set_style_radius(lastRunRow, 15, 0);
  fill(lastRunRow, SURFACE_1, LV_STATE_PRESSED);
  stackChildren(lastRunRow, LV_FLEX_FLOW_ROW_WRAP, 8, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
  onClick(lastRunRow, [](lv_event_t *) { openHistory(); });

  buildList(screen);
  buildDock(screen);
  buildKeyboard(screen);
  buildVolumeBar(screen);

  showConnection(Link::Connecting);
  showKikiState("idle", false);
  showList();
  showRuns();
}
