#include <Arduino.h>
#include <SPI.h>
#include <MFRC522.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <ArduinoJson.h>
#include <time.h>

// ---------- Network configuration ----------
// Wokwi's virtual WiFi: SSID "Wokwi-GUEST", no password, channel 6.
// On real hardware, use your own network and set WIFI_CHANNEL to 0.
const char* WIFI_SSID    = "Wokwi-GUEST";
const char* WIFI_PASS    = "";
const int   WIFI_CHANNEL = 6;

// Backend endpoint that receives the scan (must be reachable from the internet in Wokwi)
const char* API_URL   = "https://appreciation-governmental-powers-introduce.trycloudflare.com/api/attendance";
const char* API_KEY   = "CHANGE_ME";   // sent as a Bearer token
const char* DEVICE_ID = "reader-01";   // identifies this reader/location

const uint16_t HTTP_TIMEOUT_MS    = 5000;   // max wait for the server's reply
const uint16_t CONNECT_TIMEOUT_MS = 2000;   // max wait to open a connection
const uint32_t SAME_CARD_COOLDOWN_MS = 3000;
const uint32_t MESSAGE_SHOW_MS = 2000;

// ---------- RFID pins ----------
#define RST_PIN    22  // Reset pin
#define SS_SPI_PIN 21  // SDA (Slave Select) pin

MFRC522 mfrc522(SS_SPI_PIN, RST_PIN);  // Create MFRC522 instance

// ---------- LCD (I2C) ----------
#define LCD_SDA 25
#define LCD_SCL 26
LiquidCrystal_I2C lcd(0x27, 16, 2);  // address 0x27, 16 columns, 2 rows

// ---------- Scan queue ----------
// Every card tap is put here by the reader task and removed by loop()
// only after the server confirms it.
struct Scan {
  char uid[21];     // card ID, e.g. "01020304"
  char id[40];      // unique ID for this tap (lets the server ignore repeats)
  uint32_t ts;      // time of the tap (seconds since 1970), 0 if the clock wasn't set yet
};

const int QUEUE_MAX = 20;
QueueHandle_t scanQ;          // thread-safe queue shared by the two tasks

uint32_t nextAttemptMs = 0;   // don't try sending again before this time
uint32_t backoffMs = 1000;    // grows after each failure, up to 30 s

// ---------- Network clients ----------
// Global on purpose: keeps the secure connection open between scans.
WiFiClientSecure secureClient;
WiFiClient plainClient;

// ---------- LCD access (shared by both tasks, so it is protected by a mutex) ----------
SemaphoreHandle_t lcdMutex;
bool showingMessage = false;
uint32_t messageUntilMs = 0;
int lastPending = -1;

// Draws two lines. The caller must hold lcdMutex (or be in setup, before the tasks start).
void lcdPrint(const String& line1, const String& line2 = "") {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(line1);
  lcd.setCursor(0, 1);
  lcd.print(line2);
}

// Shows a message for a couple of seconds, then the idle screen comes back.
void showTimed(const String& a, const String& b = "") {
  xSemaphoreTake(lcdMutex, portMAX_DELAY);
  lcdPrint(a, b);
  showingMessage = true;
  messageUntilMs = millis() + MESSAGE_SHOW_MS;
  xSemaphoreGive(lcdMutex);
}

// Called continuously by the reader task: returns to the idle screen when a message
// has been shown long enough, and keeps the "Pending: N" count up to date.
void tickDisplay() {
  int pending = (int)uxQueueMessagesWaiting(scanQ);

  xSemaphoreTake(lcdMutex, portMAX_DELAY);
  bool expired = showingMessage && (int32_t)(millis() - messageUntilMs) >= 0;
  bool pendingChanged = !showingMessage && pending != lastPending;
  if (expired || pendingChanged) {
    lcdPrint("Scan your card", pending > 0 ? String("Pending: ") + pending : String(""));
    lastPending = pending;
    showingMessage = false;
  }
  xSemaphoreGive(lcdMutex);
}

