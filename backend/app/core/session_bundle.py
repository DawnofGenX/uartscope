"""The .uartscope bundle format.

A bundle is the shareable capture: a zip holding

    session.json   descriptor -- version, session metadata, counts
    packets.json   the raw packets, which is the reason the format exists
    metrics.csv    every metric sample, one row per sample

This lived only inside `desktop_app._export_bundle`, assembled from UI state, so
nothing else could produce one. The assembly lives here now and the desktop app
calls it, because a format defined in two places drifts.

A note on CSV: values are written through the `csv` module rather than by
f-string, because a metric value or unit containing a comma would otherwise
split one sample into two columns and silently corrupt the export.
"""
import csv
import io
import json
import zipfile
from typing import Any, Dict, Iterable, Optional

# Bumped when the member set or descriptor shape changes. A reader that does
# not recognise this version should refuse rather than guess.
BUNDLE_VERSION = "2.0"
BUNDLE_TYPE = "uartscope-session"

SESSION_MEMBER = "session.json"
PACKETS_MEMBER = "packets.json"
METRICS_MEMBER = "metrics.csv"

METRICS_HEADER = ["timestamp", "metric", "value", "unit"]


class BundleError(Exception):
    """A bundle could not be built, read, or understood."""


def describe_bundle(session: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Filename and content type for a bundle.

    The filename is derived from the session id, truncated to 8 characters, so
    a capture is recognisable in a downloads folder without opening it.
    """
    sid = ((session or {}).get("id") or "unknown")
    safe = "".join(c for c in str(sid)[:8] if c.isalnum()) or "unknown"
    return {
        "filename": f"session_{safe}.uartscope",
        "media_type": "application/zip",
    }


def _metrics_rows(metrics: Dict[str, Any]) -> Iterable[list]:
    """Flatten {name: [samples]} into CSV rows.

    A sample may carry `timestamp` or `ts`; both appear in the wild, the former
    from the recorder and the latter from a raw metric dict.
    """
    for name, history in (metrics or {}).items():
        for sample in history or []:
            if not isinstance(sample, dict):
                # A bare scalar is still a data point; record it with no unit
                # rather than dropping it, so nothing silently disappears.
                yield [sample, name, sample, ""]
                continue
            yield [
                sample.get("timestamp") or sample.get("ts", ""),
                name,
                sample.get("value"),
                sample.get("unit") or "",
            ]


def build_bundle(
    session: Optional[Dict[str, Any]],
    packets: Optional[list],
    metrics: Optional[Dict[str, Any]],
    events: Optional[list] = None,
) -> bytes:
    """Assemble a .uartscope bundle and return its bytes.

    `packets` and `metrics` are the raw data, not a summary: the format exists
    so a capture can be re-analysed elsewhere, so a bundle built from an
    already-aggregated view would be useless for that.
    """
    packets = list(packets or [])
    metrics = metrics or {}
    events = list(events or [])

    descriptor = {
        "version": BUNDLE_VERSION,
        "type": BUNDLE_TYPE,
        "session": session or {},
        "metrics": metrics,
        "packet_count": len(packets),
        "event_count": len(events),
        "event_types": sorted({
            e.get("type") for e in events
            if isinstance(e, dict) and e.get("type")
        }),
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(SESSION_MEMBER, json.dumps(descriptor, indent=2, default=str))
        zf.writestr(PACKETS_MEMBER, json.dumps(packets, indent=2, default=str))
        csv_buffer = io.StringIO()
        writer = csv.writer(csv_buffer, lineterminator="\n")
        writer.writerow(METRICS_HEADER)
        writer.writerows(_metrics_rows(metrics))
        zf.writestr(METRICS_MEMBER, csv_buffer.getvalue())
    return buffer.getvalue()


def _coerce(text: str) -> Any:
    """Recover the scalar a CSV round trip flattened to text.

    A bundle is the interchange format, so a consumer re-reading one should not
    find every number turned into a string -- that changes what
    `isinstance(v, (int, float))` reports and breaks charting and alerting on
    the re-imported capture. Booleans are left alone, and anything
    non-numeric comes back as the original text.
    """
    if not text:
        return text
    stripped = text.strip()
    if stripped.lower() in ("true", "false"):
        return stripped.lower() == "true"
    try:
        return int(stripped)
    except ValueError:
        pass
    try:
        return float(stripped)
    except ValueError:
        return text


def read_bundle(blob: bytes) -> Dict[str, Any]:
    """Parse a bundle back into session, packets and metrics.

    Used by tests and by anything that needs to re-open a capture. Raises
    BundleError rather than returning a partial result, so a caller cannot
    mistake a broken bundle for an empty one.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            names = set(zf.namelist())
            missing = [m for m in (SESSION_MEMBER, PACKETS_MEMBER, METRICS_MEMBER)
                       if m not in names]
            if missing:
                raise BundleError(
                    f"Not a .uartscope bundle: missing {', '.join(missing)}")
            descriptor = json.loads(zf.read(SESSION_MEMBER))
            packets = json.loads(zf.read(PACKETS_MEMBER))
    except BundleError:
        raise
    except zipfile.BadZipFile as exc:
        raise BundleError("Not a zip archive") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise BundleError(f"Bundle member is not valid JSON: {exc}") from exc

    version = descriptor.get("version")
    if version != BUNDLE_VERSION:
        raise BundleError(
            f"Unsupported bundle version {version!r}; this build reads "
            f"{BUNDLE_VERSION!r}")

    # Rebuild the {name: [samples]} shape from the CSV so a bundle survives a
    # round trip through anything that flattens it.
    metrics: Dict[str, list] = {}
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        text = zf.read(METRICS_MEMBER).decode("utf-8")
    for row in csv.reader(io.StringIO(text)):
        if not row or row[0] == METRICS_HEADER[0]:
            continue
        timestamp, name, value, unit = (row + ["", "", "", ""])[:4]
        metrics.setdefault(name, []).append(
            {"timestamp": timestamp, "value": _coerce(value), "unit": unit})

    return {
        "version": version,
        "session": descriptor.get("session", {}),
        "packets": packets,
        "metrics": metrics or descriptor.get("metrics", {}),
        "event_count": descriptor.get("event_count", 0),
    }
