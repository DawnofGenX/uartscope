# Changelog

All notable changes to UARTScope Pro are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.1.0] — 2026-10-05

### Added

- **A FAQ.** `docs/FAQ.md` covers finding a serial port, 8E1 sensors, which
  framing a protocol needs, why a plugin install was refused, why a metric has
  no unit, and the bugs this project has already shipped once. Every falsifiable
  claim in it is checked against the code.

- **Real-hardware acceptance tests.** `hardware/esp32_acceptance/` contains
  firmware that emits the exact byte patterns this project has mishandled — a
  frame containing `0x0A`, a gap-delimited frame with no terminator, and a
  frame containing invalid UTF-8 — with CRCs computed on-device, so no sensors
  are needed. `e2e_check.py` boots the backend on a real port, registers a
  device through the same endpoints the UI uses, and reads telemetry, sessions,
  exports, alerts, performance and the websocket back out: 19 checks.

- **CI now fails if the serial tests stop running.** The hardware tests use a
  pty, which is a real character device needing no adapter and no root, so they
  execute on a hosted runner. Without a gate, a skip guard added for "no serial
  hardware in CI" would turn the only tests covering the reader into silent
  no-ops — which is how the bugs above reached a fully green suite.

- **A real plugin marketplace.** The Marketplace screen rendered a hardcoded
  list of six plugins with invented download counts, and its Install button
  slept for a second, set a flag, and asked you to restart. Nothing was
  downloaded and no decoder was ever registered.

  It now installs real decoders. `registry/registry.json` is a manifest of
  installable plugins and ships three: LIN (LDF), J1939 and DALI. Installing
  validates the module, requires a real `ProtocolDecoder` subclass, refuses any
  id that would shadow a built-in, copies the file into the install directory,
  records the install, and registers the decoder with the live decoder table so
  it is usable immediately. Uninstall reverses all of it. Installs survive a
  restart.

  The API mirrors the UI: `GET /api/plugins`, `POST /api/plugins/{id}/install`,
  `POST /api/plugins/{id}/uninstall`, `GET /api/plugins/installed`,
  `POST /api/plugins/{id}/decode`, and `POST /api/plugins/refresh`.

  **Installing a plugin executes third-party Python in the app process with no
  sandbox.** Validation keeps the plugin honest about shape, not about intent —
  a valid plugin can still do whatever its code does. This is stated on the
  Marketplace screen rather than buried.

- **A registry you can host yourself.** `UARTSCOPE_PLUGIN_REGISTRY` accepts a
  URL or a path. The bundled manifest is the default, so the marketplace works
  with no configuration.

- **`GET /api/export/session/{id}/bundle`.** The `.uartscope` shareable capture
  format could only be produced by the desktop UI, which assembled the zip in
  memory from page state. A script or a second client had no way to export one.
  The zip assembly now lives in `session_bundle.py` and both the UI and the API
  call it, so the format is defined once.

  Reading a bundle back recovers numeric types that the CSV round trip would
  otherwise flatten to strings, and CSV values are quoted properly, so a metric
  containing a comma no longer splits into two columns.

### Changed

- **Framing is now chosen per device protocol.** Text protocols keep
  newline framing; `modbus_rtu`, `can`, `can_dbc`, `i2c` and `spi` are framed
  on the 3.5-character silent gap, derived from the device's own line settings
  so a 9600 8E1 sensor frames at roughly 4 ms rather than at a hardcoded
  second. A single global rule does not work: gap framing merged a burst of
  text lines into one delivery, which would have broken every text device.

  **This makes the device protocol load-bearing.** A board speaking Modbus
  must be configured as `modbus_rtu`; configured as `serial` it stays
  line-framed and frames are split. There is no reliable automatic detection
  at the framing layer, so it is an explicit choice.

- **Devices can express a real RS-485 configuration.** `parity` (`N`/`E`/`O`/
  `M`/`S`) and `stopbits` (`1`/`1.5`/`2`) are settable per device and validated
  against pyserial's real values. Previously every port opened 8N1, so a Modbus
  sensor at 9600 8E1 could not be expressed at all and every frame failed CRC.
  They are stored in the existing `metadata_json` column rather than as new
  columns, because the project calls `create_all` with no migration framework
  and a new column would break existing databases. Defaults are unchanged, so
  existing devices still open 8N1.