// ---------- WiFi + clock ----------
bool connectWiFi(uint32_t timeoutMs = 15000) {
  if (WiFi.status() == WL_CONNECTED) return true;

  Serial.print(F("Connecting to WiFi"));
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS, WIFI_CHANNEL);

  uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - start < timeoutMs) {
    delay(250);
    Serial.print('.');
  }
  Serial.println();

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print(F("WiFi connected, IP: "));
    Serial.println(WiFi.localIP());
    configTime(0, 0, "pool.ntp.org", "time.nist.gov");  // real time (UTC), used to stamp each tap
    return true;
  }
  Serial.println(F("WiFi connection failed"));
  return false;
}

// Seconds since 1970, or 0 if the clock hasn't been set yet
uint32_t nowEpoch() {
  time_t t = time(nullptr);
  return t > 1700000000 ? (uint32_t)t : 0;
}

// ---------- HTTP (runs in loop()) ----------
// Sends one scan to the backend.
// Returns the HTTP status code (or -1 if the request failed).
// Fills 'name' with the person's name if the server sent one.
int sendAttendance(const Scan& s, String& name, String& status) {
  if (!connectWiFi(4000)) return -1;  // short wait so retries stay quick

  uint32_t t0 = millis();
  String url = API_URL;
  bool useTls = url.startsWith("https://");

  JsonDocument req;
  req["uid"] = s.uid;
  req["device_id"] = DEVICE_ID;
  req["scan_id"] = s.id;
  req["scanned_at"] = s.ts;
  String body;
  serializeJson(req, body);

  int code = -1;

  // Up to 2 tries: if the kept-open connection turns out to be dead,
  // drop it and retry once with a fresh one.
  for (int attempt = 0; attempt < 2; attempt++) {
    HTTPClient http;

    if (useTls) {
      http.begin(secureClient, url);
    } else {
      http.begin(plainClient, url);
    }

    http.setReuse(true);
    http.setConnectTimeout(CONNECT_TIMEOUT_MS);
    http.setTimeout(HTTP_TIMEOUT_MS);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("Authorization", String("Bearer ") + API_KEY);

    code = http.POST(body);

    if (code > 0) {
      String response = http.getString();
      Serial.printf("HTTP %d\n", code);
      Serial.println(response);

      JsonDocument doc;
      if (!deserializeJson(doc, response)) {
        name = doc["data"]["name"] | "";
        status = doc["data"]["status"] | "";
      }
      http.end();
      break;
    }

    Serial.printf("HTTP request failed: %s\n", http.errorToString(code).c_str());
    http.end();

    bool staleConnection = (code <= -2 && code >= -5);
    if (!staleConnection) break;  // e.g. connection refused (-1): offline, don't retry now

    Serial.println(F("Connection dropped, retrying with a fresh one"));
    secureClient.stop();
    plainClient.stop();
  }

  Serial.printf("Send took %lu ms\n", (unsigned long)(millis() - t0));
  return code;
}

// ---------- Helpers ----------
// Builds an uppercase hex string without separators, e.g. "11223344"
String uidToString(const MFRC522::Uid& uid) {
  String s;
  for (byte i = 0; i < uid.size; i++) {
    if (uid.uidByte[i] < 0x10) s += '0';
    s += String(uid.uidByte[i], HEX);
  }
  s.toUpperCase();
  return s;
}

