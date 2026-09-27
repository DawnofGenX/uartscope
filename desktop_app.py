"""UARTScope Pro - Desktop Application (NiceGUI)"""
import asyncio
import json
import logging
import os
import sys
import types
import uuid
from datetime import datetime

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from nicegui import ui, app

from uartscope_follow import follow_hook_js, scroll_to_bottom_js
from uartscope_theme import (
    inject_theme_css,
    icon,
    STATUS,
    ACCENT,
    TEXT,
)

from app.core.device_manager import device_manager
from app.core.telemetry_engine import telemetry_engine, Metric
from app.core.session_recorder import session_recorder
from app.core.alert_engine import alert_engine, AlertRule
from app.core.serial_reader import serial_reader
from app.core.websocket_hub import ws_manager
from app.core.protocol_decoder import protocol_manager
from app.core.performance_tracker import performance_tracker
from app.core.mqtt_client import mqtt_manager
from app.models import DeviceCreate

logger = logging.getLogger(__name__)

# ─── State ───────────────────────────────────────────────────────────────────
selected_device = None
selected_session = None
current_tab = 'devices'

# ─── Helpers ─────────────────────────────────────────────────────────────────
def format_bytes(b):
    if b < 1024: return f"{b} B"
    if b < 1024*1024: return f"{b/1024:.1f} KB"
    return f"{b/(1024*1024):.1f} MB"

def format_duration(started, ended=None, seconds=None):
    try:
        if seconds is not None:
            d = int(seconds)
        else:
            s = datetime.fromisoformat(started)
            e = datetime.fromisoformat(ended) if ended else datetime.utcnow()
            d = int((e - s).total_seconds())
    except:
        return "-"
    if d < 60: return f"{d}s"
    if d < 3600: return f"{d//60}m {d%60}s"
    return f"{d//3600}h {(d%3600)//60}m"

# Alert severity -> status token KEY (not a colour). Callers resolve the key
# through the theme, so a severity can never drift from the palette. v1 returned
# raw hex here with no relationship to anything else in the UI.
SEVERITY_TOKEN = {
    'critical': 'error',
    'warning': 'warn',
    'info': 'info',
}


def severity_token(sev):
    """Map an alert severity to a v2 status token key."""
    return SEVERITY_TOKEN.get((sev or 'warning').lower(), 'warn')


def severity_color(sev):
    """Map an alert severity to its resolved colour. For inline styles only;
    prefer a token class so the value stays in the theme."""
    return {
        'critical': STATUS['error'],
        'warning': STATUS['warn'],
        'info': STATUS['info'],
    }.get(sev, STATUS['idle'])

def get_stats():
    return device_manager.get_stats()

def get_devices():
    return device_manager.get_all_devices()

def get_alert_rules():
    return alert_engine.get_all_rules()

def get_alert_events():
    return alert_engine.get_alert_history()

def get_sessions():
    return session_recorder.list_sessions()

# ─── Sidebar ─────────────────────────────────────────────────────────────────
# v2: labelled rail with inline SVG icons.
#
# v1 rendered nine bare unicode glyphs (◈▸◇⚡☁◉⟳⬡🛒) with no text label, no
# tooltip and no accessible name — the labels existed in the nav tuple but were
# never passed to the button. The drawer was also inline-pinned to 56px, so
# labels would have clipped even if rendered.
#
# The rail collapses to icons below 1024px via CSS; because the label is real
# text rather than a title attribute, the accessible name survives the collapse.

NAV_ITEMS = [
    ('devices', 'devices', 'Devices', True),
    ('terminal', 'terminal', 'Terminal', True),
    ('charts', 'charts', 'Charts', True),
    ('performance', 'performance', 'Performance', False),
    ('mqtt', 'mqtt', 'MQTT', False),
    ('alerts', 'alerts', 'Alerts', True),
    ('sessions', 'sessions', 'Sessions', True),
    ('decoder', 'decoder', 'Decoder', True),
    ('marketplace', 'marketplace', 'Marketplace', False),
]

NAV_TAB_IDS = {tid for tid, *_ in NAV_ITEMS}

# Screens still on the v1 treatment. Surfaced in the release notes as not-yet-v2
# rather than hidden, so the nav is honest about what has been redesigned.
V2_PENDING = {'performance', 'mqtt', 'marketplace'}


def nav_label(tab_id):
    for tid, _icon, label, _v2 in NAV_ITEMS:
        if tid == tab_id:
            return label
    return tab_id.replace('-', ' ').title()


def build_sidebar():
    # Width: ui.left_drawer() has no width parameter, so it goes through props
    # as Quasar's `width`. Quasar then offsets .q-page-container by that amount
    # itself. Setting width via .style() or a CSS class instead made the aside
    # 200px while the page container kept its own zero offset, so the rail
    # rendered ON TOP of the header and the empty state.
    drawer = ui.left_drawer(fixed=True)
    drawer.props('width=200')
    with drawer:
        with ui.column().classes('w-full h-full'):
            with ui.row().classes('items-center gap-3 px-4 py-5'):
                ui.html(icon('brand', 22, 'us-brand-mark'))
                ui.label('UARTScope').classes('us-subhead')

            ui.label('MONITOR').classes('us-label us-muted px-4 pb-2')

            nav_col = ui.column().classes('w-full px-2 gap-1')
            for tab_id, icon_name, label, is_v2 in NAV_ITEMS:
                is_active = current_tab == tab_id
                with nav_col:
                    btn = ui.button(on_click=lambda t=tab_id: switch_tab(t))
                    btn.props('flat no-caps unelevated')
                    btn.classes('us-rail-item')
                    if not is_v2:
                        btn.classes('opacity-60')
                    if is_active:
                        # aria-current marks the active item for assistive tech;
                        # CSS adds the terracotta rail and a weight bump, so the
                        # selected state never depends on colour alone.
                        btn.props('aria-current=page')
                    with btn:
                        ui.html(icon(icon_name, 20))
                        ui.label(label).classes('us-rail-label text-[13px]')

            ui.space()
            _build_rail_footer()


# One observable dict drives every piece of live status text in the shell, so
# the header and the rail can never disagree with each other or with the page
# body. NiceGUI's bind_text_from polls it, so any state change only has to
# write here -- no shell rebuild required.
_STATUS_SRC: dict[str, str] = {
    'device_ratio': '0/0',
    'received': '0 B',
    'headline': 'No devices',
}

# Live dot elements, so _refresh_status() can restyle them without a rebuild.
_STATUS_DOTS: list = []


def _set_dot(el, state):
    """Apply the dot colour for a status state. Colour is always accompanied by
    the headline text, so it is never the only signal."""
    el.style(f'color: {STATUS[state]}')


def _refresh_status():
    """Recompute global status text and push it to every live label."""
    stats = get_stats()
    total = stats.get('total', 0)
    connected = stats.get('connected', 0)
    streaming = stats.get('streaming', 0)

    if streaming:
        headline = f"Streaming {streaming}"
    elif connected:
        headline = f"{connected} of {total} connected"
    elif total:
        headline = f"{total} registered, none started"
    elif selected_device is not None:
        # A device is bound (preview/demo, or a selection made earlier in this
        # session) but none is registered with the manager. Saying "No devices"
        # here contradicts the page body, which is showing that device's data.
        headline = "Preview device"
    else:
        headline = "No devices"

    _STATUS_SRC['device_ratio'] = f"{connected}/{total}"
    _STATUS_SRC['received'] = format_bytes(stats['total_bytes_received'])
    _STATUS_SRC['headline'] = headline

    state = 'live' if streaming else ('info' if connected else 'idle')
    for dot in _STATUS_DOTS:
        try:
            _set_dot(dot, state)
        except Exception:
            # A dot from a previous page build can be detached by now; that is
            # not worth failing a status refresh over.
            pass


def _build_rail_footer():
    """Global counters, pinned to the bottom of the rail.

    The labels are registered as live status text so _refresh_status() can
    update them in place. v1 rebuilt the shell only on page navigation, which
    left the rail reading 0/0 while the device list below it showed a device --
    the header and the content disagreeing is worse than either being stale.
    """
    stats = get_stats()
    with ui.column().classes(
            'w-full px-4 py-4 gap-2 border-t border-[rgba(176,174,165,0.16)]'):
        with ui.row().classes('items-baseline justify-between w-full'):
            ui.label(f"{stats['connected']}/{stats['total']}").classes(
                'us-mono').bind_text_from(_STATUS_SRC, 'device_ratio')
            ui.label('Devices').classes('us-micro')
        with ui.row().classes('items-baseline justify-between w-full'):
            ui.label().classes('us-mono').bind_text_from(
                _STATUS_SRC, 'received')
            ui.label('Received').classes('us-micro')


# ─── Pages ───────────────────────────────────────────────────────────────────

# Baud rates offered in the add-device form. Ordered by how often embedded devs
# actually use them, so the common case needs no scrolling.
COMMON_BAUDRATES = [9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600]

# Connection states -> status token. A single accent colour cannot carry four
# distinct states, and v1 gave every state the same blue.
DEVICE_STATE_COLOR = {
    'streaming': 'live',
    'connected': 'info',
    'registered': 'idle',
    'error': 'error',
    'disconnected': 'idle',
}


def _device_state(dev):
    """Return (token_key, human label) for a device's connection state."""
    status = (getattr(dev, 'status', None) or 'registered').lower()
    if status == 'streaming':
        return 'live', 'Streaming'
    if status == 'connected':
        return 'info', 'Connected'
    if status in ('error', 'failed'):
        return 'error', 'Error'
    return 'idle', 'Ready'


def devices_page():
    """Devices: an Operate surface.

    The correct archetype here is Operate -- the user is acting on a fleet of
    ports. v1 rendered this landing screen as a stack of decorative cards with a
    dead-end empty state ("Connect a serial device" with no way to do it) and
    reported no live rate, even though the backend tracks bytes and packets.

    v2 makes the empty state actionable -- it can actually scan for ports,
    because device_manager.detect_ports() already existed and was never called
    from the UI -- and switches connected devices to dense rows.
    """
    container = ui.column().classes('w-full gap-5')
    scan_state = {'running': False, 'ports': [], 'error': None, 'scanned': False}

    def refresh_devices():
        stats = get_stats()
        devices = get_devices()
        container.clear()
        _refresh_status()
        # MUST re-enter the container. After clear(), NiceGUI's ambient context
        # still points at the now-deleted slot, so building without this raises
        # "The parent element this slot belongs to has been deleted" -- which
        # silently blanked the page on the first scan click.
        with container:
            _devices_body(stats, devices, scan_state, refresh_devices, {
                'start': start_device,
                'stop': stop_device,
                'reconnect': toggle_reconnect,
                'terminal': open_terminal,
                'charts': open_charts,
            })

    async def start_device(device):
        try:
            await device_manager.connect(device.id)
            session_id = str(uuid.uuid4())
            await session_recorder.start_session(session_id, device.id, f"Session {device.name}")
            device.session_id = session_id
            device.status = 'streaming'

            async def on_data(dev_id=device.id, sess_id=session_id, line=""):
                await telemetry_engine.process_line(dev_id, sess_id, line)
                await session_recorder.record_packet(sess_id, {"device_id": dev_id, "raw": line})
                latest = telemetry_engine.get_latest_values(dev_id)
                for mn, val in latest.items():
                    from app.core.telemetry_engine import Metric
                    await alert_engine.evaluate(dev_id, sess_id, Metric(name=mn, value=val, unit=None, message_type="metric"))

            await serial_reader.start_device(device_manager._devices[device.id], session_id, on_data)
            ui.notify(f"Started streaming from {device.name}", type='positive')
            refresh_devices()
        except Exception as e:
            ui.notify(f"Could not start {device.name}: {e}", type='negative')
            refresh_devices()

    async def stop_device(device):
        try:
            await serial_reader.stop_device(device.id)
            sid = device_manager._devices[device.id].session_id
            if sid:
                await session_recorder.stop_session(sid)
            device_manager._devices[device.id].session_id = None
            device_manager._devices[device.id].status = 'connected'
            ui.notify(f"Stopped {device.name}", type='info')
            refresh_devices()
        except Exception as e:
            ui.notify(f"Could not stop {device.name}: {e}", type='negative')
            refresh_devices()

    async def toggle_reconnect(device):
        device.auto_reconnect = not device.auto_reconnect
        ui.notify(
            f"{device.name}: {'auto' if device.auto_reconnect else 'manual'} reconnect",
            type='info')
        refresh_devices()

    def open_terminal(device):
        global selected_device, current_tab
        selected_device = device
        current_tab = 'terminal'
        rebuild()

    def open_charts(device):
        global selected_device, current_tab
        selected_device = device
        current_tab = 'charts'
        rebuild()

    refresh_devices()


def _devices_body(stats, devices, scan_state, refresh, actions):
    """Summary strip plus either the device rows or the empty state.

    Split out of refresh_devices() so the whole body rebuilds inside one
    `with container:` block -- see the comment there about the deleted-slot
    RuntimeError.
    """
    # ── Summary strip ────────────────────────────────────────────────────
    # Real numbers the user acts on, not vanity metrics.
    with ui.row().classes('w-full gap-3'):
        for label, val, token in [
            ('Devices', f"{stats['connected']}/{stats['total']}", None),
            ('Received', format_bytes(stats['total_bytes_received']), None),
            ('Streaming', str(stats['streaming']),
             'live' if stats['streaming'] else 'idle'),
        ]:
            with ui.column().classes('us-card flex-1 gap-1 !p-4'):
                ui.label(label).classes('us-label us-muted')
                # Colour the value only when it carries state; a count of
                # zero is not an alarm.
                ui.label(val).classes('us-metric').style(
                    f'color: {STATUS[token]}' if token else '')

    if not devices:
        _devices_empty_state(scan_state, refresh)
    else:
        _device_rows(devices, refresh, actions)


