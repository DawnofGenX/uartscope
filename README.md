# UARTScope Pro

> **The Wireshark of Microcontrollers** — open-source embedded telemetry, debugging, and protocol analysis

[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)

UARTScope Pro is an open-source platform for monitoring, debugging, and analyzing embedded device communications. Think Wireshark, but purpose-built for microcontrollers (ESP32, STM32, Arduino, Raspberry Pi Pico, nRF52, etc.).

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔌 **Serial Monitoring** | Real-time UART communication with auto baudrate detection and device identification |
| 📊 **Live Telemetry** | Automatic KEY:VALUE and JSON parsing with real-time charts |
| 📝 **Session Recording** | Record, replay, and export debugging sessions (JSON/CSV) |
| 🔔 **Alert Engine** | Rule-based alerts with cooldown, acknowledgment, and WebSocket push notifications |
| 🧩 **Protocol Decoders** | Plugin architecture: UART, I2C, SPI, CAN Bus, Modbus RTU, DBC databases |
| 📡 **MQTT Integration** | Multi-broker connections, pub/sub, message history, WebSocket bridge |
| ⚡ **Performance Analytics** | Packet rate, throughput, latency histogram, error tracking |
| 🧪 **Automated Diff Testing** | Golden session comparison for CI pipelines |
| 🛒 **Plugin Marketplace** | Browse and install community protocol decoders |
| 📦 **Session Sharing** | Export and share sessions as `.uartscope` bundles |
| 💻 **Desktop App** | Pure Python GUI (NiceGUI) — no Node.js or browser required |

## 🚀 Quick Start

### Option A: Desktop App (Recommended)

```bash
git clone https://github.com/DawnofGenX/uartscope.git
cd uartscope

# Backend
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

In a second terminal:

```bash
cd uartscope-pro
source backend/venv/bin/activate
python desktop_app.py
```

Open **http://localhost:3000**

### Option B: Docker Compose

```bash
docker compose up -d
```

Services:
- Backend API: http://localhost:8080
- Desktop App: http://localhost:3000

### Option C: Development Mode (React frontend)

```bash
# Backend
cd backend && source venv/bin/activate && python -m uvicorn app.main:app --reload

# Frontend
cd frontend && npm install && npm run dev
```

## 📖 Usage

### 1. Connect a Device

Plug in your serial device (ESP32, Arduino, Pico, etc.) and UARTScope will auto-detect it. Or register manually:

```bash
curl -X POST http://localhost:8080/api/devices/ \
  -H "Content-Type: application/json" \
  -d '{"name":"My ESP32","/dev/ttyUSB0","baudrate":115200}'
