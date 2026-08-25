#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_SSD1306.h>

Adafruit_SSD1306 display(128, 64, &Wire, -1);

void setup() {
  Serial.begin(115200);
  delay(1000);
  Wire.begin(21, 22);

  uint8_t addr = 0;
  for (uint8_t a = 1; a < 127; a++) {
    Wire.beginTransmission(a);
    if (Wire.endTransmission() == 0) {
      Serial.printf("found 0x%02X\n", a);
      addr = a;
    }
  }
  if (addr == 0) { Serial.println("no i2c device"); return; }

  if (!display.begin(SSD1306_SWITCHCAPVCC, addr)) {
    Serial.println("ssd1306 init failed");
    return;
  }
  display.clearDisplay();
  display.setTextSize(2);
  display.setTextColor(SSD1306_WHITE);
  display.setCursor(0, 20);
  display.println("HELLO");
  display.display();
  Serial.println("display ok");
}

void loop() {}