- **Performance and MQTT rebuilt to v2.** These were the last two screens on
  the v1 treatment, and both were quietly broken in the same way: each rebuilt
  its entire UI every 3 seconds without clearing the container, so the page
  grew without bound for as long as it was open. Both now clear and explicitly
  re-enter their container, matching every other screen, and a contract test
  guards that.

  Performance v1 never called `get_history()`, so the tracker kept a full hour
  of packet-rate, throughput and latency snapshots that nothing displayed. v2
  surfaces it: stat tiles carry a sparkline and a trend, a selectable
  1m/5m/15m/all window plots the real history, the latency distribution gains
  p50/p95/p99 markers, and per-device rows carry sparklines. The window caption
  states how many samples are on screen and warns when density has flattened
  the block ramp.

  MQTT keeps every capability it had — broker management, subscriptions,
  publish, history — with subscriptions grouped by the connection carrying them
  and history filterable by connection and topic, pausable, with a
  jump-to-newest follow mode. Nothing that worked was removed.

  `V2_PENDING` is now empty, so no screen carries a "Not yet v2" marker.

### Fixed

- **The Terminal screen could not receive a single byte from real hardware.**
  `SerialReader` calls the data callback with three arguments; the Terminal
  screen's callback accepted one. The `TypeError` was raised on the first real
  line and swallowed by the read loop's broad handler, so the screen only ever
  worked on seeded demo data.

- **A crashed reader bricked its device permanently.** `_read_tasks` was only
  ever popped by `stop_device()`, so once a reader task died every later start
  was a silent no-op that only logged a warning — and the heartbeat's
  auto-reconnect calls `connect()`, never `start_device()`, so it could not
  clear it. Unplug a board once and it stayed dead until restart.
  `start_device` now takes over a dead task and logs at ERROR with the device
  name and port.

- **Binary protocols could not decode a single real frame.** The reader decoded
  with `errors="replace"` before anything downstream saw the bytes, so any byte
  outside UTF-8 became U+FFFD. A Modbus RTU response containing `0xFF 0x9C`
  reached the decoder as two replacement characters and produced
  plausible-looking but wrong data — and still passed a CRC check. Lines are
  now `SerialData`, a `str` subclass carrying `raw_bytes` and `decode_error`,
  so existing consumers are unchanged and decoders get exact bytes.

- **Frames containing `0x0A` were split in two.** `readline()` terminates on
  `0x0A`/`0x0D`, and a Modbus payload can legally contain either — a register
  value of 10 is `0x000A`. Measured: a frame whose value was `0x000A` arrived
  as two chunks, so the decoder received a truncated frame plus trailing CRC. A
  real RS-485 master also sends no terminator at all, only a 3.5-character
  pause, so newline framing could not deliver a Modbus response correctly even
  when the payload held no newline byte.

- **Alerts never fired for a device connected over serial.** `app/main.py`
  called `alert_engine.evaluate()` in exactly one place — the MQTT callback —
  so the serial path broadcast metrics and recorded packets while no rule was
  ever checked. A rule created through the REST API looked correctly
  configured and reported `trigger_count: 0` forever. Session metrics had the
  same gap: `record_metric()` was called by the desktop app but not the API, so
  every API-recorded session had an empty metric list and the session Metrics
  tab was blank. Both now use the metrics the line actually produced, with
  their real units.

- **`POST /api/protocols/encode` returned 500 for an integer `can_id`.**
  `CANDecoder.encode` parsed the id with a base of 16 unconditionally, so
  `{"can_id": 256}` raised `TypeError: int() can't convert non-string with
  explicit base` while `"0x100"` worked — the more natural JSON input was the
  one that failed. `DBCDecoder.encode` had a related guard that protected only
  the string path and let the same unguarded call through for an int. Both
  accept hex strings, decimal strings and ints now. This is the "generic CAN
  encode returns HTTP 500" loose end carried since v2.0.1.

- **Plugin installs were lost on restart.** `PluginRegistry` wrote its state
  file but never read it, so a new instance reported nothing installed even
  though the record was on disk. The Marketplace screen showed an empty
  Installed list after a restart. State is now loaded on construction;
  registering the decoders still happens only at startup, where a missing or
  invalid file can be handled.

