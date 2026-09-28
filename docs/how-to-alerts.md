# How to set up alerts

**Problem:** you want UARTScope to tell you when a metric crosses a limit — a
temperature spike, a brown-out, a value that suddenly jumps — instead of
watching charts yourself.

A rule is: *metric + condition + threshold + cooldown*. The engine re-checks
rules every 2 seconds (`UARTSCOPE_ALERT_CHECK_INTERVAL`, default 2.0) against
whatever the connected devices last reported.

## Create a rule in the UI

1. Open **Alerts** and click **New alert rule**.
2. Fill in the fields:
   - **Name** — what you'll want to read in the history, e.g. `temp spike`.
   - **Metric** — the metric name as it appears in your stream (`TEMP`,
     `VOLTAGE`, …; it comes from the `KEY` in `KEY:VALUE` lines or the JSON
     field name).
   - **Condition** — a dropdown of the five symbol forms:
     `>` `<` `>=` `<=` `==`.
   - **Threshold** — the comparison value, e.g. `30`.
   - **Severity** and **Cooldown** (seconds) — see below.
3. Save. The rule appears in the list with its trigger count.

The UI sends the symbol; the alert engine aliases it internally — `>` → `gt`,
`<=` → `lte`, `==` and `=` → `eq`, `>=` → `gte`, `<` → `lt`. You never need to
type the internal names in the UI.

## Worked example: the simulator's temperature spike

Run the simulator (safe argument order: flags **after** port and baudrate):

```bash
.venv/bin/python scripts/simulate_device.py /dev/ttyUSB0 115200 --virtual
```

Its temperature hovers around 22 ± 2 and spikes about +5 every 100th sample —
peaks around 27–30. A rule `TEMP > 28` therefore fires occasionally and stays
quiet otherwise, which is exactly what you want to verify the loop:

1. Connect the virtual port (see [connect a board](how-to-connect-a-board.md)).
2. Create the rule above with cooldown `5`.
3. Wait for a spike. One history entry appears — with the value that tripped it.
4. Because cooldown is 5 s, the following above-threshold samples don't re-fire.
   With cooldown `0` you would get an entry per check (every ~2 s) for the whole
   spike, which is how you can tell cooldown is doing its job.

**Cooldown is per rule, default 60 s.** It is a suppressor, not a delay: the
first breach fires immediately; subsequent breaches are swallowed until the
cooldown window passes.

## Create and manage rules over the API

The REST body is stricter than the UI: `condition` must be one of the internal
names — symbols are rejected with a 422. Verified create:

```bash
curl -s -X POST http://127.0.0.1:8080/api/alerts/rules \
  -H 'content-type: application/json' \
  -d '{"name":"temp high","metric_name":"TEMP","condition":"gt","threshold":85,"cooldown_seconds":30}'
```

```json
{"id":"70050329-4e62-47b6-bee6-0b222031f263","created":true}
```

The list shows the stored rule (`id` differs per instance):

```bash
curl -s http://127.0.0.1:8080/api/alerts/rules
```

```json
[{"id":"70050329-4e62-47b6-bee6-0b222031f263","name":"temp high","metric_name":"TEMP","condition":"gt","threshold":85.0,"secondary_threshold":null,"cooldown":60,"severity":"warning","enabled":true,"trigger_count":0}]
```

Note the trap this example exposes: the create field is **`cooldown_seconds`**,
not `cooldown` — the response above shows `60` because an unknown `cooldown`
key was silently ignored and the default applied. The response object spells
the same value `cooldown`.

Other rule endpoints (all verified live): `DELETE /api/alerts/rules/{rule_id}`,
`PUT /api/alerts/rules/{rule_id}/enable`, `POST /api/alerts/test` (fire a test
alert through the pipeline), `GET /api/alerts/stats` (counts by severity,
unacknowledged, rule totals).

## Range and change conditions (API-only)

Two conditions the UI dropdown doesn't offer but the engine supports:

| Condition | Meaning | Fields |
|---|---|---|
| `range` | Fires when `threshold ≤ value ≤ secondary_threshold` — `threshold` is the **low** bound, `secondary_threshold` the high. | both required |
| `change` | Fires on a jump: `abs(value − last_value) > threshold`. Use it for step changes, not absolute levels. | `threshold` only |

Example — alert when buffer voltage sags below 3.0 V with a fast 10 s
suppressor:

```bash
curl -s -X POST http://127.0.0.1:8080/api/alerts/rules \
  -H 'content-type: application/json' \
  -d '{"name":"voltage sag","metric_name":"VOLTAGE","condition":"lt","threshold":3.0,"cooldown_seconds":10,"severity":"critical"}'
```

## Read and acknowledge the history

```bash
curl -s http://127.0.0.1:8080/api/alerts/history      # every fired alert
curl -s http://127.0.0.1:8080/api/alerts/stats
```

```json
{"total_alerts":0,"unacknowledged":0,"by_severity":{},"active_rules":0,"total_rules":0}
```

In the UI, the **Alerts** screen shows the same history with an **Acknowledge**
button per entry. Over the API: `POST /api/alerts/acknowledge/{alert_id}` for
one alert, `POST /api/alerts/acknowledge/all` for the whole backlog. The
`unacknowledged` count in `/api/alerts/stats` is what a CI job or dashboard
should poll.

## Gotchas

- **Metric name must match exactly.** The stream prints `TEMP:24.1`; the rule
  metric is `TEMP`. `temp` matches nothing — comparison is case-sensitive.
- **No data, no alerts.** Rules evaluate against live telemetry from connected
  devices; a device that isn't connected (or isn't parsing) can't breach
  anything.
- **Symbols via REST return 422** with a `string_pattern_mismatch` on
  `condition`. Translate `>` → `gt` etc. (the alias table above) when scripting.
- **WebSocket push**: fired alerts are also broadcast over the
  `/api/ws/telemetry` WebSocket endpoint if you want a live consumer rather
  than polling history.

Related: [tutorial step 5](tutorial-first-capture.md) ·
[sessions and export](how-to-sessions-and-export.md) ·
[API reference](reference-api.md)
