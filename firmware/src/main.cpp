#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_SSD1306.h>
#include <HX711.h>

#define OLED_ADDR   0x3C
#define PIN_SDA     21
#define PIN_SCL     22
#define PIN_HX_DT   16
#define PIN_HX_SCK  4

#define SCALE_FACTOR 406.0f

Adafruit_SSD1306 display(128, 64, &Wire, -1);
HX711 scale;

static bool oledOk = false;

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

void drawWeight(float g) {
  display.clearDisplay();
  display.setTextSize(2);
  display.setCursor(0, 8);
  display.printf("%.1f", g);
  display.setTextSize(1);
  display.setCursor(0, 40);
  display.println("gram");
  display.display();
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Wire.begin(PIN_SDA, PIN_SCL);
  initOled();

  scale.begin(PIN_HX_DT, PIN_HX_SCK);
  scale.set_scale(SCALE_FACTOR);

  Serial.println("taring... keep the platform empty");
  delay(2000);
  scale.tare(20);
  Serial.println("ready");
}

void loop() {
  if (!scale.is_ready()) {
    Serial.println("hx711 not ready");
    delay(200);
    return;
  }

  float g = scale.get_units(10);
  Serial.printf("%.2f g\n", g);

  bool alive = oledAlive();
  if (alive && !oledOk) {
    initOled();
    Serial.println("oled recovered");
  } else if (!alive) {
    oledOk = false;
  }

  if (oledOk) drawWeight(g);

  delay(200);
}