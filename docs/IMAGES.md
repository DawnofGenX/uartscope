# Screenshot capture script for UARTScope docs

Not part of the product — a throwaway tool used to produce the images in
`docs/images/`. Kept because re-running it is the only way to refresh the
screenshots after the UI changes.

```bash
# 1. Start the backend (optional, but the header shows a connection state)
cd backend && python -m uvicorn app.main:app --port 8080

# 2. Start the desktop app
.venv-v2/bin/python desktop_app.py

# 3. Capture every screen
bash docs/.shot.sh
```

## Why this is awkward

`smoke_pages.py` can reach every screen over HTTP through `/smoke/{tab}`,
which is the same path CI uses. The `with_device=true` query parameter binds a
demo device so the device-scoped screens render with data.

That parameter does not behave the way it looks: `selected_device` is a module
global in `desktop_app.py`, so once any request has bound the demo device, it
stays bound for the whole process. Screenshotting the empty state second gives
you a copy of the active state instead. `01-devices-empty.png` must therefore be
captured first, on a process that has never been asked for `with_device`.

If a capture comes out byte-identical to another, this is why. Delete
`backend/uartscope.db` and `sessions/*.json`, restart the app, and shoot the
empty state before anything else.

## Output

11 PNGs at 2x device scale (3200x2200), dark theme.
