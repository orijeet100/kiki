// The item sheet (v0.16, FR-0.33): tap a List row and a sheet rises from the bottom with that
// item: this order's quantity (– and +) and Needed or Not needed, Frequent or Occasional, its
// Product with Forget (v0.17, FR-0.34), Rename and Remove (Not needed, ADR 0026). Every change is on the screen at once and goes to Kiki after
// (events.ino); one Kiki refuses undoes itself, with the reason in the sheet.
//
// The look, in DESIGN.md's tokens: each group sits in a tray (canvas, hairline edge) holding a
// raised plate (surface 2, a hairline highlight along its top), with concentric radii; small
// spaced-out eyebrows over each group; white pill for the primary action, with its check in its
// own circle. Renaming swaps the groups for a large name field in the same tray and plate, and
// the sheet rises to make room for the keyboard.
//
// Smooth first: it's built once at start-up and only slides; no dimmed backdrop (a full-screen
// redraw takes ~78 ms here), so only the sheet's own rectangle is drawn; the orb pauses while it
// moves; the stepper's taps are sent once it has been still for QUANTITY_SETTLE_MS, so five quick
// taps are one request; tapping another row while it's open switches the sheet to that item.

static constexpr uint32_t QUANTITY_SETTLE_MS = 350;
static constexpr uint32_t ITEM_SHEET_MS = 220;
static constexpr int STEP_BUTTON = 84, MAX_QUANTITY = 99;
static constexpr int SHEET_HIDDEN_CORNERS = 40;  // the sheet runs this far past the bottom edge
static constexpr int TRAY_RADIUS = 36, TRAY_PAD = 6;

Item editing;  // what the sheet shows; its name is how Kiki knows the item
lv_obj_t *itemSheet = nullptr;  // built once at start-up, parked just below the screen when closed
bool itemSheetShown = false, renaming = false;
lv_obj_t *sheetEyebrow, *sheetTitle, *sheetError, *sheetBody, *sheetNeeded, *sheetNotNeeded;
lv_obj_t *sheetFrequent, *sheetOccasional, *sheetPatternHint, *sheetProduct, *sheetForget;
lv_obj_t *sheetQuantity, *sheetMinus, *sheetPlus, *sheetRemove, *sheetDone, *sheetRename, *sheetClose;
lv_obj_t *renameBox = nullptr, *renameInput = nullptr, *renameKeys = nullptr;
lv_timer_t *quantityTimer = nullptr, *itemSheetTimer = nullptr;
int32_t itemSheetFrom, itemSheetTo;
uint32_t itemSheetStartMs, itemSheetFrames;
bool itemSheetClosing = false;

bool itemSheetOpen() { return itemSheetShown; }

// The orb pauses while the sheet moves, and whenever the sheet reaches over it (renaming, or an
// item sheet tall enough since v0.17's Product line): the orb is drawn straight to the panel, over
// anything LVGL put there.
bool itemSheetSliding() {
  if (itemSheetTimer != nullptr || renaming) return true;
  if (!itemSheetShown) return false;
  lv_area_t orb;
  lv_obj_get_coords(orbArea, &orb);
  return lv_obj_get_y(itemSheet) <= orb.y2;
}

String capitalized(String name) {
  if (name.length()) name.setCharAt(0, toupper(name[0]));
  return name;
}

// ---------- building blocks ----------

// A small, spaced-out label over a group.
lv_obj_t *makeEyebrow(lv_obj_t *parent, const char *text) {
  lv_obj_t *label = makeText(parent, &inter_20, INK_MUTED, text);
  lv_obj_set_style_text_letter_space(label, 3, 0);
  return label;
}