def _device_rows(devices, refresh, actions):
    """Connected devices as dense rows, not cards.

    An Operate surface is scanned, not admired: one line per device, state
    legible at a glance, actions at the row's trailing edge. Callbacks arrive as
    an explicit `actions` map rather than as closures, so this stays a plain
    module-level function.

    The caller must already be inside the target container -- NiceGUI binds ui.*
    to the ambient context, not to a container passed in as an argument.
    """
    ui.label('CONNECTED').classes('us-label us-muted')
    with ui.column().classes('w-full gap-2'):
        for device in devices:
            token, state_label = _device_state(device)
            with ui.row().classes('us-row w-full items-center gap-4'):
                ui.html(f'<span class="us-dot us-dot-{token}">')
                with ui.column().classes('gap-0.5 flex-1 min-w-0'):
                    with ui.row().classes('items-center gap-2'):
                        ui.label(device.name or 'Unnamed').classes(
                            'us-subhead truncate')
                        ui.label(state_label).classes('us-micro').style(
                            f'color: {STATUS[token]}')
                    with ui.row().classes('items-baseline gap-3'):
                        ui.label(device.port).classes('us-mono us-muted')
                        ui.label(f'{device.baudrate:,} baud').classes(
                            'us-micro us-muted')
                        if getattr(device, 'board_type', None):
                            ui.label(device.board_type).classes(
                                'us-micro us-muted')
                with ui.row().classes('items-center gap-2'):
                    if device.status == 'streaming':
                        _btn('Stop', 'us-btn-danger',
                             lambda d=device: actions['stop'](d))
                        _btn('Charts', 'us-btn-secondary',
                             lambda d=device: actions['charts'](d))
                        _btn('Terminal', 'us-btn-primary',
                             lambda d=device: actions['terminal'](d))
                    else:
                        _btn('Auto' if device.auto_reconnect else 'Manual',
                             'us-btn-ghost',
                             lambda d=device: actions['reconnect'](d))
                        _btn('Start', 'us-btn-primary',
                             lambda d=device: actions['start'](d))


def _btn(text, cls, handler):
    """A themed button. NiceGUI stamps Quasar's text-primary on every
    ui.button(); the us-btn-* classes are what actually carry the palette."""
    b = ui.button(text, on_click=handler)
    b.props('flat no-caps')
    b.classes(f'us-btn {cls}')
    return b


def _devices_empty_state(scan_state, refresh):
    """Actionable empty state: scan, list what's there, or learn how.

    v1's version said "Connect a serial device to start monitoring" and offered
    nothing -- a dead end, and the documented first-run failure mode for this
    class of tool. The three distinct outcomes here mirror the real ones:
    no ports, ports found, or scan failed.
    """
    with ui.column().classes('us-empty w-full'):
        with ui.column().classes('gap-2'):
            ui.label('No devices connected').classes('us-display')
            ui.label(
                'Scan for serial ports, or add one manually if your board is '
                'already open in another program.').classes('us-body')

        # Primary action. Disabled while scanning, with the state shown.
        scanning = scan_state['running']
        scan_btn = ui.button(
            'Scanning…' if scanning else 'Scan for devices',
            on_click=lambda: _run_scan(scan_state, refresh),
        ).props('flat no-caps')
        scan_btn.classes('us-btn us-btn-primary')
        if scanning:
            scan_btn.disable()

        # Scan result
        if scan_state['error']:
            with ui.row().classes('items-start gap-2 us-body').style(
                    f'color: {STATUS["error"]}'):
                ui.html(f'<span class="us-dot" style="background:{STATUS["error"]}">')
                ui.label(scan_state['error'])

        ports = scan_state['ports']
        if ports:
            ui.label(f'{len(ports)} port{"" if len(ports) == 1 else "s"} found'
                     ).classes('us-label us-muted mt-2')
            with ui.column().classes('w-full gap-2'):
                for p in ports:
                    _detected_port_row(p, refresh)
        elif scan_state['error'] is None and scan_state['scanned']:
            # Scan ran and genuinely found nothing -- say so plainly, and point
            # at the most common cause rather than leaving a blank region.
            ui.label('No serial ports found').classes('us-subhead')
            ui.label(
                'Check the cable and that the board has power. If another '
                'program has the port open, close it and scan again.'
            ).classes('us-body us-muted')

        # Guidance: a short 3-step path, not a paragraph.
        ui.label('CONNECTING A BOARD').classes('us-label us-muted mt-2')
        with ui.column().classes('us-empty-steps w-full'):
            for i, step in enumerate([
                'Plug the board in over USB. Most ESP32 and Arduino boards '
                'enumerate as a serial port automatically.',
                'Close any other program holding the port — the Arduino IDE '
                'Serial Monitor, PlatformIO monitor, or a previous UARTScope '
                'window all block it.',
                'Scan above, then press Start on the port you want.',
            ], start=1):
                with ui.row().classes('us-empty-step'):
                    ui.label(str(i)).classes('us-step-num')
                    ui.label(step).classes('flex-1')


def _late_bindings():
    """A registry for handlers referenced before they are defined.

    v1 wired `on_click=some_handler` to functions defined further down the same
    page-builder body. Python allows it; the *page* does not survive it -- the
    name is a local that is not yet bound, so constructing the screen raises
    UnboundLocalError and the screen is simply unreachable. Terminal, Charts,
    Decoder, Alerts, Session Detail and MQTT were all broken this way in v1.

    Rather than re-indent six large page builders to hoist each handler above
    the UI, the button binds to `_late('name')`, which resolves the handler when
    the click fires -- by which point the real function is always in scope. The
    page then registers it: `_bind('name', real_handler)`.

    check_handler_order.py statically verifies the pattern is actually used and
    that no page is left with an unresolved reference.
    """
    registry: dict = {}

    def bind(name, fn):
        registry[name] = fn

    def late(name):
        def call(*a, **kw):
            fn = registry.get(name)
            if fn is None:
                raise RuntimeError(f'handler {name!r} was never registered')
            return fn(*a, **kw)
        return call

    return bind, late


def needs_device(title, detail):
    """Render a dead-end guard for screens that require a selected device.

    v1 used a bare centred label on Terminal, Charts and Sessions: "Select a
    device from the Devices tab". It names the problem but gives the user no way
    out of it, from a screen that has no route back. v2 states what is needed
    and offers the one action that resolves it.
    """
    with ui.column().classes('us-empty w-full'):
        with ui.column().classes('gap-2'):
            ui.label(title).classes('us-display')
            ui.label(detail).classes('us-body')
        _btn('Go to Devices', 'us-btn-primary', _goto_devices)


def _goto_devices():
    global current_tab
    current_tab = 'devices'
    rebuild()


def _is_real(value):
    """True when a backend-detected string is actual information.

    detect_ports() returns the literal "n/a" (description) and "Unknown"
    (board_type) for anything it cannot fingerprint, and WSL reports every
    ttyS* that way. Rendering those verbatim puts "n/a" in the UI as though it
    were a device description, so they are treated as missing everywhere.
    """
    return bool(value) and value.strip().lower() not in (
        'n/a', 'na', 'unknown', 'none', '-', 'null')


def _detected_port_row(port, refresh):
    """One detected port, with a friendly name and a one-click add.

    This is the payoff of the actionable empty state: the user can go from
    nothing registered to a device that is ready to Start, in two clicks.
    """
    board = port.get('board_type') if _is_real(port.get('board_type')) \
        else 'Serial port'
    description = port.get('description') if _is_real(port.get('description')) \
        else ''
    with ui.row().classes('us-row w-full items-center gap-3'):
        ui.html(icon('devices', 18))
        with ui.column().classes('gap-0.5 flex-1 min-w-0'):
            with ui.row().classes('items-baseline gap-2'):
                ui.label(port['port']).classes('us-mono')
                ui.label(board).classes('us-micro us-muted')
            if description:
                ui.label(description).classes('us-micro us-muted truncate')
        _btn('Add', 'us-btn-secondary', lambda p=port: _add_detected(p, refresh))


async def _run_scan(scan_state, refresh):
    """Enumerate serial ports via the backend's existing detect_ports().

    detect_ports() has existed in the backend all along; v1's UI simply never
    called it, which is why the empty state could not act on its own advice.
    """
    scan_state['running'] = True
    scan_state['error'] = None
    scan_state['ports'] = []
    try:
        scan_state['ports'] = await device_manager.detect_ports()
    except Exception as e:
        scan_state['error'] = f"Port scan failed: {e}"
    finally:
        scan_state['running'] = False
        scan_state['scanned'] = True
    refresh()


async def _add_detected(port, refresh):
    """Register a detected port as a device, defaulting to 115200."""
    try:
        # Name it after the port, not the board guess. The backend reports
        # board_type="Unknown" for anything it cannot fingerprint, and "Unknown"
        # as a device name tells the user nothing they can act on.
        dev = await device_manager.add_device(DeviceCreate(
            name=port['port'],
            port=port['port'],
            baudrate=115200,
            board_type=port.get('board_type') if _is_real(
                port.get('board_type')) else None,
            metadata={'description': port.get('description'),
                      'manufacturer': port.get('manufacturer')},
        ))
        ui.notify(
            f"Added {port['port']} — press Start to connect it", type='positive')
        refresh()
    except Exception as e:
        ui.notify(f"Could not add {port['port']}: {e}", type='negative')


