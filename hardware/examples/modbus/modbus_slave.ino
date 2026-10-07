// hardware/examples/modbus/modbus_slave.ino
// Responds to Modbus RTU read-holding-registers requests.
// Demonstrates Modbus RTU communication with UARTScope.

HardwareSerial ModbusSerial(1);

uint16_t modbus_crc16(uint8_t *data, uint8_t len) {
  uint16_t crc = 0xFFFF;
  for (uint8_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (uint8_t b = 0; b < 8; b++) {
      if (crc & 1) crc = (crc >> 1) ^ 0xA001;
      else crc >>= 1;
    }
  }
  return crc;
}

void setup() {
  Serial.begin(115200);
  ModbusSerial.begin(115200, SERIAL_8N1, 16, 17);
  Serial.println("Modbus Slave ready (slave ID 1)");
}

void loop() {
  if (ModbusSerial.available() >= 8) {
    uint8_t req[8];
    ModbusSerial.readBytes(req, 8);

    if (req[0] == 0x01 && req[1] == 0x03) {
      uint16_t value = 0x000A;
      uint8_t resp[5];
      resp[0] = 0x01;
      resp[1] = 0x03;
      resp[2] = 0x02;
      resp[3] = (value >> 8) & 0xFF;
      resp[4] = value & 0xFF;
      uint16_t crc = modbus_crc16(resp, 5);
      ModbusSerial.write(resp, 5);
      ModbusSerial.write(crc & 0xFF);
      ModbusSerial.write(crc >> 8);
    }
  }
}