```

### 2. Start Streaming

Click **Start** on a device to begin receiving telemetry. The terminal view shows raw serial output, charts update in real-time, and metrics are extracted automatically.

### 3. Set Up Alerts

Create rules like "Alert me when TEMP > 40" or "Alert when VOLTAGE changes by more than 0.5V". Rules support conditions: `gt`, `lt`, `eq`, `range`, `change`.

### 4. Record Sessions

Sessions are automatically created when streaming starts. Replay them later with timeline view and export to JSON/CSV.

### 5. Decode Protocols

Use the **Decoder** tab to manually decode I2C, SPI, CAN, or Modbus frames from hex bytes.

### 6. Connect MQTT

Add broker profiles in the **MQTT** tab to stream data from remote IoT devices. Messages are bridged to WebSocket clients and can trigger alerts.

## 🏗️ Architecture

```
uartscope-pro/
├── backend/              # FastAPI + asyncio
│   ├── app/
│   │   ├── core/
│   │   │   ├── device_manager.py      # Auto-detect, connect, heartbeat, auto-reconnect
│   │   │   ├── telemetry_engine.py    # Parse KEY:VALUE, JSON, classify messages
│   │   │   ├── alert_engine.py        # Rule-based alerts with cooldown + ack
│   │   │   ├── performance_tracker.py # PPS, throughput, latency, errors
│   │   │   ├── mqtt_client.py         # Multi-broker MQTT with pub/sub
│   │   │   ├── protocol_decoder.py    # Plugin framework (I2C, SPI, CAN, Modbus)
│   │   │   ├── session_recorder.py    # Record/replay debugging sessions
│   │   │   └── websocket_hub.py       # Real-time broadcast with device subscriptions
│   │   ├── api/routes/                 # REST + WebSocket endpoints
│   │   ├── models/                    # Pydantic schemas
│   │   └── plugins/                   # Protocol decoder plugins
│   └── tests/                         # pytest + pytest-asyncio
├── desktop_app.py         # NiceGUI desktop application (pure Python)
├── scripts/
│   └── simulate_device.py # Virtual device simulator for testing
├── docker-compose.yml
├── pyproject.toml
└── README.md
```

## 🔌 Supported Protocols

| Protocol | Decode | Encode | Notes |
|----------|--------|--------|-------|
| UART Text | ✅ | ✅ | KEY:VALUE, JSON, log levels |
| I2C | ✅ | ✅ | 7/10-bit addr, SSD1306 demo |
| SPI | ✅ | ✅ | CPOL/CPHA modes |
| CAN Bus | ✅ | ✅ | 11/29-bit ID, RTR |
| Modbus RTU | ✅ | ✅ | Function codes 01-0F |

## 📡 API Reference

### Core Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check + device stats |
| GET | `/api/devices/detect` | Auto-detect serial ports |
| POST | `/api/devices/` | Register device |
| POST | `/api/devices/{id}/start` | Start streaming |
| POST | `/api/devices/{id}/stop` | Stop streaming |
| GET | `/api/devices/{id}/stats` | Device statistics |

### Telemetry & Sessions

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/telemetry/history/{id}` | Metric history |
| GET | `/api/telemetry/latest/{id}` | Latest values |
| GET | `/api/sessions/` | List sessions |
| POST | `/api/sessions/{id}/rename` | Rename session |

### Alerts

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/alerts/rules` | Create alert rule |
| DELETE | `/api/alerts/rules/{id}` | Delete rule |
| POST | `/api/alerts/{id}/ack` | Acknowledge alert |
| GET | `/api/alerts/stats` | Alert statistics |

### MQTT

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/mqtt/profiles` | List connections |
| POST | `/api/mqtt/profiles` | Add broker |
| POST | `/api/mqtt/profiles/{id}/connect` | Connect |
| POST | `/api/mqtt/profiles/{id}/publish` | Publish message |
| GET | `/api/mqtt/messages` | Message history |

### Performance

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/performance/summary` | Performance summary |
| GET | `/api/performance/snapshot` | Real-time snapshot |
| GET | `/api/performance/device/{id}` | Per-device detail |

### WebSocket

| Path | Description |
|------|-------------|
| `/api/ws/telemetry` | Real-time telemetry, serial data, alerts, MQTT bridge |

## 🧪 Testing

```bash
cd backend
source venv/bin/activate

# Run tests
pytest tests/ -v

# Simulate a device (virtual serial port)
python scripts/simulate_device.py --virtual
```

## 🛠️ Configuration

All settings are environment variables (prefixed with `UARTSCOPE_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `UARTSCOPE_DATABASE_URL` | `sqlite+aiosqlite:///./uartscope.db` | Database URL |
| `UARTSCOPE_MQTT_ENABLED` | `false` | Auto-connect to MQTT |
| `UARTSCOPE_MQTT_BROKER` | `localhost` | MQTT broker host |
| `UARTSCOPE_MQTT_PORT` | `1883` | MQTT broker port |
| `UARTSCOPE_DEBUG` | `false` | Debug logging |

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'feat: amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

## 🙏 Acknowledgments

- [FastAPI](https://fastapi.tiangolo.com) — async web framework
- [NiceGUI](https://nicegui.io) — pure Python GUI framework
- [aiomqtt](https://github.com/sbtinstruments/aiomqtt) — async MQTT client
- [pyserial](https://github.com/pyserial/pyserial) — serial communication