def terminal_page():
    """Terminal: the Command/Inspect surface.

    v1 could not be opened at all. It built the command bar -- passing
    `on_click=show_macros_dialog` -- some 70 lines *before* defining that
    handler, so page construction raised UnboundLocalError and the screen died
    with a 500. The error only ever appeared in the server log. Handlers are
    therefore defined before the UI here, and the order is not incidental.

    The other thing v1 got wrong is the one users feel most: it re-rendered the
    log and let the browser stick to the bottom, so scrolling up to read a burst
    of output was impossible -- the view yanked you back down mid-sentence.
    v2 follows Wireshark's model: follow the tail only while the user is already
    at the bottom, otherwise hold position and count the backlog.
    """
    global selected_device

    if not selected_device:
        needs_device(
            'No device selected',
            'Pick a device to watch its serial output live. Start one on the '
            'Devices screen if you have not already.')
        return

    # ── State ────────────────────────────────────────────────────────────
    terminal_state = {
        'lines': [], 'search': '', 'case_sensitive': False, 'regex': False,
        'match_count': 0, 'current_match': 0, 'filter_level': 'all',
        'filter_metric': '', 'follow': True, 'pending': 0, 'rendered': 0,
    }
    command_history = []   # [{'cmd': str, 'timestamp': str}]
    macros = [{'name': 'Scan I2C', 'commands': ['AA', 'BB']}]

    # ── Handlers (all defined before the UI references them) ─────────────
    def send_command():
        cmd = (cmd_input.value or '').strip()
        if not cmd:
            return
        command_history.insert(
            0, {'cmd': cmd, 'timestamp': datetime.utcnow().strftime('%H:%M:%S')})
        del command_history[100:]

        async def _send():
            device = device_manager.get_device(selected_device.id)
            if device and device.serial_conn:
                try:
                    device.serial_conn.write((cmd + '\n').encode())
                    ui.notify(f"Sent: {cmd}", type='positive', timeout=2000)
                except Exception as e:
                    ui.notify(f"Send failed: {e}", type='negative')
            else:
                ui.notify("Device not connected", type='warning')
        asyncio.create_task(_send())
        cmd_input.value = ''

    def replay_command(entry):
        cmd_input.value = entry['cmd']

    def delete_macro(index):
        if 0 <= index < len(macros):
            name = macros[index]['name']
            macros.pop(index)
            ui.notify(f"Deleted macro '{name}'", type='info')
            _rerender_macros()

    def create_macro(name, commands_text, dialog):
        commands = [c.strip() for c in commands_text.strip().split('\n') if c.strip()]
        if not commands:
            ui.notify('Add at least one command', type='warning')
            return
        macros.append({'name': name or 'Unnamed', 'commands': commands})
        dialog.close()
        ui.notify(f"Macro '{name}' created with {len(commands)} commands",
                  type='positive')
        _rerender_macros()

    async def run_macro(macro):
        device = device_manager.get_device(selected_device.id)
        if not device or not device.serial_conn:
            ui.notify("Device not connected", type='warning')
            return
        ui.notify(f"Running macro '{macro['name']}'...", type='info')
        for cmd in macro['commands']:
            try:
                device.serial_conn.write((cmd + '\n').encode())
                await asyncio.sleep(0.1)
            except Exception as e:
                ui.notify(f"Macro failed at '{cmd}': {e}", type='negative')
                return
        ui.notify(f"Macro '{macro['name']}' complete", type='positive')

    # ── Follow-mode ──────────────────────────────────────────────────────
    # The tail test must run in JS: NiceGUI elements expose no scrollTop /
    # scrollHeight / clientHeight, so Python cannot answer "is the user parked at
    # the newest line?" at all. uartscope_follow owns the listener and reports
    # only the boolean that actually changed.
    def _scroll_to_bottom():
        ui.run_javascript(scroll_to_bottom_js())

    def _update_jump_bar():
        n = terminal_state['pending']
        if n:
            jump_bar.text = f"↓ {n:,} new line{'' if n == 1 else 's'}"
            jump_bar.tooltip = "Jump to the newest line and resume following"
        else:
            jump_bar.text = "↓ Following"
            jump_bar.tooltip = "Following the newest line"

    def _jump_to_new():
        """Resume following: clear the backlog, re-render, park at the tail."""
        terminal_state['pending'] = 0
        terminal_state['follow'] = True
        _apply_search_filter()
        _update_jump_bar()

    def _on_follow_change(e):
        """JS reports that the user scrolled away from, or back to, the tail."""
        following = e.args[0] if getattr(e, 'args', None) else True
        terminal_state['follow'] = bool(following)
        if following:
            terminal_state['pending'] = 0
        _update_jump_bar()

    # ── Rendering ────────────────────────────────────────────────────────
    def _classify(line):
        """Tag a line so it can be filtered and coloured by kind."""
        up = line.upper()
        if any(w in up for w in ('ERROR', 'FATAL')):
            return 'error'
        if any(w in up for w in ('WARN', 'WARNING')):
            return 'warn'
        if line.startswith('{') and line.endswith('}'):
            return 'json'
        if any(up.startswith(m) for m in (
                'TEMP', 'VOLTAGE', 'HUMIDITY', 'PRESSURE', 'CURRENT', 'POWER',
                'ADC', 'PWM', 'FREQ', 'RSSI', 'SNR')):
            return 'metric'
        return 'log'

    def _matcher(search, case_sensitive, use_regex):
        if not search:
            return None
        import re as _re
        flags = 0 if case_sensitive else _re.IGNORECASE
        try:
            return _re.compile(search if use_regex else _re.escape(search), flags)
        except _re.error:
            # A half-typed regex should not blank the log; it should say it is
            # invalid and otherwise leave the view alone.
            return 'invalid'

    def _passes_level(line, line_type, level):
        if level == 'all':
            return True
        up = line.upper()
        if level in ('ERROR', 'WARN', 'INFO', 'DEBUG'):
            return level in up
        return line_type == level

    def _apply_search_filter():
        """Re-render the log under the current search, filter and follow state."""
        search = terminal_state['search']
        pattern = _matcher(search, terminal_state['case_sensitive'],
                           terminal_state['regex'])
        level = terminal_state['filter_level']
        metric_filter = terminal_state['filter_metric'].strip().upper()

        matches = []
        for i, (ts, line, line_type) in enumerate(terminal_state['lines']):
            if not _passes_level(line, line_type, level):
                continue
            if metric_filter and metric_filter not in line.upper():
                continue
            is_match = True
            if pattern == 'invalid':
                is_match = False
            elif pattern is not None:
                is_match = bool(pattern.search(
                    line if terminal_state['case_sensitive'] else line.lower()))
            matches.append((i, ts, line, line_type, is_match))

        match_indices = [k for k, m in enumerate(matches) if m and search]
        terminal_state['match_count'] = len(match_indices)

        if pattern == 'invalid':
            match_label.set_text("Invalid regular expression")
        elif match_indices:
            terminal_state['current_match'] = min(
                terminal_state['current_match'], len(match_indices) - 1)
            match_label.set_text(
                f"Match {terminal_state['current_match'] + 1} of "
                f"{len(match_indices):,}")
        elif search:
            match_label.set_text("No matches")
        else:
            match_label.set_text(f"{len(terminal_state['lines']):,} lines")

        # Cap what we paint. The buffer holds 5000 lines; creating one NiceGUI
        # element per line on every batch is what made v1 stutter, and nobody
        # reads 5000 rows on screen at once. The cap still leaves far more
        # scrollback than fits on a monitor.
        MAX_PAINTED = 600
        visible = matches[-MAX_PAINTED:]
        hidden = len(matches) - len(visible)

        with log_area:
            if hidden:
                ui.label(
                    f"… {hidden:,} earlier line{'' if hidden == 1 else 's'} "
                    f"matched but not shown — narrow the filter to see them"
                ).classes('us-log-more')
            for _i, ts, line, line_type, is_match in visible:
                ui.label(f"[{ts}] {line}").classes(
                    f'us-log-line us-log-{line_type}').style(
                    'background: rgba(201,100,66,0.18); border-radius:2px;'
                    if is_match and search else '')

        # Follow-mode: only move the viewport if the user was already at the
        # tail. Otherwise preserve where they scrolled to and count the backlog.
        if terminal_state['follow']:
            _scroll_to_bottom()
        else:
            added = len(matches) - terminal_state['rendered']
            if added > 0:
                terminal_state['pending'] += added
                _update_jump_bar()
        terminal_state['rendered'] = len(matches)

    def navigate_match(direction):
        if direction == '__init__':
            return
        if terminal_state['match_count'] == 0:
            return
        terminal_state['current_match'] = (
            terminal_state['current_match'] + direction) % terminal_state['match_count']
        _apply_search_filter()

    def clear_search():
        terminal_state['search'] = ''
        terminal_state['filter_level'] = 'all'
        terminal_state['filter_metric'] = ''
        terminal_state['current_match'] = 0
        _apply_search_filter()

    def toggle_case():
        terminal_state['case_sensitive'] = not terminal_state['case_sensitive']
        _apply_search_filter()

    def toggle_regex():
        terminal_state['regex'] = not terminal_state['regex']
        _apply_search_filter()

    # ── Dialogs ──────────────────────────────────────────────────────────
    # Held on the state dict rather than closed over, so _rerender_macros() can
    # reach it without a nonlocal and without UnboundLocalError.
    terminal_state['macros_host'] = None

    def _rerender_macros():
        host = terminal_state.get('macros_host')
        if host is None or host.is_deleted:
            return
        host.clear()
        with host:
            _render_macros()

    def _render_macros():
        if not macros:
            ui.label('No macros yet').classes('us-body us-muted')
            return
        with ui.column().classes('w-full gap-1'):
            for i, macro in enumerate(macros):
                with ui.row().classes('us-row w-full items-center gap-3'):
                    with ui.column().classes('gap-0.5 flex-1'):
                        ui.label(macro['name']).classes('us-subhead')
                        ui.label(f"{len(macro['commands'])} commands").classes(
                            'us-micro us-muted')
                    _btn('Run', 'us-btn-secondary', lambda m=macro: run_macro(m))
                    _btn('Delete', 'us-btn-ghost us-btn-danger',
                         lambda k=i: delete_macro(k))

    def show_macros_dialog():
        dialog = ui.dialog()
        with dialog, ui.column().classes('us-dialog w-[420px]'):
            with ui.row().classes('w-full items-center justify-between'):
                ui.label('Macros').classes('us-subhead')
                _btn('New', 'us-btn-primary', lambda: _new_macro_from(dialog))
            terminal_state['macros_host'] = ui.column().classes('w-full gap-2')
            _render_macros()
        dialog.open()

    def _new_macro_from(parent):
        parent.close()
        dlg = ui.dialog()
        with dlg, ui.column().classes('us-dialog w-[420px]'):
            ui.label('New macro').classes('us-subhead')
            name_input = ui.input('Name', value='').classes('w-full')
            cmds_input = ui.textarea(
                'Commands (one per line)', value='AT\\r\\nAT+STATUS').classes('w-full')
            with ui.row().classes('w-full justify-end gap-2'):
                _btn('Cancel', 'us-btn-ghost', dlg.close)
                _btn('Create', 'us-btn-primary',
                     lambda: create_macro(name_input.value, cmds_input.value, dlg))
        dlg.open()

    def show_history_dialog():
        dialog = ui.dialog()
        with dialog, ui.column().classes('us-dialog w-[480px]'):
            ui.label('Command history').classes('us-subhead')
            if not command_history:
                ui.label('No commands sent yet').classes('us-body us-muted')
            else:
                with ui.column().classes('w-full gap-1'):
                    for entry in command_history[:20]:
                        with ui.row().classes('us-row w-full items-center gap-3').on(
                                'click', lambda e, en=entry: replay_command(en)):
                            ui.label(entry['timestamp']).classes('us-mono us-muted')
                            ui.label(entry['cmd']).classes('us-mono flex-1 truncate')
                            ui.html(icon('terminal', 14))
        dialog.open()

    # ── UI ───────────────────────────────────────────────────────────────
    with ui.column().classes('w-full gap-3'):
        with ui.row().classes('us-toolbar w-full items-center gap-3'):
            with ui.column().classes('gap-0.5 flex-1 min-w-0'):
                ui.label(selected_device.name or selected_device.port).classes(
                    'us-subhead truncate')
                ui.label(
                    f"{selected_device.port} · {selected_device.baudrate:,} baud"
                ).classes('us-micro us-mono us-muted')
            ui.label('0 lines').classes('us-mono us-muted').bind_text_from(
                terminal_state, 'lines', lambda v: f"{len(v):,} lines")

        with ui.row().classes('us-toolbar w-full items-center gap-2'):
            cmd_input = ui.input(
                placeholder='Type a command and press Enter…').classes(
                'flex-1 us-input').props('outlined dense')
            _btn('Send', 'us-btn-primary', send_command)
            _btn('Macros', 'us-btn-secondary', show_macros_dialog)
            _btn('History', 'us-btn-secondary', show_history_dialog)
        cmd_input.on('keydown.enter', send_command)

        with ui.row().classes('us-toolbar w-full items-center gap-3'):
            search_input = ui.input(placeholder='Search…').classes(
                'flex-1 us-input').props('outlined dense')
            search_input.bind_value(terminal_state, 'search')
            level_select = ui.select(
                ['all', 'ERROR', 'WARN', 'INFO', 'DEBUG', 'metric', 'json'],
                value='all').classes('w-32 us-input').props('outlined dense')
            level_select.bind_value(terminal_state, 'filter_level')
            _btn('Aa', 'us-btn-ghost', toggle_case)
            _btn('.*', 'us-btn-ghost', toggle_regex)

        with ui.row().classes('w-full items-center gap-2'):
            match_label = ui.label('0 lines').classes('us-caption us-muted flex-1')
            _btn('◀', 'us-btn-ghost', lambda: navigate_match(-1))
            _btn('▶', 'us-btn-ghost', lambda: navigate_match(1))
            _btn('Clear', 'us-btn-ghost', clear_search)
            jump_bar = _btn('↓ Following', 'us-btn-ghost us-btn-jump', _jump_to_new)

        log_area = ui.column().classes('us-log w-full gap-0')
        # NiceGUI's js_handler is the supported way to have a JS listener emit a
        # custom event into a Python handler, so the browser reports only the
        # boolean that changed rather than every scroll frame.
        log_area.on('follow-change', _on_follow_change, args=['following'],
                    js_handler="() => {const e=$event.target;"
                               "emit(e.__usFollow);}")

    # First paint, then install the follow hook -- the hook needs the log element
    # to already exist in the DOM.
    _apply_search_filter()
    _update_jump_bar()
    ui.run_javascript(follow_hook_js())

    search_input.on_value_change(lambda: _apply_search_filter())
    level_select.on_value_change(lambda: _apply_search_filter())

    async def stream_loop():
        if not selected_device:
            return
        queue = asyncio.Queue()

        async def on_data(line=""):
            await queue.put(line)

        try:
            await serial_reader.start_device(selected_device, "terminal", on_data)
        except Exception as e:
            ui.notify(f"Could not attach to the stream: {e}", type='negative')
            return

        try:
            while True:
                line = await asyncio.wait_for(queue.get(), timeout=1)
                terminal_state['lines'].append((
                    datetime.utcnow().strftime('%H:%M:%S'), line, _classify(line)))
                # Keep the buffer bounded; the painted window is capped anyway.
                del terminal_state['lines'][:-5000]
                _apply_search_filter()
        except asyncio.CancelledError:
            raise
        except Exception:
            # A read loop that dies silently looks identical to a device that
            # stopped talking, which is the single most confusing failure a
            # serial tool can have.
            logger.exception("terminal stream loop for %s failed",
                             selected_device.id)
            ui.notify("Stream stopped unexpectedly", type='negative')

    asyncio.create_task(stream_loop())

