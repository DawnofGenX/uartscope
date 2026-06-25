#!/usr/bin/env python3
"""Simulate an embedded device sending telemetry over serial.

Usage: python simulate_device.py [port] [baudrate]
Default: /dev/ttyUSB0 115200

Creates a virtual serial port pair if run with --virtual flag.
"""
import asyncio
import random
import sys
import time
import json

try:
    import serial
except ImportError:
    print("Install pyserial: pip install pyserial")
    sys.exit(1)


async def simulate(port: str, baudrate: int, virtual: bool = False):
    """Send simulated telemetry data."""
    if virtual:
        # Use a pseudo-terminal pair for testing
        import pty
        import os
        master, slave = pty.openpty()
        slave_path = os.ttyname(slave)
        print(f"Virtual serial port: {slave_path}")
        print(f"Connect UARTScope to: {slave_path}")
        fd = master
    else:
        ser = serial.Serial(port, baudrate, timeout=1)
        print(f"Opened {port} @ {baudrate}")

    t = 0
    while True:
        t += 1
        temp = 22 + random.gauss(0, 2) + (5 * (t % 100 == 0))  # Occasional spike
        voltage = 3.3 + random.gauss(0, 0.1)
        humidity = 55 + random.gauss(0, 5)
        pressure = 1013 + random.gauss(0, 2)

        # Send in KEY:VALUE format
        line = f"TEMP:{temp:.1f},VOLTAGE:{voltage:.2f},HUMIDITY:{humidity:.0f},PRESSURE:{pressure:.1f}\n"

        if virtual:
            os.write(fd, line.encode())
        else:
            ser.write(line.encode())

        # Also send JSON occasionally
        if t % 10 == 0:
            json_data = json.dumps({
                "temp": round(temp, 1),
                "voltage": round(voltage, 2),
                "humidity": round(humidity),
                "uptime": t,
                "status": "ok"
            })
            json_line = json_data + "\n"
            if virtual:
                os.write(fd, json_line.encode())
            else:
                ser.write(json_line.encode())

        # Occasionally send log messages
        if t % 25 == 0:
            log = f"[INFO] Sensor reading complete. Uptime: {t}s\n"
            if virtual:
                os.write(fd, log.encode())
            else:
                ser.write(log.encode())

        await asyncio.sleep(1)


if __name__ == "__main__":
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyUSB0"
    baudrate = int(sys.argv[2]) if len(sys.argv) > 2 else 115200
    virtual = "--virtual" in sys.argv

    print("UARTScope Pro - Device Simulator")
    print("=" * 40)
    print(f"Simulating ESP32-style telemetry")
    print(f"Metrics: TEMP, VOLTAGE, HUMIDITY, PRESSURE")
    print(f"Press Ctrl+C to stop")
    print("=" * 40)

    try:
        asyncio.run(simulate(port, baudrate, virtual))
    except KeyboardInterrupt:
        print("\nStopped.")
