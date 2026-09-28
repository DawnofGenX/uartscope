# UARTScope documentation

UARTScope Pro is open-source embedded telemetry, debugging, and protocol
analysis: point it at a serial port and it parses, charts, alerts on, records,
and decodes what your board sends. The docs are split by what you need them for
(the Diátaxis scheme): learn by doing, solve a specific problem, look something
up, or understand how a piece works.

## Tutorial

Start here if you have never used UARTScope.

| Doc | For |
|---|---|
| [Your first capture](tutorial-first-capture.md) | A guided lesson: install the app, connect a board (real or the built-in simulator), watch telemetry arrive, and read a live chart. Assumes no prior experience; every step is numbered. |

## How-to guides

Problem-oriented recipes. Each one assumes you have UARTScope running and answers
one question.

| Doc | Question it answers |
|---|---|
| [Connect a board](how-to-connect-a-board.md) | "My board isn't showing up." Scanning, registering a port manually, ports held by another program, baudrate, and Linux/macOS/Windows permissions. |
| [Set up alerts](how-to-alerts.md) | "Tell me when a value crosses a limit." Creating rules, choosing a condition, cooldown, reading the history, acknowledging. |
| [Record and export sessions](how-to-sessions-and-export.md) | "Save this capture and do something with it later." Sessions, replay, metrics, export formats, `.uartscope` bundles, and golden-baseline diffing for CI. |
| [Decode protocols](how-to-decode-protocols.md) | "What are these bytes?" The Decoder screen, hex vs line input, the six built-in protocols, autodetect, and DBC files. |

## Reference

Information-oriented. Complete, accurate, not tutorialized.

| Doc | Contents |
|---|---|
| [API reference](reference-api.md) | Every REST and WebSocket endpoint, request/response shapes, and error behavior. |
| [Configuration reference](reference-configuration.md) | Every `UARTSCOPE_*` environment variable and its default. |
| [Protocol reference](reference-protocols.md) | The six built-in decoders: frame formats, function codes, encode/decode fields. |

## Explanation

Understanding-oriented. Read these when you want to know *why* something is the
way it is.

| Doc | Topic |
|---|---|
| [Architecture](explanation-architecture.md) | How `desktop_app.py`, the FastAPI backend, the session recorder, and the alert engine fit together — and why the desktop app doesn't talk HTTP to the backend. |
| [Screens](explanation-screens.md) | What each of the nine screens is for, which three are still on the pre-v2 UI, and how to reach the session detail view. |

## Screenshots

All screenshots live in [`images/`](images/) (2x, dark theme), captured against
a live app by [`docs/.shot.sh`](IMAGES.md). `01-devices-empty.png` shows a
genuine first-run empty state; the rest show the demo board bound with seeded
telemetry.