def charts_page():
    """Charts: the Monitor surface.

    v1 built a "dashboard builder": you hand-pick widgets, each bound to one
    metric, and every one of them is a card. That is the wrong shape for this
    screen, and the reasoning is physical rather than stylistic:

      * A chart puts comparable series on one Y axis. v1 let you pin any set of
        metrics to one card, so degrees Celsius were drawn against dBm and the
        resulting curve was meaningless. The backend already records a unit per
        metric; v1 threw it away. v2 groups series by unit and never mixes them.
      * The units were not even available. The KEY:VALUE parser -- the common
        form -- left unit=None for bare lines like "TEMP:23.4", so there was
        nothing to group by. Fixed in telemetry_engine._parse, with tests.
      * A dashboard you have to assemble by hand starts empty and stays empty.
        Metrics a device is already reporting are the obvious first view, so v2
        opens on them and lets you add, pin and hide from there.

    Widgets still exist -- pinned series, gauges, alert summary -- but they sit
    on top of the live view instead of being the only way in.
    """
    global selected_device

    if not selected_device:
        needs_device(
            'No device selected',
            'Charts plot the metrics a device reports. Start one on the '
            'Devices screen, then come back here.')
        return

    # Dashboard state
    dashboard_state = {
        'widgets': [],   # pinned series the user explicitly added
        'edit_mode': False,
        'next_id': 1,
        'pinned': set(),  # metric names the user chose to pin
        'hidden': set(),  # metric names the user folded away
    }

    _bind_charts_page, _late_charts_page = _late_bindings()

    # ── Metric discovery ─────────────────────────────────────────────────
    # One source of truth, so the axis groups, the legend and the pin state can
    # never disagree about which metrics exist or what unit they carry.
    def metrics_by_unit():
        """-> {unit: [(name, [values...], latest), ...]}, ordered for reading."""
        raw = telemetry_engine.get_all_metrics(selected_device.id) or {}
        groups: dict = {}
        for name, history in raw.items():
            if not history:
                continue
            unit = history[-1].unit or '—'   # em dash: "no unit", not a guess
            values = [m.value for m in history[-60:]]
            groups.setdefault(unit, []).append((name, values, history[-1].value))
        for unit in groups:
            groups[unit].sort(key=lambda t: t[0])
        # No-unit series last: they are the ones you have to read a legend for.
        return dict(sorted(groups.items(),
                           key=lambda kv: (kv[0] == '—', kv[0])))

    def available_metrics():
        return metrics_by_unit()

    def toggle_edit():
        dashboard_state['edit_mode'] = not dashboard_state['edit_mode']
        refresh_dashboard()

    # ── Rendering helpers ────────────────────────────────────────────────
    def _fmt(v):
        """Format a value without lying about precision."""
        if v is None:
            return '—'
        av = abs(v)
        if av >= 1000:
            return f'{v:,.0f}'
        if av >= 100:
            return f'{v:.1f}'
        if av >= 1:
            return f'{v:.2f}'
        return f'{v:.3f}'

    def _sparkline(values, unit):
        """A 20-sample block sparkline. Colour is the series' unit group, so a
        glance distinguishes temperature from signal strength."""
        vals = values[-20:]
        if len(vals) < 2:
            return ''
        lo, hi = min(vals), max(vals)
        rng = (hi - lo) or 1.0
        ramp = ' ▁▂▃▄▅▆▇█'
        return ''.join(
            ramp[min(int(((v - lo) / rng) * 8), 8)] for v in vals)

    def _trend(values):
        """Direction of travel, as a word plus a glyph -- never colour alone."""
        if len(values) < 2:
            return None
        delta = values[-1] - values[-2]
        if abs(delta) < 1e-9:
            return ('flat', '→', 'steady')
        rel = abs(delta) / (abs(values[-2]) or 1.0)
        if rel < 0.01:
            return ('flat', '→', 'steady')
        return ('up', '↑', 'rising') if delta > 0 else ('down', '↓', 'falling')

    # ── UI ───────────────────────────────────────────────────────────────
    with ui.column().classes('w-full gap-4'):
        with ui.row().classes('w-full items-center justify-between'):
            with ui.column().classes('gap-1'):
                ui.label('Telemetry').classes('us-title')
                with ui.row().classes('items-center gap-2'):
                    ui.label(selected_device.name or selected_device.port).classes(
                        'us-mono us-muted')
                    ui.label('·').classes('us-muted')
                    ui.label('live').classes('us-micro').style(
                        f'color: {STATUS["live"]}')
            with ui.row().classes('items-center gap-2'):
                _btn('Edit', 'us-btn-ghost', toggle_edit)
                _btn('Add series', 'us-btn-primary',
                     _late_charts_page('show_add_widget_dialog'))

        # Live metric discovery: everything the device is reporting, grouped so
        # each group shares one axis and therefore one unit.
        dashboard_container = ui.column().classes('w-full gap-5')

    def refresh_dashboard():
        dashboard_container.clear()
        groups = available_metrics()
        widgets = dashboard_state['widgets']
        # Re-enter explicitly: clear() leaves the ambient context pointing at a
        # deleted slot, and rebuilding without this raises at runtime.
        with dashboard_container:
            if not groups:
                _charts_empty(available_metrics)
                return

            # At-a-glance header: how many metrics, across how many axes, and
            # is anything actually moving. A pill per metric here would just
            # duplicate the rows below it, which already carry value, unit,
            # sparkline and trend.
            total_series = sum(len(s) for s in groups.values())
            latest_by_name = {name: last
                              for series in groups.values()
                              for name, _v, last in series}
            moving = []
            for unit, series in groups.items():
                for name, vals, _last in series:
                    tr = _trend(vals)
                    if tr and tr[0] != 'flat':
                        moving.append((name, unit, tr))
            with ui.row().classes('w-full gap-2 flex-wrap items-center'):
                with ui.column().classes('us-metric-pill !py-2'):
                    ui.label('metrics').classes('us-micro us-muted')
                    ui.label(f'{total_series}').classes('us-mono')
                with ui.column().classes('us-metric-pill !py-2'):
                    ui.label('axes (by unit)').classes('us-micro us-muted')
                    ui.label(f'{len(groups)}').classes('us-mono')
                if moving:
                    with ui.column().classes('us-metric-pill !py-2 flex-1 min-w-0'):
                        ui.label('in motion').classes('us-micro us-muted')
                        with ui.row().classes('items-baseline gap-3 flex-wrap'):
                            for name, unit, tr in moving[:6]:
                                with ui.row().classes('items-baseline gap-1'):
                                    ui.label(tr[1]).classes('us-trend').style(
                                        f'color: {STATUS["live" if tr[0] == "up" else "info"]}')
                                    ui.label(f'{name}').classes('us-micro us-muted truncate')
                                    ui.label(_fmt(latest_by_name[name])).classes(
                                        'us-micro us-mono')
                                    if unit != '—':
                                        ui.label(unit).classes('us-micro us-muted')
                else:
                    with ui.column().classes('us-metric-pill !py-2'):
                        ui.label('in motion').classes('us-micro us-muted')
                        ui.label('all steady').classes('us-mono us-muted')

            # One block per unit. This is the fix: a Y axis only ever holds
            # series measured the same way.
            for unit, series in groups.items():
                with ui.column().classes('w-full gap-2'):
                    with ui.row().classes('items-center gap-2'):
                        # The symbol is shown verbatim (see .us-unit) but never
                        # alone: a bare "dBm" in a heading is ambiguous, so the
                        # count of series on this axis goes with it.
                        ui.label(unit).classes('us-unit')
                        ui.label(
                            'no unit reported — scale is relative only'
                            if unit == '—'
                            else f"{len(series)} series"
                        ).classes('us-micro us-muted')
                    with ui.column().classes('w-full gap-2'):
                        for name, vals, last in series:
                            pinned = name in dashboard_state['pinned']
                            _series_row(name, vals, last, unit, pinned)

            if widgets:
                ui.label('PINNED').classes('us-label us-muted mt-2')
                with ui.row().classes('w-full gap-3'):
                    for widget in widgets:
                        _render_widget(widget)

    def _series_row(name, vals, last, unit, pinned):
        """One metric: name, value, sparkline, and the actions to pin/hide."""
        with ui.row().classes('us-row w-full items-center gap-4'):
            with ui.column().classes('gap-0.5 flex-1 min-w-0'):
                with ui.row().classes('items-center gap-2'):
                    ui.label(name).classes('us-subhead truncate')
                    if pinned:
                        ui.label('pinned').classes('us-micro').style(
                            f'color: {ACCENT["text"]}')
                with ui.row().classes('items-baseline gap-2'):
                    ui.label(_fmt(last)).classes('us-mono')
                    if unit != '—':
                        ui.label(unit).classes('us-micro us-muted')
            spark = _sparkline(vals, unit)
            if spark:
                ui.label(spark).classes('us-spark')
            tr = _trend(vals)
            if tr:
                ui.label(tr[1]).classes('us-trend').style(
                    f'color: {STATUS["live" if tr[0] == "up" else "info" if tr[0] == "down" else "idle"]}')
            if dashboard_state['edit_mode']:
                _btn('Unpin' if pinned else 'Pin',
                     'us-btn-ghost',
                     lambda n=name, p=pinned: _toggle_pin(n, p))

    def _toggle_pin(name, pinned):
        if pinned:
            dashboard_state['pinned'].discard(name)
        else:
            dashboard_state['pinned'].add(name)
        refresh_dashboard()

    def _charts_empty(_getter):
        """A screen that waits on data says what it is waiting for."""
        with ui.column().classes('us-empty w-full'):
            with ui.column().classes('gap-2'):
                ui.label('Waiting for telemetry').classes('us-display')
                ui.label(
                    f'{selected_device.name or "This device"} is connected but '
                    'has not reported a metric yet. Charts appear here as '
                    'soon as the stream carries something plottable.'
                ).classes('us-body')
            ui.label(
                'A metric is recognised from a line like  TEMP:23.4  or  '
                '{"temp": 23.4}, and grouped by unit so the axis always '
                'matches the data.').classes('us-micro us-muted')

    # ── Pinned widgets (v1's dashboard builder, kept as a layer on top) ──
    def _show_add_widget_dialog_impl():
        groups = available_metrics()
        if not groups:
            ui.notify('No metrics reported yet', type='warning')
            return
        dialog = ui.dialog()
        with dialog, ui.column().classes('us-dialog w-[440px]'):
            ui.label('Pin a series').classes('us-subhead')
            ui.label(
                'Pinned series keep a fixed history of their own, independent '
                'of the live view.').classes('us-micro us-muted')
            options = [(f'{name} ({unit})', name)
                       for unit, series in groups.items()
                       for name, _v, _l in series]
            metric_select = ui.select(
                options, value=options[0][1] if options else None,
                label='Metric').classes('w-full')
            type_select = ui.select(
                ['Metric Card', 'Line Chart', 'Gauge'], value='Metric Card'
            ).classes('w-full')
            with ui.row().classes('w-full justify-end gap-2'):
                _btn('Cancel', 'us-btn-ghost', dialog.close)
                _btn('Pin', 'us-btn-primary', lambda: add_widget(
                    type_select.value, metric_select.value, dialog))
        dialog.open()

    def add_widget(widget_type, metric, dialog):
        if not metric:
            return
        widget = {
            'id': dashboard_state['next_id'],
            'type': widget_type, 'title': metric, 'metric': metric,
            'size': 'Medium', 'history': [],
        }
        dashboard_state['next_id'] += 1
        dashboard_state['widgets'].append(widget)
        dialog.close()
        ui.notify(f'Pinned {metric}', type='positive')
        refresh_dashboard()

    def remove_widget(widget_id):
        dashboard_state['widgets'] = [
            w for w in dashboard_state['widgets'] if w['id'] != widget_id]
        refresh_dashboard()

    def _render_widget(widget):
        """A pinned series. v1's widget, restyled and -- crucially -- with the
        unit attached to the value rather than dropped."""
        history = widget.get('history', [])
        unit = _unit_for(widget['metric'])
        with ui.column().classes('us-card w-[220px] gap-2'):
            with ui.row().classes('w-full items-center justify-between'):
                ui.label(widget['title']).classes('us-subhead truncate')
                if dashboard_state['edit_mode']:
                    _btn('✕', 'us-btn-ghost us-btn-danger',
                         lambda w=widget: remove_widget(w['id']))

            if widget['type'] == 'Metric Card':
                ui.label(_fmt(history[-1] if history else None)).classes(
                    'us-metric us-mono')
                if unit and unit != '—':
                    ui.label(unit).classes('us-micro us-muted')
            elif widget['type'] == 'Line Chart':
                spark = _sparkline(history, unit)
                ui.label(spark or '…').classes('us-spark')
                if history:
                    ui.label(
                        f'{_fmt(min(history[-20:]))}–{_fmt(max(history[-20:]))}'
                    ).classes('us-micro us-mono us-muted')
                else:
                    ui.label('collecting').classes('us-micro us-muted')
            elif widget['type'] == 'Gauge':
                val = history[-1] if history else None
                ui.label(_fmt(val)).classes('us-metric us-mono')
                # v1 assumed every metric was 0-100, which is only true of
                # humidity. Without a known range, show share-of-span honestly.
                if history:
                    lo, hi = min(history[-20:]), max(history[-20:])
                    rng = (hi - lo) or 1.0
                    filled = int(((val - lo) / rng) * 20)
                    ui.label('█' * max(0, min(20, filled))
                             + '░' * max(0, 20 - filled)).classes('us-micro us-mono')
            ui.label(widget['metric']).classes('us-micro us-muted truncate')

    def _unit_for(metric_name):
        groups = available_metrics()
        for unit, series in groups.items():
            for name, _v, _l in series:
                if name == metric_name:
                    return unit
        return '—'

    # ── Background update ────────────────────────────────────────────────
    async def dashboard_refresh_loop():
        while True:
            await asyncio.sleep(2)
            try:
                latest = telemetry_engine.get_latest_values(selected_device.id)
                for widget in dashboard_state['widgets']:
                    if widget['metric'] in latest:
                        widget['history'].append(latest[widget['metric']])
                        del widget['history'][:-100]
                refresh_dashboard()
            except Exception:
                # A dead refresh loop leaves a frozen chart that looks live,
                # which is worse than an error the user can see.
                logger.exception('charts refresh loop failed')
                ui.notify('Chart refresh failed', type='negative')
                return

    asyncio.create_task(dashboard_refresh_loop())
    refresh_dashboard()