### Removed

- **The plugin-install interlock did not exist.** The config comment stated
  that installing a plugin "stays off unless the operator turns it on
  deliberately" — but the default was `True`, **no code read the setting**, and
  the install route had no gate at all. Installing a plugin runs third-party
  Python in the application process via `exec()` with no sandbox, so remote
  code execution was on by default while the configuration looked like the
  control for it.

  The default is now `False` and the gate is enforced inside
  `PluginRegistry.install()` — the point every caller shares. Gating only the
  HTTP route, which is what the first fix did, left the shipped PyInstaller
  Windows executable able to install plugins with the setting off: the desktop
  app calls `install()` directly and never touches HTTP. `test_plugin_install_gate.py`
  pins both paths, including that a refused install writes nothing to disk.

- **Four config keys that never did anything.** `host`, `port`,
  `telemetry_buffer_size` and `alert_check_interval` were declared with
  explanatory comments and had zero readers anywhere in the codebase. Setting
  them changed nothing. They are deleted rather than left to look functional,
  because a comment describing behaviour the code does not implement is itself
  the defect. `default_baudrate` is still unwired (`DeviceCreate` hardcodes
  `115200`) and now says so plainly instead of implying otherwise.

- **My own environment.** 23 files carried a `.venv-v2` interpreter path in
  their `Run:` docstrings that only ever existed on one machine, and the README
  advertised WSL-specific instructions. Both are gone; the FAQ covers Linux,
  macOS and Windows instead.

- **Invented download counts.** The catalog served no telemetry, so the numbers
  were fiction. A manifest entry may not carry a `downloads` field, and a test
  enforces it.

- **The long-form documentation tree.** `docs/` loses its twelve markdown files:
  the tutorial, five how-to guides, three reference documents, two
  explanations, and the screenshot notes. The guides were written for v2.0.1 and
  verified against that release; they are recoverable from the `v2.0.1` tag if
  they are wanted back. The eleven screenshots in `docs/images/` are kept, and
  the README's link to them still works.

  The README pointed at nine of these files. Rather than leave every one a 404,
  its Documentation section now says what remains in the README and where the
  rest can be found. `CHANGELOG.md`, `README.md` and `backend/README.md` are
  unaffected.

## [2.0.1] — 2026-09-28

A quiet device no longer kills its own stream, and four other notifications that
had been failing silently are now visible. The README is replaced and a
documentation tree is added.

### Fixed

- **A device with nothing to say killed the Terminal stream.** The read loop
  used a 1-second timeout inside a `try` whose handler caught `Exception`, and
  `asyncio.TimeoutError` is a subclass of `Exception`. A board that reported
  every few seconds — or only spoke when asked — tripped that arm, the
  `while True` never iterated again, and the stream was gone. The handler then
  called `ui.notify()` from a bare `asyncio` task, where NiceGUI has no slot, so
  that raised `RuntimeError` too and the message never reached the browser. A
  healthy board that merely had nothing to report looked exactly like a dead
  one, with no message at all. An expired read timeout is now normal, so the arm
  that reports failures only handles real faults.
- **Every alert notification was being dropped.** `check_new_alerts()` on the
  Alerts screen and `on_alert()` on the main page both called `ui.notify()`
  from a context with no NiceGUI slot, so each raised `RuntimeError` before the
  message was sent. An alert that fires silently is the one outcome that screen
  exists to prevent, and it was the guaranteed one. Both now push to the client
  captured at page-build time. Note that the alert *engine* was always correct;
  only the display path was broken.
- **A failed charts refresh would have frozen the screen silently.** The same
  slot problem: the loop's error handler could not raise a visible error, so a
  dead refresh loop would leave a chart that looks live. The code's own comment
  called this worse than a visible error, and it was the likelier outcome.
- **Sending a command gave no confirmation.** The send path reported success,
  failure, and "device not connected" through the same broken mechanism, so a
  command that never left the box looked identical to one that did.

Event-handler notifications were not affected: those run with a slot and were
never broken.

