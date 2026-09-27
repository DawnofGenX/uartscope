# Changelog

All notable changes to UARTScope Pro are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[2.0.0]: https://github.com/DawnofGenX/uartscope/releases/tag/v2.0.0
[Unreleased]: https://github.com/DawnofGenX/uartscope/compare/v2.0.0...HEAD