def alerts_page():
    """Alerts: configure and triage.

    v1's structure was wrong in a way that made the screen unusable rather than
    merely ugly:

      * refresh_alerts() built its whole tree into the ambient context and never
        cleared it. Every acknowledgement therefore appended a second copy of
        the entire screen -- stats, rules and history -- below the first. Acking
        three alerts gave you three screens.
      * AlertRule has `enabled` and `trigger_count`, and v1 surfaced neither.
        The single most common triage action, silencing a rule that is firing
        constantly, had no control at all; the only verb offered was Delete,
        which is destructive and irreversible.
      * An unacknowledged alert and an acknowledged one looked almost the same
        (opacity 50%), so the queue you are meant to work through had no
        visible front edge.

    v2 separates the two jobs: rules are configured on the left, the alert queue
    is worked on the right, and the queue leads with what is unacknowledged.
    """
    global selected_device

    _bind_alerts_page, _late_alerts_page = _late_bindings()

    # Filter state. Triage means narrowing; the queue has to be filterable or
    # 200 acknowledged alerts bury the 2 that matter.
    view = {'severity': 'all', 'show_acked': False}

    def rules():
        return get_alert_rules()

    def events():
        """Alert history, newest first, filtered for the current view."""
        all_events = sorted(
            get_alert_events(),
            key=lambda a: a.get('timestamp', ''),
            reverse=True)
        out = []
        for a in all_events:
            if view['severity'] != 'all' and \
                    a.get('severity') != view['severity']:
                continue
            if not view['show_acked'] and a.get('acknowledged'):
                continue
            out.append(a)
        return out

    # ── UI ───────────────────────────────────────────────────────────────
    alerts_container = ui.column().classes('w-full gap-4')

    def refresh_alerts():
        # MUST re-enter the container: after clear() the ambient context still
        # points at the deleted slot.
        alerts_container.clear()
        with alerts_container:
            _alerts_summary()
            _alerts_rules()
            _alerts_queue()

    def _alerts_summary():
        all_events = get_alert_events()
        unack = [a for a in all_events if not a.get('acknowledged')]
        by_sev = {}
        for a in all_events:
            by_sev[a.get('severity', 'warning')] = \
                by_sev.get(a.get('severity', 'warning'), 0) + 1
        active = [r for r in rules() if getattr(r, 'enabled', True)]

        with ui.row().classes('w-full gap-2 flex-wrap items-center'):
            _stat('unacknowledged', str(len(unack)),
                  'error' if unack else 'idle')
            _stat('critical', str(by_sev.get('critical', 0)),
                  'error' if by_sev.get('critical') else 'idle')
            _stat('warning', str(by_sev.get('warning', 0)),
                  'warn' if by_sev.get('warning') else 'idle')
            _stat('rules active', f'{len(active)}/{len(rules())}', None)
            _stat('total alerts', str(len(all_events)), None)

    def _stat(label, value, token):
        with ui.column().classes('us-metric-pill !py-2'):
            ui.label(label).classes('us-micro us-muted')
            ui.label(value).classes('us-mono').style(
                f'color: {STATUS[token]}' if token else '')

    def _alerts_rules():
        with ui.column().classes('w-full gap-2'):
            with ui.row().classes('w-full items-center justify-between'):
                ui.label('Rules').classes('us-label us-muted')
                _btn('New rule', 'us-btn-primary',
                     _late_alerts_page('show_add_rule_dialog'))

            all_rules = rules()
            if not all_rules:
                with ui.column().classes('us-empty w-full'):
                    with ui.column().classes('gap-2'):
                        ui.label('No rules yet').classes('us-subhead')
                        ui.label(
                            'A rule watches one metric and raises an alert when '
                            'it crosses a threshold. Without one, nothing is '
                            'evaluated against the stream.'
                        ).classes('us-body')
                    _suggest_rules()
                return

            with ui.column().classes('w-full gap-2'):
                for rule in all_rules:
                    _rule_row(rule)

    def _suggest_rules():
        """Offer rules for metrics that actually exist, rather than an empty form.

        The form asks for a metric name by free text, so a typo creates a rule
        that can never fire and the user has no way to tell.
        """
        names = []
        if selected_device is not None:
            try:
                names = sorted(
                    telemetry_engine.get_all_metrics(selected_device.id) or {})
            except Exception:
                names = []
        if names:
            ui.label(
                f'Available on {selected_device.name or "this device"}: '
                + ', '.join(names[:6])).classes('us-micro us-muted')

    def _rule_row(rule):
        token = severity_token(rule.severity)
        enabled = getattr(rule, 'enabled', True)
        with ui.column().classes(
                f'us-row w-full items-center gap-4 '
                f'{"us-row-dim" if not enabled else ""}'):
            ui.html(f'<span class="us-dot us-dot-{token}">')
            with ui.column().classes('gap-0.5 flex-1 min-w-0'):
                with ui.row().classes('items-center gap-2'):
                    ui.label(rule.name).classes('us-subhead truncate')
                    if not enabled:
                        ui.label('silenced').classes('us-micro us-muted')
                with ui.row().classes('items-baseline gap-2 flex-wrap'):
                    ui.label(
                        f"{rule.metric_name} {rule.condition} {rule.threshold}"
                    ).classes('us-mono us-micro us-muted')
                    ui.label(f'· {rule.severity}').classes('us-micro us-muted')
                    # cooldown 0 means "no cooldown", not "every zero seconds";
                    # printing it as-is was both wrong and confusing.
                    if rule.cooldown:
                        ui.label(f'· every {rule.cooldown}s').classes(
                            'us-micro us-muted')
                    else:
                        ui.label('· no cooldown').classes('us-micro us-muted')
                    triggered = getattr(rule, 'trigger_count', 0)
                    if triggered:
                        # A rule that has fired a lot is the one worth looking at.
                        ui.label(f'· fired {triggered}×').classes(
                            'us-micro').style(f'color: {STATUS[token]}')
            with ui.row().classes('items-center gap-2'):
                _btn('Silence' if enabled else 'Unsilence', 'us-btn-ghost',
                     lambda r=rule, e=enabled: _toggle_rule(r, e))
                _btn('Delete', 'us-btn-ghost us-btn-danger',
                     lambda r=rule: _delete_rule(r))

    def _toggle_rule(rule, enabled):
        rule.enabled = not enabled
        ui.notify(
            f"{rule.name}: {'silenced' if not enabled else 'active'}",
            type='info')
        refresh_alerts()

    async def _delete_rule(rule):
        alert_engine.remove_rule(rule.id)
        ui.notify(f"Deleted rule '{rule.name}'", type='info')
        refresh_alerts()

    def _alerts_queue():
        with ui.column().classes('w-full gap-2'):
            with ui.row().classes('w-full items-center justify-between gap-3'):
                ui.label('Queue').classes('us-label us-muted')
                with ui.row().classes('items-center gap-2'):
                    sev = ui.select(
                        ['all', 'critical', 'warning', 'info'], value='all'
                    ).classes('w-28 us-input').props('outlined dense')
                    sev.bind_value(view, 'severity')
                    sev.on_value_change(lambda: refresh_alerts())
                    _btn('Show acked', 'us-btn-ghost', _toggle_acked)
                    unacked = [a for a in get_alert_events()
                               if not a.get('acknowledged')]
                    if unacked:
                        _btn('Ack all', 'us-btn-secondary',
                             _late_alerts_page('ack_all'))

            shown = events()
            if not shown:
                if view['show_acked']:
                    ui.label('Nothing matches this filter.').classes(
                        'us-body us-muted')
                else:
                    with ui.column().classes('us-empty w-full'):
                        with ui.column().classes('gap-2'):
                            ui.label('Queue is clear').classes('us-subhead')
                            ui.label(
                                'No unacknowledged alerts. New ones appear here '
                                'as the stream crosses a rule threshold.'
                            ).classes('us-body')
                        _btn('Show acknowledged', 'us-btn-ghost', _toggle_acked)
                return

            with ui.column().classes('w-full gap-1'):
                for a in shown[:100]:
                    _alert_row(a)
            if len(shown) > 100:
                ui.label(
                    f'{len(shown) - 100:,} older alerts not shown — narrow the '
                    f'filter').classes('us-micro us-muted')

    def _toggle_acked():
        view['show_acked'] = not view['show_acked']
        refresh_alerts()

    def _alert_row(alert):
        token = severity_token(alert.get('severity'))
        acked = alert.get('acknowledged', False)
        ts = (alert.get('timestamp') or '')[:19].replace('T', ' ')
        with ui.row().classes(
                f'us-row w-full items-center gap-3 '
                f'{"us-row-acked" if acked else ""}'):
            ui.html(f'<span class="us-dot us-dot-{token}">')
            with ui.column().classes('gap-0.5 flex-1 min-w-0'):
                with ui.row().classes('items-baseline gap-2 flex-wrap'):
                    ui.label(alert.get('metric_name') or '—').classes(
                        'us-mono us-micro us-muted')
                    ui.label(ts).classes('us-mono us-micro us-muted')
                ui.label(alert.get('message', '')).classes(
                    f'us-body truncate {"line-through" if acked else ""}')
            if acked:
                ui.label('✓ acknowledged').classes('us-micro us-muted')
            else:
                _btn('Ack', 'us-btn-secondary',
                     lambda a=alert: _ack_one(a))

    async def _ack_one(alert):
        alert_engine.acknowledge_alert(alert.get('id', ''))
        refresh_alerts()

    async def _ack_all_impl():
        # Acknowledge the same set the queue is showing, not the entire history:
        # "Ack all" under an active filter must mean "all of these".
        for alert in events():
            alert_engine.acknowledge_alert(alert.get('id', ''))
        ui.notify('Acknowledged', type='info')
        refresh_alerts()

    # ── New rule dialog ──────────────────────────────────────────────────
    def _show_add_rule_dialog_impl():
        dialog = ui.dialog()
        with dialog, ui.column().classes('us-dialog w-[460px]'):
            ui.label('New alert rule').classes('us-subhead')
            name_input = ui.input('Name', value='').classes('w-full')
            metric_input = ui.input('Metric', value='TEMP').classes('w-full')
            condition = ui.select(['>', '<', '>=', '<=', '=='], value='>').classes(
                'w-full')
            threshold = ui.input('Threshold', value='80').classes('w-full')
            severity = ui.select(
                ['warning', 'critical', 'info'], value='warning').classes('w-full')
            cooldown = ui.select(
                {'10s': 10, '30s': 30, '60s': 60, '300s': 300, '900s': 900},
                value=60, label='Cooldown').classes('w-full')
            with ui.row().classes('w-full justify-end gap-2'):
                _btn('Cancel', 'us-btn-ghost', dialog.close)
                _btn('Create', 'us-btn-primary', lambda: _create_rule(
                    name_input.value, metric_input.value, condition.value,
                    threshold.value, severity.value, cooldown.value, dialog))
        dialog.open()

    def _create_rule(name, metric, condition, threshold, severity, cooldown,
                     dialog):
        metric = (metric or '').strip().upper()
        if not metric:
            ui.notify('A rule needs a metric name', type='warning')
            return
        try:
            value = float(threshold)
        except (TypeError, ValueError):
            ui.notify('Threshold must be a number', type='warning')
            return
        rule = AlertRule(
            id=str(uuid.uuid4()),
            name=(name or '').strip() or f'{metric} {condition} {value:g}',
            metric_name=metric,
            condition=condition,
            threshold=value,
            cooldown=int(cooldown or 60),
            severity=severity,
        )
        alert_engine.add_rule(rule)
        dialog.close()
        ui.notify(f"Rule '{rule.name}' created", type='positive')
        refresh_alerts()

    # ── New-alert polling ────────────────────────────────────────────────
    # Notify only. The queue itself re-renders on interaction; polling it every
    # 2s would fight the user mid-acknowledgement and rebuild the page under
    # their cursor.
    async def check_new_alerts():
        last = len(get_alert_events())
        while True:
            await asyncio.sleep(2)
            try:
                current = get_alert_events()
            except Exception:
                logger.exception('alert poll failed')
                continue
            if len(current) > last:
                for a in current[last:]:
                    if not a.get('acknowledged'):
                        token = severity_token(a.get('severity'))
                        ui.notify(a.get('message') or 'Alert', type=(
                            'negative' if token == 'error'
                            else 'warning' if token == 'warn' else 'info'),
                            timeout=6000)
            last = len(current)

    asyncio.create_task(check_new_alerts())
    refresh_alerts()

def sessions_page():
    """Session list view."""
    def refresh_sessions():
        sessions = get_sessions()

        with ui.row().classes('w-full gap-3 mb-4'):
            recording = len([s for s in sessions if s.get('status') == 'recording'])
            for label, val in [('Recording', recording), ('Total', len(sessions))]:
                with ui.card().classes('flex-1 p-4') \
                    .style('background: #16181d; border-left: 2px solid #5c8af0'):
                    ui.label(str(val)).classes('text-xl font-medium text-white')
                    ui.label(label).classes('text-[10px] text-[#71717a] uppercase tracking-widest')

        if not sessions:
            with ui.card().classes('w-full p-12 text-center') \
                .style('background: #16181d; border-left: 2px solid #5c8af0'):
                ui.label('⟳').classes('text-4xl text-[#5c8af0] mb-2')
                ui.label('No sessions yet').classes('text-[#e4e4e7] font-medium')
                ui.label('Start streaming to create sessions').classes('text-[#52525b] text-sm')
        else:
            with ui.column().classes('w-full gap-3 p-6 max-w-[1400px] mx-auto'):
                for session in reversed(sessions):
                    with ui.card().classes('w-full p-4 cursor-pointer hover:border-[rgba(255,255,255,0.12)]') \
                        .style('background: #16181d; border-left: 2px solid #5c8af0') \
                        .on('click', lambda s=session: open_session(s)):
                        with ui.row().classes('w-full items-center justify-between mb-3'):
                            with ui.row().classes('items-center gap-3'):
                                is_live = session.get('status') == 'recording'
                                ui.label('●').classes('text-xs').style(f'color: {"#22c55e" if is_live else "#52525b"}')
                                with ui.column().classes('gap-0.5'):
                                    ui.label(session.get('name', 'Unnamed')).classes('text-white font-medium text-sm')
                                    ui.label(f"{session.get('packet_count', 0)} pkts · {session.get('metric_count', 0)} metrics").classes('text-[#52525b] text-xs font-mono')
                            with ui.row().classes('items-center gap-2'):
                                if is_live:
                                    ui.label('● LIVE').classes('text-[#22c55e] text-xs font-medium')
                                ui.label(format_duration(session.get('started_at', ''), session.get('ended_at'))).classes('text-[#71717a] text-xs font-mono')

    def open_session(session):
        global selected_session, current_tab
        selected_session = session
        current_tab = 'session-detail'
        rebuild()

    refresh_sessions()


