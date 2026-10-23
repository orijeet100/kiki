// Kiki's side of the conversation: the live events that drive the screen, and the two requests
// the screen sends back. Same endpoints and same meaning as the web UI (ui.html).
//
// Every wait on the network happens in networkTask, never in loop(): a POST inside a tap handler
// froze the whole screen for ~100 ms a tap. The task hands event lines and POST results to the
// loop through queues, and the loop alone touches LVGL and the screen's state.

QueueHandle_t eventLines, posts, postResults;  // of String *, Post and PostResult
volatile Link networkLink = Link::Connecting;    // written by networkTask, shown by the loop

WiFiClient eventStream;
uint32_t nextEventStreamAttempt = 0;

String kikiUrl(const char *path) { return String("http://") + KIKI_HOST + ":" + KIKI_PORT + path; }

void keepEventStreamOpen() {
  if (eventStream.connected()) return;
  if (networkLink == Link::Live) {
    Serial.println("[events] stream closed, retrying");
    networkLink = Link::Reconnecting;
  }
  if (millis() < nextEventStreamAttempt) return;
  nextEventStreamAttempt = millis() + 3000;
  Serial.printf("[events] GET %s\n", kikiUrl("/events").c_str());
  if (!eventStream.connect(KIKI_HOST, KIKI_PORT, 500)) {
    networkLink = Link::Reconnecting;
    return;
  }
  eventStream.printf("GET /events HTTP/1.1\r\nHost: %s:%d\r\n\r\n", KIKI_HOST, KIKI_PORT);
  eventStream.setTimeout(2000);
  Serial.printf("[events] %s\n", eventStream.readStringUntil('\n').c_str());  // status line
  while (eventStream.connected() && eventStream.readStringUntil('\n') != "\r") {}  // headers
  networkLink = Link::Live;
}

void readEvents() {
  while (eventStream.available()) {  // one event per "data: {...}" line
    String line = eventStream.readStringUntil('\n');
    if (line.startsWith("data: ")) {
      String *json = new String(line.substring(6));
      xQueueSend(eventLines, &json, portMAX_DELAY);  // the loop takes every line within a frame
    }
  }
}

void networkTask(void *) {
  for (;;) {
    if (WiFi.status() == WL_CONNECTED) {
      keepEventStreamOpen();
      readEvents();
    }
    Post post;
    if (xQueueReceive(posts, &post, pdMS_TO_TICKS(10))) {
      const char *path = post.kind == PostKind::Command ? "/command" : post.kind == PostKind::Reset ? "/reset" : "/item";
      int status = postJson(path, *post.json);
      PostResult result{post.kind, status, post.subject, post.detail};
      xQueueSend(postResults, &result, portMAX_DELAY);
      delete post.json;
    }
  }
}

void startNetwork() {
  eventLines = xQueueCreate(16, sizeof(String *));
  posts = xQueueCreate(8, sizeof(Post));
  postResults = xQueueCreate(8, sizeof(PostResult));
  xTaskCreate(networkTask, "network", 8192, nullptr, 2, nullptr);
}

// ---------- edits: the screen changes first, Kiki is told after ----------
// While an edit is on its way, Kiki's List events are held (the newest one is kept): an older
// List arriving between two quick edits would otherwise flick the row back and forth. When the
// last edit is answered, the newest List is shown; if an edit failed and none came, the List as
// Kiki last sent it comes back.
int editsInFlight = 0;
bool quantityUnsent = false;  // the item sheet waits for the stepper to settle (sheet.ino)
bool editFailed = false;
String heldList;

bool editsSyncing() { return editsInFlight > 0 || quantityUnsent; }

void showKikisList() {
  if (heldList.length()) {
    String json = heldList;
    heldList = "";
    handleEvent(json.c_str());
  } else if (editFailed) {
    items = serverItems;
    showList();
  }
  editFailed = false;
}

void sendPost(PostKind kind, JsonDocument &body, const String &subject, const String &detail = "") {
  String *json = new String();
  serializeJson(body, *json);
  Post post{kind, json, new String(subject), new String(detail)};
  if (kind != PostKind::Command) editsInFlight++;
  if (!xQueueSend(posts, &post, 0)) {  // eight requests already waiting: Kiki is unreachable
    PostResult result{kind, -1, post.subject, post.detail};
    xQueueSend(postResults, &result, 0);
    delete json;
  }
}

