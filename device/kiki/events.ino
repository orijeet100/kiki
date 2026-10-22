// Kiki's side of the conversation: the live events that drive the screen, and the two requests
// the screen sends back. Same endpoints and same meaning as the web UI (ui.html).

WiFiClient eventStream;
uint32_t nextEventStreamAttempt = 0;

String kikiUrl(const char *path) { return String("http://") + KIKI_HOST + ":" + KIKI_PORT + path; }

void keepEventStreamOpen() {
  if (eventStream.connected()) return;
  if (eventLink == Link::Live) {
    Serial.println("[events] stream closed, retrying");
    eventLink = Link::Reconnecting;
    showConnection(eventLink);
  }
  if (millis() < nextEventStreamAttempt) return;
  nextEventStreamAttempt = millis() + 3000;
  Serial.printf("[events] GET %s\n", kikiUrl("/events").c_str());
  if (!eventStream.connect(KIKI_HOST, KIKI_PORT, 500)) {
    eventLink = Link::Reconnecting;
    showConnection(eventLink);
    return;
  }
  eventStream.printf("GET /events HTTP/1.1\r\nHost: %s:%d\r\n\r\n", KIKI_HOST, KIKI_PORT);
  eventStream.setTimeout(2000);
  Serial.printf("[events] %s\n", eventStream.readStringUntil('\n').c_str());  // status line
  while (eventStream.connected() && eventStream.readStringUntil('\n') != "\r") {}  // headers
  eventLink = Link::Live;
  showConnection(eventLink);
}

void readEvents() {
  while (eventStream.available()) {  // one event per "data: {...}" line
    String line = eventStream.readStringUntil('\n');
    if (line.startsWith("data: ")) handleEvent(line.c_str() + 6);
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
  } else if (type == "list") {
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
    Item item{entry["name"].as<String>(), entry["quantity"] | 1, entry["status"] == "needed", false};
    if (markChanges) {
      item.changed = true;
      for (const Item &before : previous)
        if (before.name.equalsIgnoreCase(item.name))
          item.changed = before.quantity != item.quantity || before.needed != item.needed;
    }
    items.push_back(item);
  }
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
  if (name == "clear_list") {
    int removed = result["removed"].size();
    return {"cleared " + String(removed) + (removed == 1 ? " item" : " items"), false};
  }
  return {name, false};
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
  for (JsonObjectConst call : turn["tool_calls"].as<JsonArrayConst>()) run.chips.push_back(chipFor(call));
  if (run.chips.empty()) run.chips.push_back({"no change", false});
  JsonObjectConst latency = turn["latency_ms"];
  run.details = "speech-to-text " + secondsText(latency["stt"]) + " · model " + secondsText(latency["llm"]) +
                " · speech " + secondsText(latency["tts"]) + " · " + (turn["model"] | "");
  runs.push_front(run);
  if (runs.size() > MAX_RUNS) runs.pop_back();
}

// ---------- requests back to Kiki ----------

int postJson(const char *path, JsonDocument &body) {
  String json;
  serializeJson(body, json);
  HTTPClient http;
  http.setTimeout(3000);
  http.begin(kikiUrl(path));
  http.addHeader("Content-Type", "application/json");
  int status = http.POST(json);
  http.end();
  Serial.printf("[http] POST %s %s -> %d\n", path, json.c_str(), status);
  return status;
}

String failureReason(int status) { return status < 0 ? String("Kiki is offline") : "HTTP " + String(status); }

// The same request as clicking a row in the browser (FR-0.27); the new List comes back as an event.
void setNeeded(const Item &item) {
  JsonDocument body;
  body["name"] = item.name;
  body["needed"] = !item.needed;
  int status = postJson("/item", body);
  showFormError(status == 200 ? "" : "Couldn't change " + item.name + " (" + failureReason(status) + ").");
}

// Returns whether Kiki took it; the answer arrives as a turn event.
bool sendCommand(const String &text) {
  JsonDocument body;
  body["text"] = text;
  int status = postJson("/command", body);
  showFormError(status == 202 ? "" : "Couldn't send that (" + failureReason(status) + ").");
  return status == 202;
}