def session_detail_page():

    _bind_session_detail_page, _late_session_detail_page = _late_bindings()
    """Session detail with timeline replay."""
    global selected_session

    if not selected_session:
        ui.label('No session selected').classes('text-[#52525b]').style('padding: 40px')
        return

    session = selected_session

    with ui.column().classes('w-full gap-4'):
        with ui.row().classes('w-full items-center gap-3'):
            ui.button('← Back', on_click=_late_session_detail_page('go_back')).classes('bg-[rgba(255,255,255,0.03)] text-[#71717a] border border-[rgba(255,255,255,0.10)] px-3 py-1 text-sm rounded-lg')
            with ui.column():
                ui.label(session.get('name', 'Unnamed')).classes('text-white font-medium')
                ui.label(f"{session.get('packet_count', 0)} packets").classes('text-[#52525b] text-xs')

        # Tabs
        tabs = ui.tabs().classes('w-full')
        with tabs:
            t1 = ui.tab('Timeline')
            t2 = ui.tab('Metrics')
            t3 = ui.tab('Export')
            t4 = ui.tab('🧪 Diff Test')

        with ui.tab_panels(tabs, value=t1).classes('w-full p-0'):
            with ui.tab_panel(t1):
                with ui.column().classes('w-full gap-4 p-6 max-w-[1400px] mx-auto'):
                    with ui.row().classes('w-full items-center gap-3'):
                        ui.button('▶ Replay', on_click=_late_session_detail_page('start_replay')).classes('bg-[#5c6fd0] text-white px-3 py-1 text-sm rounded-lg')
                        ui.select([0.5, 1, 2, 5, 10], value=1).classes('bg-[rgba(255,255,255,0.02)] text-[#e4e4e7] border border-[rgba(255,255,255,0.10)] px-2 py-1 text-sm rounded-lg')
                        ui.label(f"0 packets").classes('text-[#71717a] text-xs font-mono')

                    ui.label('Timeline replay coming soon').classes('text-[#52525b] text-sm py-4')

            with ui.tab_panel(t2):
                ui.label('Metrics chart coming soon').classes('text-[#52525b] py-8')

            with ui.tab_panel(t3):
                with ui.column().classes('w-full gap-4 p-6 max-w-[1400px] mx-auto'):
                    ui.label('Export & Share').classes('text-white font-medium')
                    with ui.row().classes('w-full gap-2'):
                        ui.button('Export JSON', on_click=lambda: export_json()).classes('bg-[#5c6fd0] text-white px-4 py-2 rounded-lg flex-1')
                        ui.button('Export CSV', on_click=lambda: export_csv()).classes('bg-[rgba(255,255,255,0.03)] text-[#71717a] border border-[rgba(255,255,255,0.10)] px-4 py-2 rounded-lg flex-1')
                    ui.button('📦 Share Bundle (.uartscope)', on_click=lambda: export_bundle()).classes('bg-[#5c8af0] text-white px-4 py-2 rounded-lg w-full')

                    ui.label('Sharing exports session metadata + metrics. Does NOT include raw serial data. Others can open the bundle to view the session.').classes('text-[#52525b] text-[10px]')

            def export_json():
                filename = f"session_{session.get('session_id', 'unknown')[:8]}.json"
                data = {
                    'session': session,
                    'metrics': {},
                }
                for mn, hist in telemetry_engine.get_all_metrics(session.get('device_id', '')).items():
                    data['metrics'][mn] = [{'timestamp': m.timestamp.isoformat(), 'name': m.name, 'value': m.value, 'unit': m.unit} for m in hist]
                raw = json.dumps(data, indent=2, default=str).encode()
                ui.download.bytes(raw, filename)
                ui.notify(f'Exported: {filename}', type='positive')

            def export_csv():
                import io
                output = io.StringIO()
                output.write('timestamp,metric,value,unit\n')
                for mn, history in telemetry_engine.get_all_metrics(session.get('device_id', '')).items():
                    for m in history:
                        output.write(f"{m.timestamp.isoformat()},{m.name},{m.value},{m.unit or ''}\n")
                raw = output.getvalue().encode()
                ui.download.bytes(raw, f"session_{session.get('session_id', 'unknown')[:8]}.csv")
                ui.notify('CSV exported', type='positive')

            def export_bundle():
                import os, zipfile, io
                descriptor = {
                    'version': '1.0',
                    'type': 'uartscope-session',
                    'session': {k: v for k, v in session.items()},
                    'metrics': {},
                }
                for mn, hist in telemetry_engine.get_all_metrics(session.get('device_id', '')).items():
                    descriptor['metrics'][mn] = [{'timestamp': m.timestamp.isoformat(), 'name': m.name, 'value': m.value, 'unit': m.unit} for m in hist]

                # Build zip in memory
                zip_buffer = io.BytesIO()
                with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
                    zf.writestr('session.json', json.dumps(descriptor, indent=2, default=str))
                    csv_output = io.StringIO()
                    csv_output.write('timestamp,metric,value,unit\n')
                    for mn, hist in descriptor['metrics'].items():
                        for m_dict in hist:
                            csv_output.write(f"{m_dict['timestamp']},{m_dict['name']},{m_dict['value']},{m_dict.get('unit', '')}\n")
                    zf.writestr('metrics.csv', csv_output.getvalue())

                ui.download.bytes(zip_buffer.getvalue(), f"session_{session.get('session_id', 'unknown')[:8]}.uartscope")
                ui.notify('Bundle exported!', type='positive')

            with ui.tab_panel(t4):
                # Golden Session Diff Tab
                with ui.column().classes('w-full gap-4'):
                    ui.label('Automated Session Diff').classes('text-white font-medium')
                    ui.label('Mark this session as "golden" (expected behavior), then compare new sessions against it. Perfect for CI pipelines.').classes('text-[#71717a] text-xs')

                    with ui.row().classes('w-full gap-3 items-center'):
                        golden_status = ui.label('⚪ No golden session set').classes('text-[#52525b] text-sm flex-1')
                        ui.button('⭐ Mark as Golden', on_click=lambda: mark_as_golden()).classes('bg-[#eab308] text-white px-3 py-1.5 text-sm rounded-lg')

                    # Diff criteria
                    with ui.card().classes('w-full p-4').style('background: #16181d; border-left: 2px solid #5c8af0'):
                        ui.label('Diff Criteria').classes('text-white font-medium text-sm mb-2')
                        check_metrics = ui.checkbox('Compare metric values', value=True).classes('text-[#71717a] text-xs')
                        check_packet_count = ui.checkbox('Compare packet counts', value=True).classes('text-[#71717a] text-xs')
                        check_errors = ui.checkbox('Compare error patterns', value=True).classes('text-[#71717a] text-xs')
                        tolerance = ui.number('Tolerance (%)', value=5, min=0, max=100).classes('w-full mb-2').props('outlined dense').style('color: #e4e4e7')

                    # Compare button
                    ui.button('🧪 Run Diff Against Golden', on_click=lambda: run_diff()).classes('bg-[#5c8af0] text-white px-4 py-2 rounded-lg w-full')

                    # Diff results area
                    diff_results = ui.column().classes('w-full gap-3 p-6 max-w-[1400px] mx-auto')

        # Diff functions (defined in outer scope)
        current_packets = session.get('packet_count', 0)
        golden_data = {'packet_count': 0, 'metrics': {}, 'error_count': 0, 'metric_samples': {}}

        def mark_as_golden():
            golden_data['packet_count'] = session.get('packet_count', 0)
            golden_data['name'] = session.get('name', '')
            golden_data['metrics'] = session.get('metrics_latest', {})
            golden_data['error_count'] = session.get('error_count', 0)
            golden_data['metric_samples'] = {}
            golden_status.text = f"⭐ Golden: {golden_data['name']} ({golden_data['packet_count']} pkts)"
            ui.notify(f"Session marked as golden ({golden_data['packet_count']} packets)", type='positive')

        def run_diff():
            diff_results.clear()
            tolerance_val = tolerance.value / 100.0
            passed = True
            results = []

            # Compare packet counts
            if check_packet_count.value:
                expected = golden_data['packet_count']
                actual = current_packets
                diff_pct = abs(actual - expected) / max(expected, 1) * 100
                match = diff_pct <= (tolerance_val * 100)
                passed = passed and match
                results.append({
                    'name': 'Packet Count',
                    'expected': str(expected),
                    'actual': str(actual),
                    'diff': f"{diff_pct:.1f}%",
                    'pass': match,
                })

            # Compare metrics (latest values)
            if check_metrics.value:
                current_metrics = session.get('metrics_latest', {})
                golden_metrics = golden_data.get('metrics', {})
                for metric_name, golden_val in golden_metrics.items():
                    if isinstance(golden_val, (int, float)):
                        current_val = current_metrics.get(metric_name, 0)
                        if isinstance(current_val, (int, float)):
                            if golden_val != 0:
                                pct_diff = abs(current_val - golden_val) / abs(golden_val) * 100
                            else:
                                pct_diff = 0 if current_val == 0 else 100
                            match = pct_diff <= (tolerance_val * 100)
                            passed = passed and match
                            results.append({
                                'name': f"Metric: {metric_name}",
                                'expected': f"{golden_val}",
                                'actual': f"{current_val}",
                                'diff': f"{pct_diff:.1f}%",
                                'pass': match,
                            })

            # Compare error counts
            if check_errors.value:
                golden_errors = golden_data['error_count']
                current_errors = session.get('error_count', 0)
                match = current_errors == golden_errors
                passed = passed and match
                results.append({
                    'name': 'Error Count',
                    'expected': str(golden_errors),
                    'actual': str(current_errors),
                    'diff': '0' if match else f"+{current_errors - golden_errors}",
                    'pass': match,
                })

            # Render results
            with diff_results:
                if passed:
                    with ui.card().classes('w-full p-3').style('background: rgba(39,166,68,0.1); border: 1px solid rgba(39,166,68,0.3)'):
                        ui.label('✅ ALL CHECKS PASSED').classes('text-[#22c55e] font-medium')
                else:
                    with ui.card().classes('w-full p-3').style('background: rgba(229,72,77,0.1); border: 1px solid rgba(229,72,77,0.3)'):
                        ui.label('❌ TEST FAILED').classes('text-[#ef4444] font-medium')

                for r in results:
                    color = '#22c55e' if r['pass'] else '#ef4444'
                    icon = '✓' if r['pass'] else '✗'
                    with ui.row().classes('w-full items-center gap-3 p-2 rounded-lg').style('background: rgba(255,255,255,0.01)'):
                        ui.label(icon).style(f'color: {color}').classes('text-sm')
                        ui.label(r['name']).classes('text-[#e4e4e7] text-xs flex-1')
                        ui.label(f"Expected: {r['expected']}").classes('text-[#71717a] text-xs font-mono')
                        ui.label(f"Actual: {r['actual']}").classes('text-[#e4e4e7] text-xs font-mono')
                        ui.label(f"Δ {r['diff']}").style(f'color: {color}').classes('text-xs font-mono')

    def _go_back_impl():
        global current_tab, selected_session
        current_tab = 'sessions'
        selected_session = None
        rebuild()

    _bind_session_detail_page('go_back', _go_back_impl)

    async def _start_replay_impl():
        ui.notify('Replay started', type='info')


    _bind_session_detail_page('start_replay', _start_replay_impl)
def performance_page():
    """Performance Analytics - packet rate, throughput, latency, errors, uptime."""
    def refresh_performance():
        summary = performance_tracker.get_summary()
        snapshot = performance_tracker.get_global_snapshot()
        all_perf = performance_tracker.get_all_perf()

        # Main stats row
        with ui.row().classes('w-full gap-3 mb-4'):
            for label, val, color in [
                ('Current PPS', f"{snapshot.get('current_packet_rate', 0):.1f}", '#5c8af0'),
                ('Throughput', format_bytes(snapshot.get('current_throughput', 0)) + '/s', '#22c55e'),
                ('Avg Latency', f"{snapshot.get('avg_latency_ms', 0):.1f} ms", '#eab308'),
                ('Total Errors', str(summary.get('total_errors', 0)), '#ef4444'),
                ('Error Rate', f"{summary.get('error_rate_per_min', 0):.1f}/min", '#ef4444'),
            ]:
                with ui.card().classes('flex-1 p-4') \
                    .style('background: #16181d; border-left: 2px solid #5c8af0'):
                    ui.label(str(val)).classes('text-lg font-medium font-mono').style(f'color: {color}')
                    ui.label(label).classes('text-[10px] text-[#71717a] uppercase tracking-widest')

        # Aggregate totals
        with ui.row().classes('w-full gap-3 mb-4'):
            for label, val in [
                ('Total Packets', f"{summary.get('total_packets', 0):,}"),
                ('Total Data', format_bytes(summary.get('total_bytes', 0))),
                ('Avg PPS', f"{summary.get('avg_packet_rate', 0):.1f}"),
                ('Avg Throughput', format_bytes(summary.get('avg_throughput', 0)) + '/s'),
                ('Uptime', format_duration(None, None, seconds=summary.get('total_uptime_seconds', 0))),
            ]:
                with ui.card().classes('flex-1 p-4') \
                    .style('background: #16181d; border-left: 2px solid #5c8af0'):
                    ui.label(str(val)).classes('text-lg font-medium text-white font-mono')
                    ui.label(label).classes('text-[10px] text-[#71717a] uppercase tracking-widest')

        # Per-device performance table
        with ui.card().classes('w-full p-4 mb-4').style('background: #16181d; border-left: 2px solid #5c8af0'):
            ui.label('Per-Device Performance').classes('text-white font-medium mb-3')

            if not all_perf:
                ui.label('No device data yet').classes('text-[#52525b] text-sm py-4')
            else:
                # Table
                with ui.table({
                    'columns': [
                        {'name': 'device', 'label': 'Device', 'field': 'name', 'align': 'left', 'classes': 'text-[#71717a] text-xs'},
                        {'name': 'status', 'label': 'Status', 'field': 'status', 'align': 'left'},
                        {'name': 'uptime', 'label': 'Uptime', 'field': 'uptime', 'align': 'right'},
                        {'name': 'packets', 'label': 'Packets', 'field': 'packets', 'align': 'right'},
                        {'name': 'data', 'label': 'Data', 'field': 'data', 'align': 'right'},
                        {'name': 'pps', 'label': 'PPS', 'field': 'pps', 'align': 'right'},
                        {'name': 'throughput', 'label': 'Throughput', 'field': 'throughput', 'align': 'right'},
                        {'name': 'latency', 'label': 'Latency', 'field': 'latency', 'align': 'right'},
                        {'name': 'errors', 'label': 'Errors', 'field': 'errors', 'align': 'right'},
                    ],
                    'rows': [],
                    'row_key': 'id',
                }) as perf_table:
                    rows = []
                    for dev_id, p in all_perf.items():
                        is_connected = p.connected_at and not p.disconnected_at
                        rows.append({
                            'id': dev_id,
                            'name': p.device_name or dev_id,
                            'status': '● LIVE' if is_connected else '○ OFF',
                            'uptime': _fmt_uptime(p.uptime_seconds),
                            'packets': f"{p.total_packets:,}",
                            'data': format_bytes(p.total_bytes),
                            'pps': f"{p.current_packet_rate:.1f}",
                            'throughput': format_bytes(int(p.current_throughput)) + '/s',
                            'latency': f"{p.avg_latency_ms:.1f}ms",
                            'errors': str(p.error_count),
                        })
                    perf_table.rows = rows
                    # Style status column
                    perf_table.props('separator=cell')

        # Latency sparkline (text-based mini chart)
        with ui.card().classes('w-full p-4').style('background: #16181d; border-left: 2px solid #5c8af0'):
            with ui.row().classes('w-full items-center justify-between mb-3'):
                ui.label('Latency Distribution (last 100 samples)').classes('text-white font-medium')
                ui.label(f"Avg: {summary.get('avg_latency_ms', 0):.1f}ms").classes('text-[#52525b] text-xs font-mono')

            # Collect all latency samples
            all_latencies = []
            for p in all_perf.values():
                all_latencies.extend(p.latencies)

            if all_latencies:
                # Build histogram (10 buckets)
                lat_max = max(all_latencies)
                lat_min = min(all_latencies)
                bucket_count = 10
                bucket_width = (lat_max - lat_min) / bucket_count if lat_max > lat_min else 1
                buckets = [0] * bucket_count
                for lat in all_latencies:
                    idx = min(int((lat - lat_min) / bucket_width), bucket_count - 1) if bucket_width > 0 else 0
                    buckets[idx] += 1

                max_bucket = max(buckets) if buckets else 1
                with ui.row().classes('w-full items-end gap-1').style('height: 80px'):
                    for i, count in enumerate(buckets):
                        height_pct = (count / max_bucket) * 100 if max_bucket > 0 else 0
                        label_text = f"{lat_min + i * bucket_width:.0f}"
                        with ui.column().classes('flex-1 items-center gap-0.5'):
                            ui.label(str(count)).classes('text-[#52525b] text-[9px] font-mono').style('height: 12px')
                            ui.label('█').classes('text-[#5c8af0]').style(f'font-size: {max(8, height_pct * 0.6):.0f}px; line-height: 1')
                            ui.label(label_text).classes('text-[#52525b] text-[8px] font-mono')
            else:
                ui.label('No latency data yet').classes('text-[#52525b] text-sm py-4')

    def _fmt_uptime(seconds):
        if seconds < 60: return f"{seconds:.0f}s"
        if seconds < 3600: return f"{seconds/60:.1f}m"
        return f"{seconds/3600:.1f}h"

    # Poll for updates
    async def perf_refresh_loop():
        while True:
            await asyncio.sleep(3)
            refresh_performance()

    asyncio.create_task(perf_refresh_loop())
    refresh_performance()