// Called from loop(): whatever networkTask brought in since the last frame.
void handleNetworkNews() {
  static Link shownLink = Link::Connecting;
  if (networkLink != shownLink) {
    shownLink = eventLink = networkLink;
    showConnection(eventLink);
  }
  String *json;
  while (xQueueReceive(eventLines, &json, 0)) {
    handleEvent(json->c_str());
    delete json;
  }
  PostResult result;
  while (xQueueReceive(postResults, &result, 0)) {
    finishPost(result);
    delete result.subject;
    delete result.detail;
  }
}

void handleEvent(const char *json) {
  JsonDocument event(&spiRam);
  if (DeserializationError error = deserializeJson(event, json)) {
    Serial.printf("[events] couldn't parse: %s\n", error.c_str());
    return;
  }
  String type = event["type"] | "";
  if (type == "snapshot") {
    readItems(event["items"], false);
    runs.clear();
    for (JsonObjectConst turn : event["turns"].as<JsonArrayConst>()) addRun(turn);  // oldest first
    showRuns();
    showList();
    setKikiState(event["state"] | "idle");
  } else if (type == "state") {
    setKikiState(event["value"] | "idle");
  } else if (type == "progress") {
    showProgress(event["text"] | "");  // "Filling cart, 4 of 12" while the orb thinks
  } else if (type == "list") {
    if (editsSyncing()) {
      heldList = json;
      return;
    }
    readItems(event["items"], true);
    showList();
  } else if (type == "turn") {
    addRun(event.as<JsonObjectConst>());
    showRuns();
    addNewestRunToHistory();
    runJustFinished = event["error"].isNull();
    if (runs.front().said.length()) {  // the web UI's caption(): the orb says it, words on its timing
      orbSays(runs.front().said);
      showCaption(runs.front().said);
    }
  }
  Serial.printf("[events] %s  state=%s items=%d runs=%d\n", type.c_str(), kikiState.c_str(), (int)items.size(),
                (int)runs.size());
}

void setKikiState(const String &state) {
  kikiState = state;
  bool showDone = state == "idle" && runJustFinished;
  runJustFinished = false;
  showKikiState(state, showDone);
}

// Marks rows that are new or different, the way the web UI compares "quantity status".
void readItems(JsonArrayConst list, bool markChanges) {
  std::vector<Item> previous = std::move(items);
  items.clear();
  for (JsonObjectConst entry : list) {
    Item item{entry["name"].as<String>(), entry["quantity"] | 1, entry["status"] == "needed", false,
              entry["buying_pattern"] == "frequent", entry["product_name"] | "", entry["on_list"] | true};
    if (markChanges) {
      item.changed = true;
      for (const Item &before : previous)
        if (before.name.equalsIgnoreCase(item.name))
          item.changed = before.quantity != item.quantity || before.needed != item.needed;
    }
    items.push_back(item);
  }
  serverItems = items;
}

// ---------- runs: what History and the last-run line show ----------

String joinNames(JsonArrayConst list) {
  String joined;
  for (JsonVariantConst entry : list) {
    if (joined.length()) joined += ", ";
    joined += entry.is<const char *>() ? entry.as<String>() : entry["name"].as<String>();
  }
  return joined;
}

String joinParts(const String &a, const String &b) { return a.length() && b.length() ? a + " · " + b : a + b; }

// ui.html's chip(), word for word except "→", which Inter's Latin subset doesn't have: "now".
// Analyzing and filling the Cart are addOrdering's, below.
Chip chipFor(JsonObjectConst call) {
  String name = call["name"] | "";
  JsonObjectConst args = call["args"], result = call["result"];
  if (!result["error"].isNull()) return {name + ": " + result["error"].as<String>(), true};
  bool notFound = result["not_found"].is<const char *>();
  String notOnList = String("not on list: ") + (result["not_found"] | "");
  if (name == "add_items") {
    String added;
    for (JsonObjectConst item : result["added"].as<JsonArrayConst>()) {
      if (added.length()) added += ", ";
      added += item["name"].as<String>();
      if ((item["quantity"] | 1) > 1) added += " ×" + String(item["quantity"].as<int>());
    }
    String parts = joinParts(added.length() ? "added " + added : "",
                             result["already_present"].size() ? "already there: " + joinNames(result["already_present"]) : "");
    return {parts.length() ? parts : String("added nothing"), false};
  }
  if (name == "remove_items")
    return {joinParts(result["removed"].size() ? "not needed: " + joinNames(result["removed"]) : "",
                      result["not_found"].size() ? "not on list: " + joinNames(result["not_found"]) : ""),
            false};
  if (name == "set_quantity") return {notFound ? notOnList : args["name"].as<String>() + " now " + args["quantity"].as<String>(), false};
  if (name == "set_usual_quantity")
    return {notFound ? notOnList : args["name"].as<String>() + " usually " + args["quantity"].as<String>(), false};
  if (name == "set_buying_pattern")
    return {notFound ? notOnList : args["name"].as<String>() + " now " + args["buying_pattern"].as<String>(), false};
  if (name == "rename_item") return {notFound ? notOnList : args["name"].as<String>() + " now " + args["new_name"].as<String>(), false};
  if (name == "clear_list" || name == "clear_all_items") {  // clear_list: the name before v0.17
    int removed = result["removed"].size();
    return {"cleared " + String(removed) + (removed == 1 ? " item" : " items"), false};
  }
  if (name == "reset_list") return {"reset: " + String(result["needed"].size()) + " needed", false};
  if (!result["failed"].isNull()) return {"Instacart: " + result["failed"].as<String>(), true};
  if (name == "set_product_for_item") {
    if (notFound) return {notOnList, false};
    if (!result["no_results"].isNull()) return {"no results: " + result["no_results"].as<String>(), true};
    return {args["name"].as<String>() + " now " + result["product_name"].as<String>(), false};
  }
  if (name == "forget_product_for_item") return {notFound ? notOnList : args["name"].as<String>() + ": product forgotten", false};
  return {name, false};
}

