/*
 * UARTScope real-hardware acceptance firmware.
 *
 * No sensors needed: this board's only job is to emit the exact byte patterns
 * that broke UARTScope, so the fixes can be proven against real silicon
 * instead of a pty.
 *
 * It deliberately sends four things:
 *
 *  1. Plain text telemetry          -> proves the text path still works.
 *  2. A frame containing 0x0A       -> the bug that split every Modbus frame
 *                                      whose register value was 10.
 *  3. A gap-delimited frame, no \n  -> how a real RS-485 master frames.
 *  4. A frame containing 0xFF/0x9C  -> invalid UTF-8, which used to be
 *                                      destroyed by errors="replace".
 *
 * The two binary cases only make sense with the UARTScope device protocol set
 * to modbus_rtu, because framing is chosen per protocol: `serial` is
 * line-framed, binary protocols are gap-framed on a 3.5-character gap.
 *
 * Board-agnostic: uses only the HardwareSerial UART, no Arduino core version
 * assumptions beyond the two print functions every core provides.
 *
 * Expected output on 115200 8N1:
 *   READY
 *   then a repeating cycle, announced by a "CYCLE <n>" line every 10s.
 */

#include <Arduino.h>

HardwareSerial Port(1);   // UART1 -- the default UART0 is the USB/serial bridge

static const uint32_t BAUD     = 115200;
static const uint32_t GAP_MS   = 60;   // >> T3.5 at 115200 (~0.33 ms)

/* Modbus RTU read-holding-registers RESPONSE for slave 1:
 *   addr 01 | fn 03 | bytecount 02 | value XXXX | CRClo CRChi
 * CRCs are computed at runtime, so the frames are genuinely valid rather than
 * hand-copied constants that could be wrong and would then "prove" nothing. */
static void send_modbus_response(uint8_t slave, uint8_t fn, uint16_t value) {
  uint8_t f[5];
  f[0] = slave;
  f[1] = fn;
  f[2] = 0x02;                       // two data bytes
  f[3] = (uint8_t)(value >> 8);      // high byte
  f[4] = (uint8_t)(value & 0xFF);    // low byte

  // Modbus CRC-16 (polynomial 0xA001, init 0xFFFF)
  uint16_t crc = 0xFFFF;
  for (uint8_t i = 0; i < 5; i++) {
    crc ^= f[i];
    for (uint8_t b = 0; b < 8; b++) {
      if (crc & 0x0001) crc = (crc >> 1) ^ 0xA001;
      else              crc >>= 1;
    }
  }

  Port.write(f, 5);
  Port.write((uint8_t)(crc & 0xFF));
  Port.write((uint8_t)(crc >> 8));
  // Deliberately NO terminator: a real master just pauses (the silent gap).
  delay(GAP_MS);
}

void setup() {
  Serial.begin(BAUD);
  Port.begin(BAUD);

  Serial.println();
  Serial.println("READY");
  Serial.println("UARTScope acceptance firmware, no sensors attached.");
  Serial.println("text + 3 binary frame shapes, repeating every 10s.");
  Serial.flush();
}

void loop() {
  static uint32_t cycle = 0;
  static uint32_t next = 0;
  uint32_t now = millis();

  if (now < next) return;
  next = now + 10000;
  cycle++;

  Serial.print("CYCLE ");
  Serial.println(cycle);

  /* --- 1. plain text telemetry: the path that must never regress --- */
  Serial.print("TEMP:");
  Serial.print(20.0 + (cycle % 10), 1);
  Serial.print("C HUM:");
  Serial.print(40 + (cycle % 10));
  Serial.println('%');
  Serial.print("TEMP:23.4C HUM:45%");
  Serial.println();          // terminates immediately
  Serial.flush();
  delay(GAP_MS);

  /* --- 2. the 0x0A bug: register value 10 = 0x000A --- */
  send_modbus_response(0x01, 0x03, 0x000A);

  /* --- 3. gap-delimited, ordinary value --- */
  send_modbus_response(0x01, 0x03, 0x2A4C);   // 10828

  /* --- 4. invalid UTF-8 payload: 0xFF 0x9C, the replace-decoding case --- */
  send_modbus_response(0x02, 0x03, 0xFF9C);

  Serial.print("cycle ");
  Serial.print(cycle);
  Serial.println(" complete");
  Serial.flush();

  delay(2000);
}
