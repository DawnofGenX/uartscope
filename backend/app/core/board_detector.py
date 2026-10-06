"""USB board detection for ESP32 flashing.

Maps USB VID/PID pairs to arduino-cli FQBNs for common ESP32 boards.
Uses pyserial's list_ports to enumerate connected USB-serial devices.
"""
import serial.tools.list_ports

# USB VID/PID → board info mapping
# Covers common USB-serial bridge chips on ESP32 dev boards
BOARD_MAP = {
    # CP210x (ESP32 DevKit, many clones)
    (0x10C4, 0xEA60): {"fqbn": "esp32:esp32:esp32", "name": "ESP32 DevKit (CP210x)"},
    (0x10C4, 0xEA61): {"fqbn": "esp32:esp32:esp32", "name": "ESP32 DevKit (CP210x)"},
    # FT232 (some ESP32 boards)
    (0x0403, 0x6001): {"fqbn": "esp32:esp32:esp32", "name": "ESP32 DevKit (FT232)"},
    # CH340 (common on cheap ESP32 boards)
    (0x1A86, 0x7523): {"fqbn": "esp32:esp32:esp32", "name": "ESP32 DevKit (CH340)"},
    # ESP32-S3 native USB
    (0x303A, 0x0002): {"fqbn": "esp32:esp32:esp32s3", "name": "ESP32-S3 (native USB)"},
    # ESP32-C3 native USB
    (0x303A, 0x1001): {"fqbn": "esp32:esp32:esp32c3", "name": "ESP32-C3 (native USB)"},
}

# All supported FQBNs for the dropdown
SUPPORTED_BOARDS = [
    {"fqbn": "esp32:esp32:esp32", "name": "ESP32 (classic)"},
    {"fqbn": "esp32:esp32:esp32s3", "name": "ESP32-S3"},
    {"fqbn": "esp32:esp32:esp32c3", "name": "ESP32-C3"},
    {"fqbn": "esp32:esp32:esp32c6", "name": "ESP32-C6"},
]


def board_from_vid_pid(vid: int, pid: int) -> dict | None:
    """Look up board info from USB VID/PID.

    Returns dict with 'fqbn' and 'name', or None if unknown.
    """
    return BOARD_MAP.get((vid, pid))


def detect_board() -> list[dict]:
    """Detect connected USB-serial boards and return board info list.

    Each dict includes: port, vid, pid, serial_number, fqbn, name.
    Returns empty list if no known boards are connected.
    """
    boards = []
    for port in serial.tools.list_ports.comports():
        if port.vid and port.pid:
            info = board_from_vid_pid(port.vid, port.pid)
            if info:
                boards.append({
                    "port": port.device,
                    "vid": port.vid,
                    "pid": port.pid,
                    "serial_number": port.serial_number,
                    **info,
                })
    return boards