String counted(int n, const char *word, const char *plural) { return String(n) + " " + (n == 1 ? word : plural); }

String whyFailed(const String &reason) {
  return reason == "sold_out" ? "sold out" : reason == "not_found" ? "not found" : reason == "not_added" ? "didn't go in"
       : reason == "more_than_nine" ? "more than nine" : reason;
}

// Ordering (v0.17), as ui.html shows it: a few summary chips, and each item's Product, guess or
// failure as a row under Products in its History card.
void addOrdering(Run &run, const String &name, JsonObjectConst result) {
  for (JsonObjectConst m : result["matched"].as<JsonArrayConst>())
    run.products.push_back({capitalized(m["name"] | ""), m["product_name"] | "", "", false});
  if (name == "learn_product_preferences") {
    int orders = result["new_orders"] | 0, matched = result["matched"].size(), left = result["no_product"].size();
    int unreadable = result["unreadable_orders"].size();
    run.chips.push_back({orders ? "read " + counted(orders, "new order", "new orders") : String("no new orders"), false});
    if (matched) run.chips.push_back({"matched " + String(matched), false});
    if (left) {
      run.chips.push_back({String(left) + " without a product", false});
      run.products.push_back({"No product", joinNames(result["no_product"]), "", false, true});
    }
    if (unreadable) run.chips.push_back({counted(unreadable, "order", "orders") + " unreadable", true});
    for (JsonObjectConst o : result["unreadable_orders"].as<JsonArrayConst>())
      run.products.push_back({"Order " + o["order_id"].as<String>(), o["why"] | "", "", true});
    return;
  }
  int total = result["lines"].size(), guessed = 0, failed = 0;
  for (JsonObjectConst line : result["lines"].as<JsonArrayConst>()) {
    String status = line["status"] | "";
    if (status == "top_match") {
      guessed++;
      run.products.push_back({capitalized(line["item"] | ""), line["product_name"] | "", "top match", false});
    } else if (status == "failed") {
      failed++;
      run.products.push_back({capitalized(line["item"] | ""), whyFailed(line["reason"] | ""), "", true});
    }
  }
  if (!total) return run.chips.push_back({"nothing needed", false});
  run.chips.push_back({"cart: " + String(total - failed) + " of " + String(total), false});
  if (guessed) run.chips.push_back({counted(guessed, "top match", "top matches"), false});
  if (failed) run.chips.push_back({String(failed) + " failed", true});
  if (!result["matching_failed"].isNull()) run.chips.push_back({"couldn't check past orders", true});
}

String secondsText(JsonVariantConst ms) { return ms.isNull() ? String("–") : String(ms.as<float>() / 1000, 1) + " s"; }

// days since 1970-01-01 for a civil date (Howard Hinnant's algorithm): newlib has no timegm().
long daysFromCivil(int y, int m, int d) {
  y -= m <= 2;
  long era = (y >= 0 ? y : y - 399) / 400;
  long yoe = y - era * 400;
  long doy = (153 * (m + (m > 2 ? -3 : 9)) + 2) / 5 + d - 1;
  return era * 146097 + yoe * 365 + yoe / 4 - yoe / 100 + doy - 719468;
}

