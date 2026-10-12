#include <Arduino.h>
#include <SPI.h>
#include <MFRC522.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>

// ---------- Network configuration ----------
// Wokwi's virtual WiFi: SSID "Wokwi-GUEST", no password, channel 6.
// On real hardware, use your own network and set WIFI_CHANNEL to 0.
const char* WIFI_SSID    = "Wokwi-GUEST";
const char* WIFI_PASS    = "";
const int   WIFI_CHANNEL = 6;

// Backend endpoint that receives the scan (must be reachable from the internet in Wokwi)
// const char* API_URL   = "https://httpbin.org/post";
const char* API_URL   = "https://gathered-smallest-finding-cluster.trycloudflare.com/api/attendance";
const char* API_KEY   = "CHANGE_ME";   // sent as a Bearer token
const char* DEVICE_ID = "reader-01";   // identifies this reader/location

const uint16_t HTTP_TIMEOUT_MS = 8000;
const uint32_t SAME_CARD_COOLDOWN_MS = 3000;

// ---------- RFID pins ----------
#define RST_PIN    22  // Reset pin
#define SS_SPI_PIN 21  // SDA (Slave Select) pin

MFRC522 mfrc522(SS_SPI_PIN, RST_PIN);  // Create MFRC522 instance

String lastUid = "";
uint32_t lastScanMs = 0;

// ---------- WiFi ----------
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
    return true;
  }
  Serial.println(F("WiFi connection failed"));
  return false;
}

// ---------- HTTP ----------
// Sends {"uid":"11223344","device_id":"reader-01"} to the backend.
bool sendAttendance(const String& uid) {
  if (!connectWiFi()) return false;

  String url = API_URL;
  bool useTls = url.startsWith("https://");

  WiFiClientSecure secureClient;
  WiFiClient plainClient;
  HTTPClient http;

  if (useTls) {
    // TESTING ONLY: skips certificate validation.
    // For production, use secureClient.setCACert(rootCA) with your server's root CA.
    secureClient.setInsecure();
    http.begin(secureClient, url);
  } else {
    http.begin(plainClient, url);
  }

  http.setTimeout(HTTP_TIMEOUT_MS);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("Authorization", String("Bearer ") + API_KEY);

  String body = String("{\"uid\":\"") + uid + "\",\"device_id\":\"" + DEVICE_ID + "\"}";

  int code = http.POST(body);
  bool ok = (code >= 200 && code < 300);

  if (code > 0) {
    Serial.printf("HTTP %d\n", code);
    Serial.println(http.getString());  // server response (e.g. employee name / status)
  } else {
    Serial.printf("HTTP request failed: %s\n", http.errorToString(code).c_str());
  }

  http.end();
  return ok;
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

void setup() {
  Serial.begin(115200);   // Initialize serial communications with the PC
  while (!Serial);       // Wait for serial port to open (needed for native USB boards)

  SPI.begin();           // Init SPI bus
  mfrc522.PCD_Init();    // Init MFRC522 card
  mfrc522.PCD_DumpVersionToSerial();

  connectWiFi();

  Serial.println(F("Approximate your card to the reader..."));
  Serial.println(F("-------------------------------------"));
}

void loop() {
  // Look for new cards
  if ( ! mfrc522.PICC_IsNewCardPresent()) {
    return;
  }

  // Select one of the cards
  if ( ! mfrc522.PICC_ReadCardSerial()) {
    return;
  }

  String uid = uidToString(mfrc522.uid);

  // Ignore the same card scanned again within the cooldown (avoids double check-ins)
  if (uid == lastUid && millis() - lastScanMs < SAME_CARD_COOLDOWN_MS) {
    mfrc522.PICC_HaltA();
    mfrc522.PCD_StopCrypto1();
    return;
  }
  lastUid = uid;
  lastScanMs = millis();

  // Print UID on Serial Monitor
  Serial.print(F("Card UID: "));
  Serial.println(uid);

  // Send to backend
  if (sendAttendance(uid)) {
    Serial.println(F("Attendance recorded"));
  } else {
    Serial.println(F("Failed to record attendance"));
  }

  // Halt PICC to stop reading it continuously
  mfrc522.PICC_HaltA();
  mfrc522.PCD_StopCrypto1();
}