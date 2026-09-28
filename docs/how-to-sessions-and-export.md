# How to record, replay, and export sessions

**Problem:** you want the capture itself as an artifact — to replay it after a
bug, hand it to a colleague, diff a firmware build against a known-good run, or
feed it to a script.

One fact first, because it surprises people: **sessions are not created
automatically when streaming starts.** Live monitoring does not write anything
to disk. You create a session when you want the data recorded. This keeps a
days-long monitoring run from silently filling your disk.

## 1. Create a session

In the UI: **Sessions → create**, give it a name. Over the API (verified):

```bash
curl -s -X POST http://127.0.0.1:8080/api/sessions/ \
  -H 'content-type: application/json' \
  -d '{"device_id": "demo-device", "name": "how-to test"}'
```

```json
{"id":"d1e5dc40-9ced-41ab-8b6c-e8a8cec19656","status":"recording"}
```

The response `id` is the session id every later call uses. It is optional to
pass `session_id` in the body; if you omit it a UUID is assigned. Optional
fields: `device_id`, `name`. List and inspect:

```bash
curl -s http://127.0.0.1:8080/api/sessions/            # all sessions
curl -s http://127.0.0.1:8080/api/sessions/<id>/info   # metadata + counters
curl -s http://127.0.0.1:8080/api/sessions/<id>/packets
curl -s http://127.0.0.1:8080/api/sessions/<id>/metrics
curl -s http://127.0.0.1:8080/api/sessions/<id>/events
```

Sessions land under `sessions_dir` (default `./sessions`) and stop being
writable past `max_session_size_mb` (default 500). See the
[configuration reference](reference-configuration.md).

## 2. Stop, rename

```bash
curl -s -X POST http://127.0.0.1:8080/api/sessions/<id>/stop
curl -s -X PUT  http://127.0.0.1:8080/api/sessions/<id>/rename \
  -H 'content-type: application/json' -d '{"name": "firmware-v1.2-good"}'
```

In the UI, stop/rename from the Sessions list row. A stopped session stays
readable forever; only `stop` makes its numbers final.

## 3. Read the four session tabs

Open a session in the UI (Sessions list → row; the detail page is also
reachable at `/smoke/session-detail` for the screenshot/CI tooling). The four
sub-tabs are different lenses on the same recording:

| Tab | Answers | Use it for |
|---|---|---|
| **Replay** | "What happened, in order?" | Scrubbing the capture sample by sample; reproducing a glitch timeline |
| **Metrics** | "How bad was it?" | Per-metric min / max / avg / count over the session window |
| **Export** | "Get it out." | JSON, CSV, and the `.uartscope` bundle (see next section) |
| **Diff** | "Is this run the same as the good one?" | Golden-baseline comparison — see below |

![Session detail with the Replay tab](images/09-session-detail.png)

## 4. Export

Three flavors, one choice:

| Format | Endpoint / button | Shape |
|---|---|---|
| CSV | `GET /api/export/csv/{device_id}` (live per-device) or the Export tab | One row per sample — spreadsheet / pandas |
| JSON | `GET /api/export/json/{device_id}`, or `GET /api/export/session/{session_id}` for a specific session | Structured records — scripts, CI artifacts |
| `.uartscope` bundle | **Export tab in the desktop app only** | Zip of `session.json` + `packets.json` + `metrics.csv` — everything, shareable |

### The `.uartscope` bundle is desktop-only

There is **no REST endpoint** for bundle export — it is implemented in
`desktop_app.py` (`_export_bundle`). A REST client cannot produce one. If you
need the equivalent headlessly, download the session's JSON and packets
endpoints and zip them yourself.

A bundle is self-contained — the recipient drops it in their sessions directory
or imports it, and gets your packets, metrics, and metadata in one file. This is
the "send me the capture" format.

## 5. Diff against a golden baseline (CI)

The **Diff** tab compares a session against a pinned *golden* session and shows
per-metric divergence. The workflow for firmware CI:

1. On a known-good firmware build, record a session, stop it, and pin it as the
   golden baseline (the Diff tab's golden controls; the empty state reads
   `No golden set` until one is pinned).
2. In CI, after flashing the build under test, run a fixed capture: create a
   session via `POST /api/sessions/`, exercise the board, `stop` it.
3. Compare the new session against the golden set in the Diff tab, or fetch
   both sessions' `/metrics` over REST and assert on deltas in your test code —
   that's the fully headless form:

```bash
curl -s http://127.0.0.1:8080/api/sessions/<new>/metrics
curl -s http://127.0.0.1:8080/api/sessions/<golden>/metrics
```

A failed assertion ("TEMP max moved +6.2 °C vs golden") points you straight at
the regression, and the two sessions travel with the CI artifact as evidence.

## Gotchas

- **Recording ≠ monitoring.** Data before `POST /api/sessions/` is gone; the
  recorder cannot backfill live history it wasn't subscribed to.
- **`/api/export/csv/{device_id}` is device-scoped, not session-scoped.** For
  session data use `/api/export/session/{session_id}`.
- **Stop before exporting for a final copy.** Exporting a running session gives
  you the bytes recorded so far, and the metrics tab keeps moving under you.
- **`sessions/` and `*.db` are gitignored** — recordings are local artifacts,
  never repo contents.

Related: [connect a board](how-to-connect-a-board.md) ·
[alerts](how-to-alerts.md) · [API reference](reference-api.md)