// "2026-10-22T01:17:45Z" (UTC) -> "09:17:45 PM" in KIKI_TZ, like toLocaleTimeString in the web UI.
String localTimeOf(const char *timestamp) {
  int y, mo, d, h, mi, s;
  if (sscanf(timestamp, "%d-%d-%dT%d:%d:%d", &y, &mo, &d, &h, &mi, &s) != 6) return "";
  time_t utc = (time_t)daysFromCivil(y, mo, d) * 86400 + h * 3600 + mi * 60 + s;
  struct tm local;
  localtime_r(&utc, &local);
  char text[16];
  strftime(text, sizeof text, "%I:%M:%S %p", &local);
  return text;
}

void addRun(JsonObjectConst turn) {
  Run run;
  run.time = localTimeOf(turn["ts"] | "");
  run.source = turn["source"] | "";
  run.latency = secondsText(turn["latency_ms"]["total"]);
  run.heard = turn["heard"] | "";
  run.said = turn["said"] | "";
  run.error = turn["error"] | "";
  for (JsonObjectConst call : turn["tool_calls"].as<JsonArrayConst>()) {
    String name = call["name"] | "";
    JsonObjectConst result = call["result"];
    if ((name == "learn_product_preferences" || name == "fill_cart") && result["failed"].isNull()) addOrdering(run, name, result);
    else run.chips.push_back(chipFor(call));
  }
  if (run.chips.empty()) run.chips.push_back({"no change", false});
  JsonObjectConst latency = turn["latency_ms"];
  run.details = "speech-to-text " + secondsText(latency["stt"]) + " · model " + secondsText(latency["llm"]) +
                " · speech " + secondsText(latency["tts"]) + " · " + (turn["model"] | "");
  runs.push_front(run);
  if (runs.size() > MAX_RUNS) runs.pop_back();
}

// ---------- requests back to Kiki ----------

// Runs on networkTask only.
int postJson(const char *path, const String &json) {
  uint32_t start = millis();
  HTTPClient http;
  http.setTimeout(3000);
  http.begin(kikiUrl(path));
  http.addHeader("Content-Type", "application/json");
  int status = http.POST(json);
  http.end();
  Serial.printf("[http] POST %s %s -> %d in %lu ms\n", path, json.c_str(), status, millis() - start);
  return status;
}

String failureReason(int status) { return status < 0 ? String("Kiki is offline") : "HTTP " + String(status); }

// The item sheet's edits (FR-0.33), each already on the screen; Kiki's new List comes back as an
// event. Needed is the same request as clicking a row in the browser (FR-0.27).
void sendNeeded(const String &name, bool needed) {
  JsonDocument body;
  body["name"] = name;
  body["needed"] = needed;
  sendPost(PostKind::Needed, body, name);
}

void sendQuantity(const String &name, int quantity) {
  JsonDocument body;
  body["name"] = name;
  body["quantity"] = quantity;
  sendPost(PostKind::Quantity, body, name);
}

void sendPattern(const String &name, bool frequent) {
  JsonDocument body;
  body["name"] = name;
  body["buying_pattern"] = frequent ? "frequent" : "occasional";
  sendPost(PostKind::Pattern, body, name);
}

void sendRename(const String &name, const String &newName) {
  JsonDocument body;
  body["name"] = name;
  body["new_name"] = newName;
  sendPost(PostKind::Rename, body, name, newName);
}

// The sheet's Forget (FR-0.34): the Item has no Product; the next Cart finds one for it.
void sendForget(const String &name) {
  JsonDocument body;
  body["name"] = name;
  body["forget_product"] = true;
  sendPost(PostKind::Forget, body, name);
}

// The List's Reset, after its second tap (FR-0.35).
void sendReset() {
  JsonDocument body;
  body.to<JsonObject>();
  sendPost(PostKind::Reset, body, "the list");
}

// The text box is already cleared; the answer arrives as a turn event.
void sendCommand(const String &text) {
  JsonDocument body;
  body["text"] = text;
  sendPost(PostKind::Command, body, text);
}

String editFailure(int status) {
  return status == 409 ? String("that name is taken") : status == 404 ? String("Kiki doesn't know it any more") : failureReason(status);
}

// A refused edit undoes itself (showKikisList), and a refused command goes back into the text
// box, with the reason.
void finishPost(const PostResult &result) {
  const String &subject = *result.subject;
  if (result.kind != PostKind::Command) {
    editsInFlight--;
    if (result.status == 200) {
      showFormError("");
    } else {
      editFailed = true;
      String reason = "Couldn't change " + subject + " (" + editFailure(result.status) + ").";
      showFormError(reason);
      sheetEditFailed(subject, *result.detail, reason);
    }
    if (!editsSyncing()) showKikisList();
  } else if (result.status == 202) {
    showFormError("");
  } else {
    putBackCommand(subject);
    showFormError("Couldn't send that (" + failureReason(result.status) + ").");
  }
}
