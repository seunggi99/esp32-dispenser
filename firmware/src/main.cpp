#include <Arduino.h>
#include <Wire.h>
#include <WiFi.h>
#include <PubSubClient.h>
#include <Adafruit_SSD1306.h>
#include <HX711.h>
#include "secrets.h"

#define OLED_ADDR   0x3C
#define PIN_SDA     21
#define PIN_SCL     22
#define PIN_HX_DT   16
#define PIN_HX_SCK  4
#define PIN_PUMP_IA 25
#define PIN_PUMP_IB 26

#define SCALE_FACTOR 405.0f

Adafruit_SSD1306 display(128, 64, &Wire, -1);
HX711 scale;
WiFiClient wifiClient;
PubSubClient mqtt(wifiClient);

static bool oledOk = false;
static char topicCommand[64];
static char topicResult[64];
static char topicTelemetry[64];
static unsigned long lastTelemetry = 0;

bool oledAlive() {
  Wire.beginTransmission(OLED_ADDR);
  return Wire.endTransmission() == 0;
}

void initOled() {
  if (!display.begin(SSD1306_SWITCHCAPVCC, OLED_ADDR)) return;
  display.setTextColor(SSD1306_WHITE);
  display.clearDisplay();
  display.display();
  oledOk = true;
}

void drawStatus(float g, const char* state) {
  if (!oledOk) return;
  display.clearDisplay();
  display.setTextSize(1);
  display.setCursor(0, 0);
  display.println(state);
  display.setTextSize(2);
  display.setCursor(0, 20);
  display.printf("%.1f", g);
  display.setTextSize(1);
  display.setCursor(0, 48);
  display.println(mqtt.connected() ? "mqtt ok" : "mqtt --");
  display.display();
}

void pumpOff() {
  digitalWrite(PIN_PUMP_IA, LOW);
  digitalWrite(PIN_PUMP_IB, LOW);
}

void runPump(uint32_t ms) {
  drawStatus(scale.get_units(5), "RUNNING");

  digitalWrite(PIN_PUMP_IA, HIGH);
  digitalWrite(PIN_PUMP_IB, LOW);
  delay(ms);
  pumpOff();

  // 장비는 명령 수행 여부만 보고한다. 성공 판정은 서버가 한다.
  char payload[128];
  snprintf(payload, sizeof(payload),
           "{\"device\":\"%s\",\"duration_ms\":%lu,\"reported\":\"done\"}",
           DEVICE_ID, ms);
  mqtt.publish(topicResult, payload);
  Serial.printf("result -> %s\n", payload);
}

void onMessage(char* topic, byte* payload, unsigned int len) {
  char buf[128];
  unsigned int n = len < sizeof(buf) - 1 ? len : sizeof(buf) - 1;
  memcpy(buf, payload, n);
  buf[n] = '\0';

  Serial.printf("cmd <- %s\n", buf);

  // {"duration_ms":3000} 형태에서 숫자만 추출
  char* p = strstr(buf, "duration_ms");
  if (!p) return;
  p = strchr(p, ':');
  if (!p) return;

  long ms = strtol(p + 1, nullptr, 10);
  if (ms <= 0 || ms > 30000) {
    Serial.println("invalid duration");
    return;
  }
  runPump((uint32_t)ms);
}

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("wifi connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\nwifi ok: %s\n", WiFi.localIP().toString().c_str());
}

void connectMqtt() {
  static unsigned long backoff = 1000;
  if (mqtt.connected()) { backoff = 1000; return; }

  Serial.print("mqtt connecting... ");
  if (mqtt.connect(DEVICE_ID)) {
    Serial.println("ok");
    mqtt.subscribe(topicCommand);
    backoff = 1000;
  } else {
    Serial.printf("failed rc=%d, retry in %lums\n", mqtt.state(), backoff);
    delay(backoff);
    if (backoff < 16000) backoff *= 2;
  }
}

void setup() {
  pinMode(PIN_PUMP_IA, OUTPUT);
  pinMode(PIN_PUMP_IB, OUTPUT);
  pumpOff();

  Serial.begin(115200);
  delay(1000);

  snprintf(topicCommand,   sizeof(topicCommand),   "device/%s/command",   DEVICE_ID);
  snprintf(topicResult,    sizeof(topicResult),    "device/%s/result",    DEVICE_ID);
  snprintf(topicTelemetry, sizeof(topicTelemetry), "device/%s/telemetry", DEVICE_ID);

  Wire.begin(PIN_SDA, PIN_SCL);
  initOled();

  scale.begin(PIN_HX_DT, PIN_HX_SCK);
  scale.set_scale(SCALE_FACTOR);
  Serial.println("taring... keep the platform empty");
  delay(2000);
  scale.tare(20);

  connectWifi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setCallback(onMessage);

  Serial.println("ready");
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWifi();
  if (!mqtt.connected()) connectMqtt();
  mqtt.loop();

  if (!scale.is_ready()) { delay(50); return; }
  float g = scale.get_units(5);

  bool alive = oledAlive();
  if (alive && !oledOk) { initOled(); }
  else if (!alive) { oledOk = false; }
  drawStatus(g, "IDLE");

  if (millis() - lastTelemetry > 1000) {
    lastTelemetry = millis();
    char payload[96];
    snprintf(payload, sizeof(payload),
             "{\"device\":\"%s\",\"weight_g\":%.2f}", DEVICE_ID, g);
    mqtt.publish(topicTelemetry, payload);
  }

  delay(100);
}