// The tray and its plate: a canvas tray with a hairline edge holding a raised surface-2 plate
// with a hairline highlight along its top. Returns the plate, where the content goes.
lv_obj_t *makeTray(lv_obj_t *parent) {
  lv_obj_t *tray = makeBox(parent);
  lv_obj_set_width(tray, LV_PCT(100));
  fill(tray, CANVAS);
  lv_obj_set_style_radius(tray, TRAY_RADIUS, 0);
  lv_obj_set_style_border_width(tray, 1, 0);
  lv_obj_set_style_border_color(tray, HAIRLINE, 0);
  lv_obj_set_style_pad_all(tray, TRAY_PAD, 0);
  lv_obj_t *plate = makeBox(tray);
  lv_obj_set_width(plate, LV_PCT(100));
  fill(plate, SURFACE_2);
  lv_obj_set_style_radius(plate, TRAY_RADIUS - TRAY_PAD, 0);
  lv_obj_set_style_border_side(plate, LV_BORDER_SIDE_TOP, 0);
  lv_obj_set_style_border_width(plate, 1, 0);
  lv_obj_set_style_border_color(plate, HAIRLINE, 0);
  lv_obj_set_style_pad_all(plate, 22, 0);
  stackChildren(plate, LV_FLEX_FLOW_COLUMN, 18, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
  return plate;
}

// Two choices in a canvas track, the chosen one a white pill (Framer's pricing tabs).
void makeChoices(lv_obj_t *parent, const char *first, const char *second, lv_obj_t **firstChoice, lv_obj_t **secondChoice) {
  lv_obj_t *track = makeBox(parent);
  lv_obj_set_size(track, LV_PCT(100), 72);
  fill(track, CANVAS);
  lv_obj_set_style_radius(track, LV_RADIUS_CIRCLE, 0);
  lv_obj_set_style_pad_all(track, 5, 0);
  stackChildren(track, LV_FLEX_FLOW_ROW, 5, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER);
  for (lv_obj_t **choice : {firstChoice, secondChoice}) {
    *choice = makeBox(track);
    lv_obj_add_flag(*choice, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_height(*choice, LV_PCT(100));
    lv_obj_set_flex_grow(*choice, 1);
    lv_obj_set_style_radius(*choice, LV_RADIUS_CIRCLE, 0);
    lv_obj_center(makeText(*choice, &inter_24, INK, choice == firstChoice ? first : second));
  }
}

lv_obj_t *makeRoundButton(lv_obj_t *parent, const char *text, int size, const lv_font_t *font) {
  lv_obj_t *button = makeBox(parent);
  lv_obj_set_size(button, size, size);
  lv_obj_add_flag(button, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_set_style_radius(button, LV_RADIUS_CIRCLE, 0);
  fill(button, CANVAS);
  fill(button, HAIRLINE, LV_STATE_PRESSED);
  lv_obj_set_style_border_width(button, 1, 0);
  lv_obj_set_style_border_color(button, HAIRLINE, 0);
  lv_obj_center(makeText(button, font, INK, text));
  return button;
}

// A thin check mark, drawn: the fonts carry no ✓.
void drawCheck(lv_obj_t *parent, lv_color_t ink) {
  static lv_point_precise_t points[] = {{0, 9}, {7, 16}, {20, 2}};
  lv_obj_t *check = lv_line_create(parent);
  lv_line_set_points(check, points, 3);
  lv_obj_set_style_line_width(check, 3, 0);
  lv_obj_set_style_line_color(check, ink, 0);
  lv_obj_set_style_line_rounded(check, true, 0);
  lv_obj_set_size(check, 21, 18);
  lv_obj_center(check);
}

// A pill as tall as a thumb: white for the primary action, its check in a black circle tucked
// against the right edge; charcoal for the rest.
lv_obj_t *makeActionPill(lv_obj_t *parent, const char *text, bool primary, lv_color_t ink) {
  lv_obj_t *pill = makeBox(parent);
  lv_obj_add_flag(pill, LV_OBJ_FLAG_CLICKABLE);
  lv_obj_set_height(pill, 84);
  lv_obj_set_flex_grow(pill, 1);
  lv_obj_set_style_radius(pill, LV_RADIUS_CIRCLE, 0);
  fill(pill, primary ? INK : SURFACE_2);
  fill(pill, primary ? lv_color_hex(0xd8d8d8) : HAIRLINE, LV_STATE_PRESSED);
  lv_obj_set_style_pad_left(pill, 34, 0);
  lv_obj_set_style_pad_right(pill, primary ? 10 : 34, 0);
  stackChildren(pill, LV_FLEX_FLOW_ROW, 0, primary ? LV_FLEX_ALIGN_SPACE_BETWEEN : LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
  makeText(pill, &inter_24, ink, text);
  if (primary) {
    lv_obj_t *circle = makeBox(pill);
    lv_obj_set_size(circle, 64, 64);
    lv_obj_set_style_radius(circle, LV_RADIUS_CIRCLE, 0);
    fill(circle, ON_PRIMARY);
    drawCheck(circle, INK);
  }
  return pill;
}

// ---------- showing ----------

void styleChoice(lv_obj_t *choice, bool selected) {
  fill(choice, INK);
  lv_obj_set_style_bg_opa(choice, selected ? LV_OPA_COVER : LV_OPA_TRANSP, 0);
  lv_obj_set_style_text_color(lv_obj_get_child(choice, 0), selected ? ON_PRIMARY : INK_MUTED, 0);
}

void enable(lv_obj_t *control, bool enabled) {
  lv_obj_set_style_opa(control, enabled ? LV_OPA_COVER : LV_OPA_40, 0);
  if (enabled) lv_obj_remove_state(control, LV_STATE_DISABLED);
  else lv_obj_add_state(control, LV_STATE_DISABLED);
}

void showSheet() {
  lv_label_set_text(sheetEyebrow, editing.frequent ? "FREQUENT" : "OCCASIONAL");
  lv_label_set_text(sheetTitle, capitalized(editing.name).c_str());
  styleChoice(sheetNeeded, editing.needed);
  styleChoice(sheetNotNeeded, !editing.needed);
  styleChoice(sheetFrequent, editing.frequent);
  styleChoice(sheetOccasional, !editing.frequent);
  lv_label_set_text(sheetPatternHint, editing.frequent ? "Stays on the list, dimmed, when it's not needed."
                                                       : "Leaves the list when it's not needed.");
  lv_label_set_text(sheetQuantity, String(editing.quantity).c_str());
  lv_obj_set_style_text_color(sheetQuantity, editing.needed ? INK : INK_MUTED, 0);
  enable(sheetMinus, editing.needed && editing.quantity > 1);
  enable(sheetPlus, editing.quantity < MAX_QUANTITY || !editing.needed);
  enable(sheetRemove, editing.needed);
  lv_label_set_text(sheetProduct, editing.product.length() ? editing.product.c_str() : "No product yet");
  lv_obj_set_style_text_color(sheetProduct, editing.product.length() ? INK : INK_MUTED, 0);
  enable(sheetForget, editing.product.length() > 0);
}

void showSheetError(const String &text) {
  lv_label_set_text(sheetError, text.c_str());
  if (text.isEmpty()) lv_obj_add_flag(sheetError, LV_OBJ_FLAG_HIDDEN);
  else lv_obj_remove_flag(sheetError, LV_OBJ_FLAG_HIDDEN);
}

// Kiki's List changed (a spoken command, or an edit coming back): the sheet follows its item.
void refreshItemSheet() {
  if (!itemSheetShown) return;
  for (const Item &item : items)
    if (item.name == editing.name) {
      editing.needed = item.needed;
      editing.quantity = item.quantity;
      editing.frequent = item.frequent;
      editing.product = item.product;
    }
  showSheet();
}

// An edit, on the screen: the List's row (in place, showList) and the sheet.
void showEdit() {
  for (Item &item : items)
    if (item.name == editing.name) {
      item.needed = editing.needed;
      item.quantity = editing.quantity;
      item.frequent = editing.frequent;
      item.product = editing.product;
    }
  showList();
  showSheet();
  showSheetError("");
}

// Called by finishPost (events.ino) when Kiki refuses an edit; Kiki's List puts the rest back.
void sheetEditFailed(const String &name, const String &newName, const String &reason) {
  if (!itemSheetShown) return;
  if (newName.length() && editing.name == newName) editing.name = name;  // the rename didn't happen
  showSheetError(reason);
}

// ---------- editing ----------

void sendSettledQuantity(lv_timer_t *);

void flushQuantity() {
  if (!quantityUnsent) return;
  if (quantityTimer) lv_timer_delete(quantityTimer);
  quantityTimer = nullptr;
  sendQuantity(editing.name, editing.quantity);
  quantityUnsent = false;
}

void sendSettledQuantity(lv_timer_t *) {
  quantityTimer = nullptr;  // a one-shot timer deletes itself
  flushQuantity();
}

void chooseNeeded(bool needed) {
  if (editing.needed == needed) return;
  measureFromTap(needed ? "Needed" : "Not needed");
  flushQuantity();
  editing.needed = needed;
  showEdit();
  sendNeeded(editing.name, needed);
}

void choosePattern(bool frequent) {
  if (editing.frequent == frequent) return;
  measureFromTap(frequent ? "Frequent" : "Occasional");
  flushQuantity();
  editing.frequent = frequent;
  showEdit();
  sendPattern(editing.name, frequent);
}

// – and + change this order's quantity; + on a Not needed item makes it Needed, as saying a
// number does (FR-0.22).
void step(int by) {
  int quantity = constrain(editing.quantity + by, 1, MAX_QUANTITY);
  if (quantity == editing.quantity && editing.needed) return;
  measureFromTap("new quantity");
  editing.quantity = quantity;
  editing.needed = true;
  showEdit();
  quantityUnsent = true;
  if (quantityTimer) {
    lv_timer_reset(quantityTimer);
  } else {
    quantityTimer = lv_timer_create(sendSettledQuantity, QUANTITY_SETTLE_MS, nullptr);
    lv_timer_set_repeat_count(quantityTimer, 1);
  }
}

// Forget (FR-0.34): the next Cart finds a Product for it again ("use Diamond walnuts for walnuts"
// sets one by voice).
void forgetProduct() {
  if (editing.product.isEmpty()) return;
  measureFromTap("forgot product");
  flushQuantity();
  editing.product = "";
  showEdit();
  sendForget(editing.name);
}

void removeItem() {
  flushQuantity();
  if (editing.needed) {
    measureFromTap("removed item");
    editing.needed = false;
    showEdit();
    sendNeeded(editing.name, false);
  }
  closeItemSheet();
}

// ---------- renaming: the groups give way to a name field and a keyboard ----------
// The keyboard's white key saves; its hide key, or ×, goes back to the sheet with the old name.

void placeItemSheet();

void endRename(bool keep) {
  if (!renaming) return;
  renaming = false;
  String newName = lv_textarea_get_text(renameInput);
  newName.trim();
  lv_obj_add_flag(renameBox, LV_OBJ_FLAG_HIDDEN);
  lv_obj_remove_flag(sheetBody, LV_OBJ_FLAG_HIDDEN);
  lv_obj_remove_flag(sheetRename, LV_OBJ_FLAG_HIDDEN);
  showSheet();
  placeItemSheet();
  if (!keep || newName.isEmpty() || newName == editing.name) return;
  measureFromTap("new name");
  String oldName = editing.name;
  for (Item &item : items)
    if (item.name == oldName) item.name = newName;
  editing.name = newName;
  showList();
  showSheet();
  showSheetError("");
  sendRename(oldName, newName);
}

void onRenameEvent(lv_event_t *event) {
  lv_event_code_t code = lv_event_get_code(event);
  if (code == LV_EVENT_READY) endRename(true);  // the keyboard's Save key
  else if (code == LV_EVENT_CANCEL) endRename(false);
}

void startRename() {
  if (renaming) return;
  renaming = true;
  flushQuantity();
  lv_obj_add_flag(sheetBody, LV_OBJ_FLAG_HIDDEN);
  lv_obj_add_flag(sheetRename, LV_OBJ_FLAG_HIDDEN);
  lv_label_set_text(sheetEyebrow, "RENAME");
  lv_textarea_set_text(renameInput, editing.name.c_str());
  lv_obj_remove_flag(renameBox, LV_OBJ_FLAG_HIDDEN);
  placeItemSheet();
}

// Built once with the sheet, hidden until Rename: creating the keyboard on the tap took 119 ms.
void buildRename() {
  renameBox = makeBox(itemSheet);
  lv_obj_add_flag(renameBox, LV_OBJ_FLAG_HIDDEN);
  lv_obj_set_width(renameBox, LV_PCT(100));
  stackChildren(renameBox, LV_FLEX_FLOW_COLUMN, 18, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);

  lv_obj_t *plate = makeTray(renameBox);
  lv_obj_set_style_border_color(lv_obj_get_parent(plate), ACCENT_BLUE, 0);  // focus: the one signal of blue
  lv_obj_set_style_pad_ver(plate, 26, 0);
  renameInput = lv_textarea_create(plate);
  lv_obj_remove_style_all(renameInput);
  lv_obj_set_width(renameInput, LV_PCT(100));
  lv_textarea_set_one_line(renameInput, true);
  lv_textarea_set_max_length(renameInput, 60);
  lv_obj_set_style_text_font(renameInput, &inter_32_bold, 0);
  lv_obj_set_style_text_color(renameInput, INK, 0);
  lv_obj_set_style_border_side(renameInput, LV_BORDER_SIDE_LEFT, LV_PART_CURSOR);
  lv_obj_set_style_border_width(renameInput, 3, LV_PART_CURSOR);
  lv_obj_set_style_border_color(renameInput, ACCENT_BLUE, LV_PART_CURSOR);
  lv_obj_set_style_anim_duration(renameInput, 500, LV_PART_CURSOR);
  lv_obj_add_state(renameInput, LV_STATE_FOCUSED);
  lv_obj_add_event_cb(renameInput, onRenameEvent, LV_EVENT_ALL, nullptr);

  lv_obj_t *hint = makeText(renameBox, &inter_20, INK_MUTED, "Kiki will call it this from now on, by voice too.");
  lv_obj_set_style_pad_left(hint, 12, 0);

  renameKeys = makeKeyboard(renameBox, W - 72, "Save");
  typeInto(renameKeys, renameInput);
}

// ---------- the sheet ----------

void onSheetTap(lv_event_t *event) {
  lv_obj_t *control = lv_event_get_current_target_obj(event);
  if (control == sheetNeeded) chooseNeeded(true);
  else if (control == sheetNotNeeded) chooseNeeded(false);
  else if (control == sheetFrequent) choosePattern(true);
  else if (control == sheetOccasional) choosePattern(false);
  else if (control == sheetMinus) step(-1);
  else if (control == sheetPlus) step(1);
  else if (control == sheetRemove) removeItem();
  else if (control == sheetForget) forgetProduct();
  else if (control == sheetRename) startRename();
  else if (control == sheetClose && renaming) endRename(false);  // × while renaming: back to the sheet
  else if (control == sheetDone || control == sheetClose) closeItemSheet();
}

void stepItemSheet(lv_timer_t *) {
  float p = min(1.0f, (millis() - itemSheetStartMs) / (float)ITEM_SHEET_MS), eased = 1 - (1 - p) * (1 - p) * (1 - p);
  lv_obj_set_y(itemSheet, itemSheetFrom + (int32_t)((itemSheetTo - itemSheetFrom) * eased));
  itemSheetFrames++;
  if (p < 1) return;
  Serial.printf("[measure] sheet slide: %lu frames in %lu ms, %lu ms of it copying %lu kpx to the panel\n", itemSheetFrames,
                millis() - itemSheetStartMs, flushMicros / 1000, flushedPixels / 1000);
  lv_timer_delete(itemSheetTimer);
  itemSheetTimer = nullptr;
  if (itemSheetClosing) itemSheetShown = itemSheetClosing = false;  // parked until the next row is tapped
  setOrbVisible(!itemSheetSliding());
}

void slideItemSheet(int32_t to) {
  itemSheetFrom = lv_obj_get_y(itemSheet);
  itemSheetTo = to;
  itemSheetStartMs = millis();
  itemSheetFrames = flushMicros = flushedPixels = 0;
  setOrbVisible(false);
  if (!itemSheetTimer) itemSheetTimer = lv_timer_create(stepItemSheet, 16, nullptr);
}

// Slides so its bottom edge sits on the screen's: renaming makes it taller, and back.
void placeItemSheet() {
  lv_obj_update_layout(itemSheet);
  slideItemSheet(H - lv_obj_get_height(itemSheet) + SHEET_HIDDEN_CORNERS);
}

void buildItemSheet() {
  itemSheet = makeBox(lv_layer_top());
  lv_obj_set_width(itemSheet, W);
  lv_obj_set_pos(itemSheet, 0, H);
  lv_obj_add_flag(itemSheet, LV_OBJ_FLAG_CLICKABLE);  // taps on it stay on it
  fill(itemSheet, SURFACE_1);
  lv_obj_set_style_radius(itemSheet, 44, 0);
  lv_obj_set_style_border_side(itemSheet, LV_BORDER_SIDE_TOP, 0);
  lv_obj_set_style_border_width(itemSheet, 1, 0);
  lv_obj_set_style_border_color(itemSheet, HAIRLINE, 0);
  lv_obj_set_style_pad_hor(itemSheet, 36, 0);
  lv_obj_set_style_pad_top(itemSheet, 14, 0);
  lv_obj_set_style_pad_bottom(itemSheet, 30 + SHEET_HIDDEN_CORNERS, 0);
  stackChildren(itemSheet, LV_FLEX_FLOW_COLUMN, 22, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER);

  lv_obj_t *grabber = makeBox(itemSheet);  // says "this is a sheet"
  lv_obj_set_size(grabber, 56, 6);
  lv_obj_set_style_radius(grabber, LV_RADIUS_CIRCLE, 0);
  fill(grabber, HAIRLINE);

  lv_obj_t *head = makeBox(itemSheet);
  lv_obj_set_width(head, LV_PCT(100));
  stackChildren(head, LV_FLEX_FLOW_ROW, 14, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER);
  lv_obj_t *names = makeBox(head);
  lv_obj_set_flex_grow(names, 1);
  stackChildren(names, LV_FLEX_FLOW_COLUMN, 6, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);
  sheetEyebrow = makeEyebrow(names, "");
  sheetTitle = makeText(names, &inter_48, INK, "");
  lv_obj_set_width(sheetTitle, LV_PCT(100));
  lv_label_set_long_mode(sheetTitle, LV_LABEL_LONG_MODE_DOTS);
  sheetRename = makePillButton(head, "Rename", false);
  fill(sheetRename, SURFACE_2);
  fill(sheetRename, HAIRLINE, LV_STATE_PRESSED);
  sheetClose = makeRoundButton(head, "×", 64, &inter_32_bold);
  fill(sheetClose, SURFACE_2);

  sheetError = makeText(itemSheet, &inter_20, ERROR_RED, "");
  lv_obj_set_width(sheetError, LV_PCT(100));
  lv_obj_add_flag(sheetError, LV_OBJ_FLAG_HIDDEN);

  sheetBody = makeBox(itemSheet);
  lv_obj_set_width(sheetBody, LV_PCT(100));
  stackChildren(sheetBody, LV_FLEX_FLOW_COLUMN, 18, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_START);

  lv_obj_t *order = makeTray(sheetBody);  // this order: how many, and whether at all
  lv_obj_t *quantityRow = makeBox(order);
  lv_obj_set_width(quantityRow, LV_PCT(100));
  stackChildren(quantityRow, LV_FLEX_FLOW_ROW, 8, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER);
  lv_obj_t *orderLabel = makeEyebrow(quantityRow, "THIS ORDER");
  lv_obj_set_flex_grow(orderLabel, 1);
  sheetMinus = makeRoundButton(quantityRow, "–", STEP_BUTTON, &inter_48);
  sheetQuantity = makeText(quantityRow, &inter_48, INK, "");
  lv_obj_set_width(sheetQuantity, 104);
  lv_obj_set_style_text_align(sheetQuantity, LV_TEXT_ALIGN_CENTER, 0);
  sheetPlus = makeRoundButton(quantityRow, "+", STEP_BUTTON, &inter_48);
  makeChoices(order, "Needed", "Not needed", &sheetNeeded, &sheetNotNeeded);

  lv_obj_t *pattern = makeTray(sheetBody);  // whether it stays on the list
  makeEyebrow(pattern, "ON THE LIST");
  makeChoices(pattern, "Frequent", "Occasional", &sheetFrequent, &sheetOccasional);
  sheetPatternHint = makeText(pattern, &inter_20, INK_MUTED, "");
  lv_obj_set_style_pad_left(sheetPatternHint, 8, 0);

  lv_obj_t *product = makeTray(sheetBody);  // what the Cart gets for it (v0.17)
  makeEyebrow(product, "PRODUCT");
  lv_obj_t *productRow = makeBox(product);
  lv_obj_set_width(productRow, LV_PCT(100));
  stackChildren(productRow, LV_FLEX_FLOW_ROW, 14, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER);
  sheetProduct = makeText(productRow, &inter_24, INK, "");
  lv_obj_set_flex_grow(sheetProduct, 1);
  lv_label_set_long_mode(sheetProduct, LV_LABEL_LONG_MODE_DOTS);
  sheetForget = makePillButton(productRow, "Forget", false);
  fill(sheetForget, CANVAS);
  fill(sheetForget, HAIRLINE, LV_STATE_PRESSED);

  lv_obj_t *actions = makeBox(sheetBody);
  lv_obj_set_width(actions, LV_PCT(100));
  lv_obj_set_style_pad_top(actions, 6, 0);
  stackChildren(actions, LV_FLEX_FLOW_ROW, 14, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER);
  sheetRemove = makeActionPill(actions, "Remove", false, ERROR_RED);
  sheetDone = makeActionPill(actions, "Done", true, ON_PRIMARY);

  for (lv_obj_t *control : {sheetNeeded, sheetNotNeeded, sheetFrequent, sheetOccasional, sheetMinus, sheetPlus, sheetRemove,
                            sheetRename, sheetDone, sheetClose, sheetForget})
    onClick(control, onSheetTap);
  buildRename();
}

// Opens the sheet on `item`, or switches the open sheet to it.
void openItemSheet(const Item &item) {
  if (itemSheetClosing) return;  // let it finish leaving
  measureFromTap("item sheet");
  closeKeyboard();
  if (itemSheetShown) {
    flushQuantity();
    endRename(false);
  }
  itemSheetShown = true;
  editing = item;
  showSheet();
  showSheetError("");
  placeItemSheet();
}

void closeItemSheet() {
  if (!itemSheetShown || itemSheetClosing) return;
  flushQuantity();
  endRename(false);
  itemSheetClosing = true;
  slideItemSheet(H);
}

// The keyboard on screen, for the "key" test command: renaming's, or the text box's.
lv_obj_t *keyboardShown() {
  if (renaming) return renameKeys;
  return lv_obj_has_flag(keyboard, LV_OBJ_FLAG_HIDDEN) ? nullptr : keyboard;
}

// "tapsheet <control>" over serial: a finger on one of the sheet's controls.
void tapSheetControl(const String &name) {
  lv_obj_t *control = name == "needed" ? sheetNeeded : name == "notneeded" ? sheetNotNeeded : name == "frequent" ? sheetFrequent
                    : name == "occasional" ? sheetOccasional : name == "minus" ? sheetMinus : name == "plus" ? sheetPlus
                    : name == "remove" ? sheetRemove : name == "rename" ? sheetRename : name == "done" ? sheetDone
                    : name == "close" ? sheetClose : name == "forget" ? sheetForget : nullptr;
  if (!itemSheetShown || !control) return;
  lv_area_t area;
  lv_obj_get_coords(control, &area);
  Serial.printf("[test] tap sheet %s\n", name.c_str());
  pressScreenFor((area.x1 + area.x2) / 2, (area.y1 + area.y2) / 2, 120);
}
