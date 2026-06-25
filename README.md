# UARTScope Pro

> **The Wireshark of Microcontrollers**

Open-source embedded telemetry and debugging platform for ESP32, STM32, Arduino, Raspberry Pi Pico, and other embedded devices.

## Features

- 🔌 **Serial Monitoring** — Real-time UART communication with auto device detection
- 📊 **Live Charts** — Automatic telemetry visualization with zero configuration
- 📝 **Logging & Export** — CSV/JSON export, session recording
- 🔔 **Alert Engine** — Rule-based notifications (temperature, voltage, etc.)
- 🔍 **Packet Inspector** — Wireshark-style protocol analysis
- 🧩 **Protocol Decoders** — Plugin architecture for UART, SPI, I2C, CAN, Modbus, and custom protocols
- 📡 **MQTT Integration** — Remote IoT device streaming
- 💾 **Session Recording** — Record and replay debugging sessions

## Quick Start

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python -m uvicorn app.main:app --host 0.0.0.0 --port 8080
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000

### Simulate a Device

```bash
python scripts/simulate_device.py --virtual
```

## Architecture

```
uartscope/
├── backend/          # FastAPI + asyncio + pyserial
│   ├── app/
│   │   ├── core/     # Device Manager, Telemetry Engine, Alert Engine, Protocol Decoder
│   │   ├── api/      # REST endpoints + WebSocket
│   │   ├── models/   # Pydantic schemas
│   │   ├── plugins/  # Protocol decoder plugins
│   │   └── storage/  # SQLite/PostgreSQL backends
│   └── tests/
├── frontend/         # React + TypeScript + Vite + Recharts
│   └── src/
│       ├── components/  # Dashboard, Terminal, Charts, Alerts
│       ├── api/         # REST + WebSocket clients
│       └── hooks/       # React hooks for real-time data
├── docs/
└── scripts/          # Device simulator, test tools
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | /api/devices/detect | Auto-detect serial ports |
| POST | /api/devices/ | Register a device |
| POST | /api/devices/{id}/start | Start streaming |
| POST | /api/devices/{id}/stop | Stop streaming |
| GET | /api/telemetry/history/{id} | Get telemetry history |
| GET | /api/telemetry/latest/{id} | Get latest values |
| POST | /api/sessions/ | Create recording session |
| POST | /api/alerts/rules | Create alert rule |
| GET | /api/export/csv/{id} | Export CSV |
| GET | /api/export/json/{id} | Export JSON |
| WS | /api/ws/telemetry | Real-time telemetry stream |

## License

MIT