// ---------- Reader task ----------
// Does only two things, both fast: watch for cards and keep the LCD up to date.
// It never waits on the network, so taps are always caught, even while a send is in progress.
void readerTask(void*) {
  String lastUid = "";
  uint32_t lastScanMs = 0;

  for (;;) {
    tickDisplay();

    if (mfrc522.PICC_IsNewCardPresent() && mfrc522.PICC_ReadCardSerial()) {
      String uid = uidToString(mfrc522.uid);

      // Ignore the same card scanned again within the cooldown (avoids double check-ins)
      if (!(uid == lastUid && millis() - lastScanMs < SAME_CARD_COOLDOWN_MS)) {
        lastUid = uid;
        lastScanMs = millis();

        Serial.print(F("Card UID: "));
        Serial.println(uid);

        Scan s;
        memset(&s, 0, sizeof(s));
        strlcpy(s.uid, uid.c_str(), sizeof(s.uid));
        snprintf(s.id, sizeof(s.id), "%s-%08X%08X", DEVICE_ID, (unsigned)esp_random(), (unsigned)esp_random());
        s.ts = nowEpoch();

        if (xQueueSend(scanQ, &s, 0) == pdTRUE) {
          Serial.printf("Queued scan (pending: %d)\n", (int)uxQueueMessagesWaiting(scanQ));
          showTimed("Saved", uid);
        } else {
          Serial.println(F("Queue full, scan dropped"));
          showTimed("Queue full", "Try later");
        }
      }

      // Stop talking to this card until it is removed and presented again
      mfrc522.PICC_HaltA();
      mfrc522.PCD_StopCrypto1();
    }

    vTaskDelay(pdMS_TO_TICKS(30));  // poll about 30 times per second
  }
}

void setup() {
  Serial.begin(115200);   // Initialize serial communications with the PC
  while (!Serial);       // Wait for serial port to open (needed for native USB boards)

  lcdMutex = xSemaphoreCreateMutex();
  scanQ = xQueueCreate(QUEUE_MAX, sizeof(Scan));

  Wire.begin(LCD_SDA, LCD_SCL);
  lcd.init();
  lcd.backlight();
  lcdPrint("Starting...");

  SPI.begin();           // Init SPI bus
  mfrc522.PCD_Init();    // Init MFRC522 card
  mfrc522.PCD_DumpVersionToSerial();

  // TESTING ONLY: skips certificate validation. Use setCACert() for production.
  secureClient.setInsecure();

  connectWiFi();

  // Start the reader task. From here on it owns the RFID reader and shares the LCD.
  xTaskCreatePinnedToCore(readerTask, "reader", 6144, nullptr, 2, nullptr, 1);

  Serial.println(F("Approximate your card to the reader..."));
  Serial.println(F("-------------------------------------"));
}

// loop() only sends queued scans to the server. Reading cards happens in readerTask.
void loop() {
  Scan s;
  // Look at the oldest scan without removing it (waits up to 0.2 s for one to appear)
  if (xQueuePeek(scanQ, &s, pdMS_TO_TICKS(200)) != pdTRUE) return;

  // Waiting out a retry delay after a failure
  if ((int32_t)(millis() - nextAttemptMs) < 0) {
    vTaskDelay(pdMS_TO_TICKS(50));
    return;
  }

  String name, status;
  int code = sendAttendance(s, name, status);

  bool success  = (code >= 200 && code < 300);
  bool rejected = (code >= 400 && code < 500 && code != 408 && code != 429);

  if (success || rejected) {
    Scan done;
    xQueueReceive(scanQ, &done, 0);   // the server answered, so remove it from the queue
    backoffMs = 1000;
    nextAttemptMs = 0;                // next scan in the queue can go right away

    if (rejected) {
      Serial.println(F("Server rejected the scan"));
      showTimed("Rejected", "Contact admin");
    } else if (status == "assigned") {
      Serial.println("Card assigned to: " + name);
      showTimed("Card assigned", name.substring(0, 16));
    } else if (status == "already_assigned") {
      Serial.println(F("Card already belongs to someone else"));
      showTimed("Card in use", "Try another");
    } else if (status == "disabled") {
      Serial.println(F("Card is disabled"));
      showTimed("Card disabled", "See admin");
    } else if (name.length() > 0) {
      Serial.println("Attendance recorded: " + name);
      showTimed("Welcome,", name.substring(0, 16));
    } else {
      Serial.println(F("Unknown card"));
      showTimed("Unknown card", s.uid);
    }
  } else {
    // Network problem or server error: keep the scan and try again later, waiting longer each time
    Serial.printf("Send failed, will retry in %lu ms (pending: %d)\n",
                  (unsigned long)backoffMs, (int)uxQueueMessagesWaiting(scanQ));
    nextAttemptMs = millis() + backoffMs;
    backoffMs = min<uint32_t>(backoffMs * 2, 30000);
  }
}