- **The product could not be imported after a documented install.** `nicegui`
  was absent from every Python manifest — `backend/requirements.txt` and
  `backend/pyproject.toml` both. The desktop app (`desktop_app.py`) is built on
  NiceGUI, so `pip install -r requirements.txt` followed by `import desktop_app`
  failed with `ModuleNotFoundError: No module named 'nicegui'`, and the CI
  screen-build step failed on every Python version. No other declared
  dependency pulls NiceGUI in transitively, so the gap could not be papered
  over: `Dockerfile.desktop` happened to work only because it installed the
  package separately, and the Windows release job likewise had a bare
  `pip install nicegui` alongside the manifest. It is now a declared
  dependency, and the redundant line in the release workflow has been dropped.
- **The API test suite only passed because of a stray local database.** Tests
  that hit a route which touches the database passed on a developer's machine
  because a real `uartscope.db` was sitting in the working tree. In a clean
  checkout they failed. The suite no longer depends on ambient state.
- **The screen-build CI step probed a port with nothing listening.** It checked
  a port before the app had bound it, so it could not detect a genuinely broken
  screen build.

### Added

- **Documentation.** The README is replaced, and `docs/` adds a documentation
  tree: a tutorial, five how-to guides, API / configuration / protocol
  references, and architecture and screen explanations, with screenshots of the
  running app.

  Every claim in the old README was checked against the code and against a
  running instance, and several were wrong. Corrected here, because a user
  following them would have been stuck: the quick start told you to run uvicorn
  and then the desktop app in a second terminal, but `desktop_app.py` imports
  the backend modules in-process and never calls the backend over HTTP, so
  uvicorn is not part of local use at all; `/api/devices/{id}/start` and `/stop`
  do not exist (the real verbs are `/connect` and `/disconnect`, and the
  documented `/stop` belongs to a different router that matched the path by
  accident); `/api/devices/{id}/stats` does not exist either; the documented
  register example was malformed JSON; baudrate auto-detection is claimed as a
  feature but no such code exists; sessions are not created automatically when
  streaming starts; the plugin marketplace is a hardcoded list, not a registry;
  and the architecture tree described a `storage/` package that does not exist.

  The README now also states which features are mocks and which screens are
  still pre-v2, so they are not discovered by surprise.

### Verification

- 75 tests pass, plus 4 new for the stream fix — 79 total. The new tests were
  each confirmed to fail against the code they guard against.
- All 13 screen builds serve cleanly over real HTTP.
- Ruff clean; all three static gates pass.
- Every endpoint in the API reference was exercised against a live instance.

## [2.0.0] — 2026-09-27

The desktop app (NiceGUI) is redesigned end to end. The v2 pass found and fixed
eight defects in which the product displayed something, looked configured, and
was doing nothing. Those fixes matter more than the visual work, so they are
listed first.

### Fixed

These are all silent-wrong-value bugs: nothing raised, nothing looked broken,
and the screen showed a result.

- **No alert rule a user could create had ever fired.** The condition picker
  offers `>`, `<`, `>=`, `<=` and `==`; `AlertRule.check()` compared only
  against the internal names `gt`, `lt`, `gte`, `lte` and `eq`. Every symbol
  fell through every branch and returned `False`. A rule appeared in the list,
  looked configured, and did nothing — and silence is indistinguishable from
  "all well". An unrecognised condition is now logged rather than ignored.
- **Every recorded session had an empty metric list.** `record_metric()` had no
  caller anywhere in the product. The session format has a `metrics` list and
  the Sessions screen has a Metrics tab; both were permanently empty. The live
  stream path now records parsed metrics, and evaluates alerts against the
  metrics each line actually produced, with their real units.
- **Every session export downloaded as `session_unknown.json`/`.csv`/
  `.uartscope`.** The UI read `session['session_id']`; the recorder writes
  `id`. Not one export in the product was ever correctly named.
- **The golden-session diff always reported PASS.** `mark_as_golden()` and
  `run_diff()` both read `session['metrics_latest']`, a key no code path
  writes, so the baseline was always empty and the comparison loop iterated
  nothing. Comparing against nothing is now a failure, and metrics absent from
  the baseline are surfaced rather than ignored.
- **Plain text was decoded as I²C.** `UARTTextDecoder.can_decode()` required a
  trailing newline, so `hello` and `TEMP:23.4` scored `0.0` while
  `I2CDecoder` scored `0.6` on length alone and won. An ASCII string was
  reported as an I²C transaction with a device address and a read/write
  direction the bytes do not contain.
