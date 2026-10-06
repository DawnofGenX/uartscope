// hardware/examples/i2c/i2c_scanner.ino
// Scans the I2C bus and prints found addresses.
// Demonstrates I2C communication with UARTScope.

#include <Wire.h>

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);  // SDA=21, SCL=22
  Serial.println("I2C Scanner ready");
}

void loop() {
  Serial.println("Scanning...");
  for (byte addr = 1; addr < 127; addr++) {
    Wire.beginTransmission(addr);
    if (Wire.endTransmission() == 0) {
      Serial.printf("Found device at 0x%02X\n", addr);
    }
  }
  delay(5000);
}
