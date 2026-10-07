// hardware/examples/uart/uart_echo.ino
// Echoes back everything received on UART1.
// Demonstrates basic UART communication with UARTScope.

HardwareSerial MySerial(1);

void setup() {
  Serial.begin(115200);
  MySerial.begin(115200, SERIAL_8N1, 16, 17);  // RX=16, TX=17
  Serial.println("UART Echo ready");
}

void loop() {
  if (MySerial.available()) {
    char c = MySerial.read();
    MySerial.write(c);
  }
}
