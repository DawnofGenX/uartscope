// hardware/examples/can/can_sender.ino
// Sends a CAN frame every 2 seconds.
// Demonstrates CAN communication with UARTScope.
// NOTE: Requires a CAN transceiver (e.g., SN65HVD230) and a CAN library.

void setup() {
  Serial.begin(115200);
  Serial.println("CAN Sender ready (requires CAN transceiver)");
}

void loop() {
  // Placeholder — real CAN needs a transceiver and library
  Serial.println("CAN frame: ID=0x123 Data=01 02 03 04");
  delay(2000);
}
