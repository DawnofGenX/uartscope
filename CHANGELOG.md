# Changelog

All notable changes to UARTScope Pro are recorded here.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Removed

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
[Unreleased]: https://github.com/DawnofGenX/uartscope/compare/v2.0.1...HEAD