def mqtt_page():

    _bind_mqtt_page, _late_mqtt_page = _late_bindings()
    """MQTT Integration - broker connections, subscriptions, message history."""
    import time as _time

    def refresh_mqtt():
        profiles = mqtt_manager.get_all_profiles()
        stats = mqtt_manager.get_stats()
        messages = mqtt_manager.get_message_history(limit=50)

        # Stats bar
        with ui.row().classes('w-full gap-3 mb-4'):
            for label, val, color in [
                ('Connections', f"{stats.get('connected', 0)}/{stats.get('total_connections', 0)}", '#5c8af0'),
                ('Messages', str(stats.get('total_messages', 0)), '#22c55e'),
                ('Data', format_bytes(stats.get('total_bytes', 0)), '#eab308'),
                ('History', str(stats.get('history_size', 0)), '#71717a'),
            ]:
                with ui.card().classes('flex-1 p-4') \
                    .style('background: #16181d; border-left: 2px solid #5c8af0'):
                    ui.label(str(val)).classes('text-lg font-medium font-mono').style(f'color: {color}')
                    ui.label(label).classes('text-[10px] text-[#71717a] uppercase tracking-widest')

        # Connection profiles
        with ui.card().classes('w-full p-4 mb-4').style('background: #16181d; border-left: 2px solid #5c8af0'):
            with ui.row().classes('w-full items-center justify-between mb-3'):
                ui.label('Broker Connections').classes('text-white font-medium')
                ui.button('+ Add Broker', on_click=_late_mqtt_page('show_add_broker_dialog')).classes('bg-[#5c6fd0] text-white px-3 py-1 text-sm rounded-lg')

            if not profiles:
                ui.label('No MQTT connections configured').classes('text-[#52525b] text-sm py-4')
            else:
                with ui.column().classes('w-full gap-3 p-6 max-w-[1400px] mx-auto'):
                    for profile in profiles:
                        with ui.card().classes('w-full p-3').style('background: rgba(255,255,255,0.01); border: 1px solid rgba(255,255,255,0.06)'):
                            with ui.row().classes('w-full items-center justify-between mb-3'):
                                with ui.row().classes('items-center gap-3'):
                                    sc = '#22c55e' if profile.connected else '#52525b'
                                    ui.label(' ').classes('inline-block w-2 h-2 rounded-full').style(f'background: {sc}')
                                    with ui.column().classes('gap-0.5'):
                                        ui.label(profile.name).classes('text-white font-medium text-sm')
                                        ui.label(f"{profile.broker}:{profile.port}").classes('text-[#52525b] text-xs font-mono')
                                with ui.row().classes('items-center gap-2'):
                                    ui.label(f"{profile.messages_received} msgs").classes('text-[#52525b] text-xs font-mono')
                                    if profile.connected:
                                        ui.button('Disconnect', on_click=lambda p=profile: disconnect_broker(p)).classes('bg-[#ef4444] text-white px-2 py-0.5 text-xs rounded')
                                    else:
                                        ui.button('Connect', on_click=lambda p=profile: connect_broker(p)).classes('bg-[#22c55e] text-white px-2 py-0.5 text-xs rounded')
                                    ui.button('Delete', on_click=lambda p=profile: delete_broker(p)).classes('bg-[rgba(229,72,77,0.1)] text-[#ef4444] px-2 py-0.5 text-xs rounded')

        # Subscriptions + Publish panel
        if profiles:
            with ui.row().classes('w-full gap-3 mb-4'):
                # Subscriptions
                with ui.card().classes('flex-1 p-4').style('background: #16181d; border-left: 2px solid #5c8af0'):
                    ui.label('Subscriptions').classes('text-white font-medium mb-2')
                    with ui.column().classes('w-full gap-0.5'):
                        for profile in profiles:
                            if profile.subscribed_topics:
                                for topic in profile.subscribed_topics:
                                    with ui.row().classes('items-center gap-2 p-1.5 rounded').style('background: rgba(255,255,255,0.01)'):
                                        ui.label('📡').classes('text-xs')
                                        ui.label(topic).classes('text-[#e4e4e7] text-xs font-mono flex-1')
                                        ui.button('✕', on_click=lambda p=profile, t=topic: unsubscribe_topic(p, t)).classes('text-[#ef4444] text-xs px-1')

                # Publish panel
                with ui.card().classes('flex-1 p-4').style('background: #16181d; border-left: 2px solid #5c8af0'):
                    ui.label('Publish Message').classes('text-white font-medium mb-2')
                    pub_profile = ui.select(
                        {p.id: p.name for p in profiles if p.connected},
                        label='Connection',
                        value=profiles[0].id if profiles else None,
                    ).classes('w-full mb-2').props('outlined').style('color: #e4e4e7')
                    pub_topic = ui.input('Topic', value='command').classes('w-full mb-2').props('outlined').style('color: #e4e4e7')
                    pub_payload = ui.textarea('Payload (JSON or text)', value='{"cmd": "status"}').classes('w-full mb-2').props('outlined').style('color: #e4e4e7; font-family: monospace')
                    ui.button('Publish', on_click=lambda: do_publish(pub_profile.value, pub_topic.value, pub_payload.value)).classes('bg-[#5c6fd0] text-white px-4 py-1.5 text-sm rounded-lg w-full')

        # Message history
        with ui.card().classes('w-full p-4').style('background: #16181d; border-left: 2px solid #5c8af0'):
            ui.label('Message History (last 50)').classes('text-white font-medium mb-3')
            if not messages:
                ui.label('No messages yet. Connect to an MQTT broker to receive data.').classes('text-[#52525b] text-sm py-4')
            else:
                with ui.column().classes('w-full gap-1 max-h-72 overflow-y-auto'):
                    for msg in reversed(messages):
                        with ui.row().classes('w-full items-start gap-2 p-2 rounded-lg').style('background: rgba(255,255,255,0.01)'):
                            ui.label(msg.timestamp.strftime('%H:%M:%S')).classes('text-[#52525b] text-xs font-mono')
                            ui.label(msg.topic).classes('text-[#5c8af0] text-xs font-mono min-w-32')
                            ui.label(msg.payload[:80]).classes('text-[#e4e4e7] text-xs flex-1 font-mono')

    # Actions
    def _show_add_broker_dialog_impl():
        dialog = ui.dialog()
        with dialog, ui.card().classes('p-6 w-96').style('background: #16181d; border: 1px solid rgba(255,255,255,0.10)'):
            ui.label('Add MQTT Broker').classes('text-white font-medium mb-4 text-lg')
            name = ui.input('Name', value='My Broker').classes('mb-2 w-full').props('outlined').style('color: #e4e4e7')
            broker = ui.input('Broker Host', value='broker.hivemq.com').classes('mb-2 w-full').props('outlined').style('color: #e4e4e7')
            port = ui.number('Port', value=1883).classes('mb-2 w-full').props('outlined').style('color: #e4e4e7')
            topic_prefix = ui.input('Topic Prefix', value='uartscope').classes('mb-2 w-full').props('outlined').style('color: #e4e4e7')
            username = ui.input('Username (optional)').classes('mb-2 w-full').props('outlined').style('color: #e4e4e7')
            password = ui.input('Password (optional)').classes('mb-2 w-full').props('outlined').style('color: #e4e4e7')
            with ui.row().classes('gap-2 justify-end w-full mt-4'):
                ui.button('Cancel', on_click=dialog.close).props('flat').classes('text-[#71717a]')
                ui.button('Add', on_click=lambda: create_broker(
                    name.value, broker.value, int(port.value), topic_prefix.value,
                    username.value or None, password.value or None, dialog
                )).classes('bg-[#5c6fd0] text-white px-4 py-2 rounded-lg')

    _bind_mqtt_page('show_add_broker_dialog', _show_add_broker_dialog_impl)

    async def create_broker(name, broker, port, topic_prefix, username, password, dialog):
        from app.core.mqtt_client import MQTTConnectionProfile
        profile = MQTTConnectionProfile(
            name=name, broker=broker, port=port, topic_prefix=topic_prefix,
            username=username, password=password,
        )
        mqtt_manager.add_profile(profile)
        dialog.close()
        ui.notify(f"Broker '{name}' added", type='positive')
        refresh_mqtt()

    async def connect_broker(profile):
        ui.notify(f"Connecting to {profile.name}...", type='info')
        success = await mqtt_manager.connect(profile.id)
        if success:
            ui.notify(f"Connected to {profile.name}", type='positive')
        else:
            ui.notify(f"Failed to connect: {profile.last_error}", type='negative')
        refresh_mqtt()

    async def disconnect_broker(profile):
        await mqtt_manager.disconnect(profile.id)
        ui.notify(f"Disconnected from {profile.name}", type='info')
        refresh_mqtt()

    async def delete_broker(profile):
        mqtt_manager.remove_profile(profile.id)
        ui.notify(f"Deleted {profile.name}", type='info')
        refresh_mqtt()

    async def unsubscribe_topic(profile, topic):
        await mqtt_manager.unsubscribe(profile.id, topic)
        refresh_mqtt()

    async def do_publish(profile_id, topic, payload):
        success = await mqtt_manager.publish(profile_id, topic, payload)
        if success:
            ui.notify(f"Published to {topic}", type='positive')
        else:
            ui.notify("Publish failed - not connected?", type='negative')

    # Poll for updates
    async def mqtt_refresh_loop():
        while True:
            await asyncio.sleep(3)
            refresh_mqtt()

    asyncio.create_task(mqtt_refresh_loop())
    refresh_mqtt()


def marketplace_page():
    """Plugin Marketplace - browse, install, and share protocol decoder plugins."""
    # Built-in catalog (would be fetched from GitHub in production)
    catalog = [
        {
            'id': 'ldf_decoder',
            'name': 'LIN Bus (LDF)',
            'author': 'UARTScope Community',
            'description': 'Decode LIN bus frames using .ldf database files. Supports LIN 1.3-2.2, signal mapping, and schedule tables.',
            'version': '1.0.0',
            'downloads': 1240,
            'tags': ['automotive', 'lin', 'can-lin'],
            'installed': False,
        },
        {
            'id': 'j1939_decoder',
            'name': 'J1939 (Heavy Duty)',
            'author': 'UARTScope Community',
            'description': 'SAE J1939 protocol decoder for trucks, buses, and agricultural vehicles. PGN-based message parsing.',
            'version': '1.1.0',
            'downloads': 890,
            'tags': ['automotive', 'j1939', 'truck'],
            'installed': False,
        },
        {
            'id': 'dali_decoder',
            'name': 'DALI Lighting',
            'author': 'UARTScope Community',
            'description': 'DALI / DALI-2 lighting control protocol decoder. Supports broadcast, group addressing, and scene commands.',
            'version': '0.9.0',
            'downloads': 567,
            'tags': ['lighting', 'dali', 'iot'],
            'installed': False,
        },
        {
            'id': 'rcs_decoder',
            'name': 'RCS Servo',
            'author': 'UARTScope Community',
            'description': 'Futaba S.Bus / S.Bus2 and FrSky servo protocol decoder. Channel extraction and failsafe detection.',
            'version': '1.0.0',
            'downloads': 723,
            'tags': ['rc', 'servo', 'fpv'],
            'installed': False,
        },
        {
            'id': 'mbus_decoder',
            'name': 'M-Bus Metering',
            'author': 'UARTScope Community',
            'description': 'Meter-Bus (EN 13757) decoder for heat, gas, water, and electricity meters. Variable data format parsing.',
            'version': '1.0.0',
            'downloads': 445,
            'tags': ['metering', 'mbus', 'iot'],
            'installed': False,
        },
        {
            'id': 'profibus_decoder',
            'name': 'PROFIBUS DP',
            'author': 'UARTScope Pro',
            'description': 'PROFIBUS DP-V0/V1 decoder for industrial automation. SAP handling and diagnostic messages.',
            'version': '1.0.0',
            'downloads': 312,
            'tags': ['industrial', 'profibus', 'plc'],
            'installed': False,
        },
    ]

    installed_plugins = [p for p in catalog if p['installed']]
    search_state = {'query': ''}

    with ui.column().classes('w-full gap-4'):
        # Header
        with ui.row().classes('w-full items-center justify-between mb-3'):
            with ui.column():
                ui.label('Plugin Marketplace').classes('text-white font-medium text-lg')
                ui.label('Browse and install community protocol decoders').classes('text-[#52525b] text-sm')
            with ui.row().classes('gap-2 mt-1'):
                ui.label(f'{len(installed_plugins)} installed').classes('text-[#22c55e] text-xs font-mono')

        # Search bar
        search_input = ui.input('Search plugins...', placeholder='Search by name, tag, or description').classes('w-full').props('outlined dense').style('color: #e4e4e7')
        search_input.on_value_change(lambda: refresh_catalog())

        # Installed section
        if installed_plugins:
            with ui.card().classes('w-full p-4').style('background: rgba(255,255,255,0.02); border: 1px solid rgba(39,166,68,0.2)'):
                ui.label('✅ Installed Plugins').classes('text-white font-medium mb-3')
                with ui.column().classes('w-full gap-3 p-6 max-w-[1400px] mx-auto'):
                    for plugin in installed_plugins:
                        with ui.row().classes('w-full items-center justify-between p-2 rounded-lg').style('background: rgba(255,255,255,0.01)'):
                            with ui.row().classes('items-center gap-2'):
                                ui.label('📦').classes('text-sm')
                                with ui.column().classes('gap-0'):
                                    ui.label(plugin['name']).classes('text-[#e4e4e7] text-sm font-medium')
                                    ui.label(f"v{plugin['version']} · {plugin['author']}").classes('text-[#52525b] text-xs')
                            with ui.row().classes('gap-2 mt-1'):
                                ui.label('Installed').classes('text-[#22c55e] text-xs')
                                ui.button('Uninstall', on_click=lambda p=plugin: uninstall_plugin(p)).classes('bg-[rgba(229,72,77,0.1)] text-[#ef4444] px-2 py-0.5 text-xs rounded')

        # Catalog grid
        catalog_container = ui.column().classes('w-full gap-4 p-6 max-w-[1400px] mx-auto')

    def refresh_catalog():
        query = search_input.value.lower().strip() if search_input.value else ''
        catalog_container.clear()

        filtered = catalog
        if query:
            filtered = [p for p in catalog if
                        query in p['name'].lower() or
                        query in p['description'].lower() or
                        any(query in t for t in p['tags'])]

        if not filtered:
            with catalog_container:
                with ui.card().classes('w-full p-12 text-center').style('background: #16181d; border-left: 2px solid #5c8af0'):
                    ui.label('🔍').classes('text-3xl mb-2')
                    ui.label('No plugins found').classes('text-[#e4e4e7] font-medium')
                    ui.label('Try a different search term').classes('text-[#52525b] text-sm')
        else:
            with catalog_container:
                for plugin in filtered:
                    with ui.card().classes('w-full p-4').style('background: #16181d; border-left: 2px solid #5c8af0'):
                        with ui.row().classes('w-full items-start justify-between'):
                            with ui.column().classes('gap-1 flex-1'):
                                with ui.row().classes('items-center gap-2'):
                                    ui.label(plugin['name']).classes('text-white font-medium text-sm')
                                    ui.label(f"v{plugin['version']}").classes('text-[#52525b] text-xs font-mono')
                                ui.label(plugin['description']).classes('text-[#71717a] text-xs leading-relaxed')
                                with ui.row().classes('gap-1 mt-1'):
                                    for tag in plugin['tags']:
                                        ui.label(tag).classes('text-[#5c8af0] text-[10px] bg-[rgba(113,112,255,0.1)] px-1.5 py-0.5 rounded')
                                ui.label(f"by {plugin['author']} · {plugin['downloads']:,} downloads").classes('text-[#52525b] text-[10px] mt-1')
                            with ui.column().classes('gap-2 items-end'):
                                if plugin['installed']:
                                    ui.label('✅ Installed').classes('text-[#22c55e] text-xs')
                                else:
                                    ui.button('Install', on_click=lambda p=plugin: install_plugin(p)).classes('bg-[#5c6fd0] text-white px-3 py-1 text-xs rounded-lg')

    async def install_plugin(plugin):
        ui.notify(f"Installing '{plugin['name']}'...", type='info')
        # Simulate install (in production: download from GitHub repo)
        await asyncio.sleep(1)
        plugin['installed'] = True
        plugin['downloads'] += 1
        ui.notify(f"✅ '{plugin['name']}' installed! Restart to activate.", type='positive')
        refresh_catalog()

    async def uninstall_plugin(plugin):
        plugin['installed'] = False
        ui.notify(f"'{plugin['name']}' uninstalled", type='info')
        refresh_catalog()

    refresh_catalog()


