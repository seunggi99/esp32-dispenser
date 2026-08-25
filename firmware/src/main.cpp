#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_SSD1306.h>
#include <HX711.h>

Adafruit_SSD1306 display(128, 64, &Wire, -1);
HX711 scale;

void setup() {
  Serial.begin(115200);
  delay(1000);

  Wire.begin(21, 22);
  display.begin(SSD1306_SWITCHCAPVCC, 0x3C);
  display.setTextColor(SSD1306_WHITE);

  scale.begin(16, 4);
  scale.set_scale(405.0f);

  Serial.println("taring... keep empty");
  delay(2000);
  scale.tare(20);
  Serial.println("ready");
}

void loop() {
  float g = scale.get_units(10);

  Serial.printf("%.2f g\n", g);

  display.clearDisplay();
  display.setTextSize(2);
  display.setCursor(0, 8);
  display.printf("%.1f", g);
  display.setTextSize(1);
  display.setCursor(0, 40);
  display.println("gram");
  display.display();

  delay(200);
}