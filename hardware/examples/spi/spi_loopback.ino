// hardware/examples/spi/spi_loopback.ino
// Sends test data over SPI and reads it back.
// Demonstrates SPI communication with UARTScope.

#include <SPI.h>

void setup() {
  Serial.begin(115200);
  SPI.begin(18, 19, 23, 5);  // SCK=18, MISO=19, MOSI=23, SS=5
  Serial.println("SPI Loopback ready");
}

void loop() {
  byte tx = 0xAB;
  byte rx = SPI.transfer(tx);
  Serial.printf("Sent 0x%02X, received 0x%02X\n", tx, rx);
  delay(1000);
}