def decoder_page():
    """Protocol decoder - hex input, decode, structured output, DBC file loading."""
    dbc_info = {'loaded': False, 'messages': 0, 'signals': 0}

    _bind_decoder_page, _late_decoder_page = _late_bindings()

    with ui.column().classes('w-full gap-4'):
        # DBC file loader
        with ui.card().classes('w-full p-4').style('background: rgba(255,255,255,0.02); border: 1px solid rgba(113,112,255,0.2)'):
            with ui.row().classes('w-full items-center justify-between mb-2'):
                ui.label('📁 CAN Database (.dbc)').classes('text-white font-medium')
                ui.button('Load DBC File', on_click=_late_decoder_page('show_dbc_upload_dialog')).classes('bg-[#5c8af0] text-white px-3 py-1 text-sm rounded-lg')
            with ui.row().classes('w-full items-center gap-3'):
                ui.label('Status:').classes('text-[#71717a] text-xs')
                dbc_status_label = ui.label('No DBC loaded').classes('text-[#52525b] text-xs font-mono')
                ui.label('Messages:').classes('text-[#71717a] text-xs')
                dbc_msgs_label = ui.label('0').classes('text-[#52525b] text-xs font-mono')
                ui.label('Signals:').classes('text-[#71717a] text-xs')
                dbc_sigs_label = ui.label('0').classes('text-[#52525b] text-xs font-mono')

        with ui.row().classes('w-full items-center gap-3'):
            protocol = ui.select(
                ['auto'] + [p['id'] for p in protocol_manager.list_decoders()],
                value='auto', label='Protocol'
            ).classes('bg-[rgba(255,255,255,0.02)] text-[#e4e4e7] border border-[rgba(255,255,255,0.10)] px-3 py-2 rounded-lg w-48')
            raw_input = ui.input('Hex Data', placeholder='e.g. 7848656C6C6F00 or 010300010001').classes('flex-1').props('outlined').style('color: #e4e4e7; font-family: JetBrains Mono, monospace')
            ui.button('Decode', on_click=lambda: do_decode(raw_input.value, protocol.value)).classes('bg-[#5c6fd0] text-white px-4 py-2 rounded-lg')

        result_container = ui.column().classes('w-full gap-3 p-6 max-w-[1400px] mx-auto')

        def _show_dbc_upload_dialog_impl():
            """Dialog to paste DBC file content."""
            dialog = ui.dialog()
            with dialog, ui.card().classes('p-6 w-[600px]').style('background: #16181d; border: 1px solid rgba(255,255,255,0.10)'):
                ui.label('Load CAN Database (.dbc)').classes('text-white font-medium mb-4 text-lg')
                ui.label('Paste DBC file content below:').classes('text-[#71717a] text-xs mb-2')
                dbc_input = ui.textarea('DBC Content', placeholder='BO_ 100 EngineData: 8 Vector__XXX\n SG_ RPM : 0|16@1+ (1,0) [0|8000] "rpm" Vector__XXX').classes('w-full h-48 mb-4').props('outlined').style('color: #e4e4e7; font-family: monospace; font-size: 11px')
                with ui.row().classes('gap-2 justify-end w-full'):
                    ui.button('Cancel', on_click=dialog.close).props('flat').classes('text-[#71717a]')
                    ui.button('Load', on_click=lambda: do_load_dbc(dbc_input.value, dialog)).classes('bg-[#5c8af0] text-white px-4 py-2 rounded-lg')

        async def do_load_dbc(content, dialog):
            if not content.strip():
                ui.notify('Paste DBC content first', type='warning')
                return
            dialog.close()
            ui.notify('Loading DBC file...', type='info')
            try:
                from app.core.protocol_decoder import protocol_manager
                decoder = protocol_manager.get_decoder('can_dbc')
                if decoder:
                    result = decoder.load_dbc_text(content)
                    msgs = result.get('messages', 0)
                    sigs = result.get('total_signals', 0)
                    if 'error' not in result:
                        dbc_status_label.text = '✅ Loaded'
                        dbc_msgs_label.text = str(msgs)
                        dbc_sigs_label.text = str(sigs)
                        ui.notify(f'DBC loaded: {msgs} messages, {sigs} signals', type='positive')
                    else:
                        ui.notify(f"Error: {result['error']}", type='negative')
                else:
                    ui.notify('DBC decoder not available', type='negative')
            except Exception as e:
                ui.notify(f'Error: {e}', type='negative')

        _bind_decoder_page('show_dbc_upload_dialog', _show_dbc_upload_dialog_impl)

        async def do_decode(raw_hex, proto_id):
            result_container.clear()
            if not raw_hex:
                return
            try:
                raw_data = bytes.fromhex(raw_hex.replace(' ', ''))
            except ValueError:
                ui.notify('Invalid hex', type='negative')
                return

            if proto_id == 'auto':
                decoder = protocol_manager.auto_detect(raw_data)
                if not decoder:
                    with result_container:
                        ui.label('No protocol detected').classes('text-[#ef4444]').style('padding: 20px')
                    return
                proto_id = decoder.protocol_id

            decoded = protocol_manager.decode(proto_id, raw_data)
            decoder = protocol_manager.get_decoder(proto_id)

            with result_container:
                with ui.card().classes('w-full p-4').style('background: rgba(255,255,255,0.02); border: 1px solid rgba(113,112,255,0.2)'):
                    with ui.row().classes('items-center gap-2 mb-3'):
                        ui.label(decoder.name).classes('text-[#5c8af0] font-medium text-sm').style('background: rgba(113,112,255,0.15); padding: 2px 8px; border-radius: 9999px')
                        ui.label(proto_id).classes('text-[#52525b] text-xs font-mono')
                    with ui.column().classes('gap-1 font-mono text-sm'):
                        for key, value in decoded.items():
                            with ui.row().classes('gap-3'):
                                ui.label(key).classes('text-[#71717a] min-w-32')
                                ui.label(str(value)).classes('text-[#e4e4e7]')


# ─── Main Layout ─────────────────────────────────────────────────────────────
content_container = None

def rebuild():
    """Rebuild the entire UI."""
    global content_container
    _refresh_status()
    if content_container:
        content_container.clear()
        with content_container:
            render_content()

def render_content():
    global content_container
    if current_tab == 'devices':
        devices_page()
    elif current_tab == 'terminal':
        terminal_page()
    elif current_tab == 'charts':
        charts_page()
    elif current_tab == 'alerts':
        alerts_page()
    elif current_tab == 'sessions':
        sessions_page()
    elif current_tab == 'session-detail':
        session_detail_page()
    elif current_tab == 'performance':
        performance_page()
    elif current_tab == 'mqtt':
        mqtt_page()
    elif current_tab == 'marketplace':
        marketplace_page()
    elif current_tab == 'decoder':
        decoder_page()

def switch_tab(tab_id):
    global current_tab
    current_tab = tab_id
    rebuild()


def build_header():
    """Persistent page header: where you are, and what the system is doing.

    v1 had no header at all. The only context anywhere was the sidebar brand and
    an empty-state message, so there was no page name and no global status.
    """
    with ui.row().classes('us-header w-full items-center').style(
            'margin: 0 -24px; padding-left: 24px; padding-right: 24px'):
        with ui.column().classes('gap-1'):
            ui.label(nav_label(current_tab)).classes('us-title')
            ui.label(_TAB_SUBTITLES.get(current_tab, '')).classes('us-caption us-muted')
        with ui.row().classes('items-center gap-3'):
            _header_status()
            if current_tab in V2_PENDING:
                ui.label('Not yet v2').classes(
                    'us-micro px-2 py-1 rounded-full').style(
                    'background:rgba(176,174,165,0.10)')

def _header_status():
    """Live connection state, bound to the shared status source.

    v2 distinguishes three states, not two: registered-but-not-started devices
    are a real and common state, and collapsing them into "No devices" left the
    header contradicting the device list directly below it.

    NiceGUI has no class binding and .style() takes a plain string, not a
    callable, so the dot is a real label whose colour _refresh_status() writes
    directly. The registry is reset on every build so a page navigation cannot
    leave detached elements behind in it.
    """
    _STATUS_DOTS.clear()
    with ui.row().classes('us-status items-center gap-2'):
        dot = ui.label('●').classes('us-dot-label')
        _STATUS_DOTS.append(dot)
        ui.label().classes('us-caption').bind_text_from(
            _STATUS_SRC, 'headline')

# One line of orientation per screen. Monitor surfaces, not marketing copy.
_TAB_SUBTITLES = {
    'devices': 'Serial ports and connection state',
    'terminal': 'Live stream',
    'charts': 'Real-time telemetry',
    'alerts': 'Rule-based monitoring',
    'sessions': 'Recording and replay',
    'session-detail': 'Session detail',
    'decoder': 'I2C, SPI, CAN, Modbus decode',
    'performance': 'Packet rate, throughput, latency',
    'mqtt': 'Broker connections and pub/sub',
    'marketplace': 'Community protocol decoders',
}


def _demo_device():
    """A device-shaped stand-in for previewing screens without hardware.

    Deliberately not registered with device_manager: nothing here opens a real
    port, so this is safe to construct for a render.
    """
    return types.SimpleNamespace(
        id='demo-device', name='Demo board', port='/dev/ttyUSB0',
        baudrate=115200, board_type='ESP32', status='registered',
        auto_reconnect=True, session_id=None, serial_conn=None,
        metadata={},
    )


# Seed telemetry for the preview device, spanning several units so the
# unit-grouping on the Charts screen is visible without real hardware. Includes
# a negative value and a large one, because _fmt() and the sparkline ramp have
# to hold up for those.
_DEMO_LINES = [
    'TEMP:23.4', 'TEMP:23.9', 'TEMP:24.6', 'TEMP:24.1', 'TEMP:23.8', 'TEMP:24.9',
    'HUMIDITY:58', 'HUMIDITY:59', 'HUMIDITY:61', 'HUMIDITY:60',
    'VOLTAGE:3.28', 'VOLTAGE:3.31', 'VOLTAGE:3.29',
    'CURRENT:0.11', 'CURRENT:0.14', 'CURRENT:0.12',
    'RSSI:-58', 'RSSI:-61', 'RSSI:-59', 'RSSI:-72',
    'ERROR: sensor timeout on channel 2',
]


def _seed_demo_telemetry():
    """Feed the preview device one round of demo telemetry.

    Idempotent, and scheduled rather than awaited: the page builder is sync and
    process_line is async, so this runs as a task and the Charts screen fills in
    on its first 2s refresh.
    """

    async def feed():
        for line in _DEMO_LINES:
            await telemetry_engine.process_line('demo-device', 'demo-session', line)

    if telemetry_engine.get_all_metrics('demo-device'):
        return
    asyncio.create_task(feed())


def _seed_demo_alerts():
    """Seed rules and alert history for the preview, so the Alerts screen can be
    reviewed with the states that matter: unacknowledged, acknowledged, and each
    severity. Uses the same engine instance the page reads from, so this is real
    data rather than a mock. Idempotent.
    """
    if alert_engine.get_all_rules():
        return

    for name, metric, cond, thr, sev in [
        ('Over temperature', 'TEMP', '>', 30.0, 'critical'),
        ('Signal degraded', 'RSSI', '<', -60.0, 'warning'),
        ('Over voltage', 'VOLTAGE', '>', 3.30, 'info'),
    ]:
        alert_engine.add_rule(AlertRule(
            id=name, name=name, metric_name=metric, condition=cond,
            threshold=thr, cooldown=0, severity=sev))

    async def feed():
        for m in [Metric(name='TEMP', value=31.2),
                  Metric(name='RSSI', value=-64.0),
                  Metric(name='VOLTAGE', value=3.28),
                  Metric(name='TEMP', value=32.4),
                  Metric(name='RSSI', value=-71.0),
                  Metric(name='TEMP', value=30.8),
                  Metric(name='VOLTAGE', value=3.35),
                  Metric(name='RSSI', value=-66.0),
                  Metric(name='TEMP', value=33.1)]:
            await alert_engine.evaluate('demo-device', 'demo-session', m)
        # Acknowledge a couple so the queue renders both states.
        for a in alert_engine.get_alert_history()[2:4]:
            alert_engine.acknowledge_alert(a['id'])

    asyncio.create_task(feed())


@ui.page('/')
@ui.page('/smoke/{tab}')
def main_page(tab: str = 'devices', with_device: bool = False):
    """Build the shell.

    The /smoke/<tab> route exists so smoke_pages.py can boot every screen over
    real HTTP. v1 had no way to reach a screen without clicking to it, which is
    how the Terminal and Decoder both sat broken in the repo: each raised
    UnboundLocalError on construction and the only evidence was a server log.

    `with_device` binds a device without opening a real port, so the
    device-scoped screens can be rendered and reviewed without hardware. The
    screens that need one build a completely different tree, and reviewing only
    the no-device path would miss most of their code.
    """
    global content_container, current_tab, selected_device

    if tab in NAV_TAB_IDS:
        current_tab = tab

    if with_device and selected_device is None:
        selected_device = _demo_device()
        _seed_demo_telemetry()
    if with_device and tab == 'alerts':
        _seed_demo_alerts()

    # v2 design system: tokens + Inter/JetBrains Mono. Must run before any
    # screen is built so the first paint is already themed.
    # The Quasar palette re-point inside inject_theme_css() is authoritative;
    # setting primary here would reintroduce the blue that --q-primary now
    # deliberately holds neutral ink instead.
    inject_theme_css(ui)

    # Background data refresh
    async def bg_refresh():
        while True:
            await asyncio.sleep(3)

    asyncio.create_task(bg_refresh())

    # Alert notifications
    async def on_alert(alert):
        ui.notify(f"🚨 {alert.get('message', '')}", type='warning', timeout=5000)

    alert_engine.register_callback(on_alert)

    # Build layout
    build_sidebar()

    # Content area. v1 capped this at max-width 1000px, which left Monitor
    # surfaces (terminal, charts) stranded on a narrow column in the middle of a
    # wide monitor. The cap is raised to 1600px: dense screens can breathe, and
    # text screens stay readable. Padding is restored here because the header and
    # page need the inset that v1 got from the container's own p-6.
    content_container = ui.column().classes('w-full').style(
        'max-width: 1600px; margin: 0 auto; padding: 0 24px 32px 24px')
    with content_container:
        build_header()
        render_content()

    # Keep the header and rail honest without a full rebuild. 2s is fast enough
    # to feel live and cheap enough to ignore; the labels it drives are all
    # small text nodes, so this is not a repaint of the page.
    ui.timer(2.0, _refresh_status)


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        # v1 shipped title '🐴 UARTScope Pro' and an emoji favicon.
        title='UARTScope Pro',
        port=3000,
        host='0.0.0.0',
        dark=True,
        reload=False,
        show=False,
    )