- **`KEY:VALUE` metrics carried no unit.** The JSON path inferred units; the
  `KEY:VALUE` path captured an optional inline unit and stopped. `TEMP:23.4`
  produced `unit=None`, so unit-aware UI had nothing to be aware of.
- **A clean virtualenv could not boot the backend.** `requirements.txt` pinned
  plain `sqlalchemy`, which omits `greenlet`; the async engine raised on import.
  Now `sqlalchemy[asyncio]`.
- **Six screens could not be opened at all.** Terminal, Charts, Decoder,
  Alerts, Session Detail and MQTT each raised `UnboundLocalError` during render,
  because a button was wired to a handler defined further down the same
  function. Nine instances, all now resolved.

### Added

- **A design token layer** (`uartscope_theme.py`). Every colour, size, weight
  and duration in the desktop UI resolves through one module. The stylesheet is
  generated from it, so the palette can change in exactly one place. All 22
  documented contrast pairs are asserted on every CI run, and a recorded ratio
  that drifts from the computed one fails the build.
- **A labelled 200 px sidebar.** v1 rendered nine bare glyphs with no text
  label, no tooltip and no accessible name — the labels existed in the nav tuple
  and were never passed to the button.
- **A working session replay.** The detail screen opened on two tabs reading
  "coming soon". The data was never missing: `load_session()` read the full
  history from disk the whole time, and nothing called it. v2 loads it and gives
  a transport, a scrubber, speed control, and a sliding window over the packets.
- **Live protocol decoding.** The Decoder was a calculator — a hex box, a
  dropdown, a button — in a product whose reason to exist is a live stream. It
  now decodes incoming lines in place, shows the raw bytes beside the decoded
  fields, and reports detection confidence.
- **Static checks** (`check_handler_order.py`, `check_dict_keys.py`). The
  checks exist because the bugs above are invisible to pytest: a screen that
  raises during render simply does not appear. Both are wired into CI, and both
  are verified to fail when their target defect is reintroduced.
- **An HTTP smoke test** (`smoke_pages.py`) that boots the real app and requests
  every screen, with and without a device bound. Now part of CI.

### Changed

- **Charts group series by unit.** The v1 dashboard plotted independently
  scaled values on one shared Y axis, so `°C` and `dBm` were drawn against the
  same scale. Each unit now gets its own axis. Unit symbols are rendered
  verbatim and never uppercased — `dBm` is not a word.
- **Alerts triage.** Acknowledging an alert used to append a second copy of the
  entire screen, because `refresh_alerts()` built into the ambient context
  without clearing it. The queue is now filterable by severity, leads with
  unacknowledged work, and rules can be silenced non-destructively —
  `AlertRule.enabled` and `trigger_count` were never surfaced, so the only verb
  offered for a noisy rule was the destructive one.
- **Terminal follow-mode.** New output forced the viewport to the tail even when
  the reader had scrolled away. Following now suspends, reports "N new lines",
  and resumes only on return to the tail.
- **Device rows are dense and actionable.** v1's empty state was "No devices
  connected", with no way forward. It now scans for ports, lists what it found,
  and offers one-click add.
- **`process_line()` returns its `ParsedMessage`.** It previously returned
  `None`, so any caller wanting the metrics from the line it had just processed
  had to re-parse it.

### Retained from v1

These screens keep their v1 visual treatment in this release. They function and
are reachable, but they have not been through the v2 design pass:

- **Performance**
- **MQTT**
- **Marketplace**

They are listed in `V2_PENDING` in `desktop_app.py` so the navigation is honest
about what has been redesigned.

### Verification

- 70 pre-existing tests pass; 15 new assertions added, each verified to fail
  against the code it guards against.
- All 13 screen builds serve cleanly over real HTTP.
- No tracebacks in the application log across a full pass of every screen.
- The React frontend in `frontend/` is unchanged and out of scope for v2.

[2.0.1]: https://github.com/DawnofGenX/uartscope/releases/tag/v2.0.1
[2.0.0]: https://github.com/DawnofGenX/uartscope/releases/tag/v2.0.0
[Unreleased]: https://github.com/DawnofGenX/uartscope/compare/v2.1.0...HEAD
[2.1.0]: https://github.com/DawnofGenX/uartscope/compare/v2.0.1...v2.1.0
