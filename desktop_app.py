"""UARTScope Pro - Desktop Application (NiceGUI)"""
import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import datetime

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from nicegui import ui, app

from uartscope_theme import (
    inject_theme_css,
    icon,
    STATUS,
)

from app.core.device_manager import device_manager
from app.core.telemetry_engine import telemetry_engine
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

def severity_color(sev):
    """Map an alert severity to a v2 status token.

    v1 returned raw hex (#ef4444/#eab308/#3b82f6/#71717a) with no relationship to
    the rest of the palette. The v2 values are computed for contrast on the dark
    surfaces: error 5.59:1, warn 9.74:1, info 6.76:1, idle 5.04:1 on base.
    """
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
                ui.html(
                    '<svg width="22" height="22" viewBox="0 0 24 24" fill="none" '
                    'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" '
                    'stroke-linejoin="round" aria-hidden="true" '
                    'style="color:#c96442">'
                    '<path d="M2.5 12h3l2-6 3 12 2.5-8 1.5 4h7"/>'
                    '</svg>'
                )
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
    """Terminal view - real-time serial output with search & filter."""
    global selected_device

    if not selected_device:
        ui.label('Select a device from the Devices tab to open the terminal').classes('text-[#52525b] text-sm').style('padding: 60px')
        return

    # State for terminal
    terminal_state = {'lines': [], 'search': '', 'case_sensitive': False, 'regex': False, 'match_count': 0, 'current_match': 0, 'filter_level': 'all', 'filter_metric': ''}

    with ui.column().classes('w-full gap-3 p-6 max-w-[1400px] mx-auto'):
        # Header
        with ui.row().classes('w-full items-center justify-between mb-3'):
            ui.label(f"{selected_device.name}  /  {selected_device.port}").classes('text-[#71717a] text-sm font-mono')
            ui.label('0 lines').classes('text-[#52525b] text-xs font-mono').bind_text_from(terminal_state, 'lines', lambda v: f"{len(v)} lines")

        # Command bar
        with ui.row().classes('w-full gap-2 items-center p-3').style('background: #16181d; border-radius: 8px'):
            cmd_input = ui.input('Send command', placeholder='Type a command and press Enter...').classes('flex-1').props('outlined dense').style('color: #e4e4e7; font-family: JetBrains Mono, monospace; font-size: 12px')
            ui.button('Send', on_click=lambda: send_command()).classes('bg-[#22c55e] text-white px-4 py-1.5 text-sm rounded-lg font-medium')
            ui.button('Macros ▾', on_click=show_macros_dialog).classes('bg-[rgba(255,255,255,0.03)] text-[#71717a] border border-[rgba(255,255,255,0.10)] px-3 py-1 text-sm rounded-lg')
            ui.button('History ▾', on_click=show_history_dialog).classes('bg-[rgba(255,255,255,0.03)] text-[#71717a] border border-[rgba(255,255,255,0.10)] px-3 py-1 text-sm rounded-lg')

        # Command state
        command_history = []  # list of {'cmd': str, 'timestamp': str}
        macros = [{'name': 'Scan I2C', 'commands': ['AA', 'BB']}]  # example macros

    def send_command():
        """Send command to device."""
        cmd = cmd_input.value
        if not cmd:
            return
        # Record in history
        ts = datetime.utcnow().strftime('%H:%M:%S')
        command_history.insert(0, {'cmd': cmd, 'timestamp': ts})
        if len(command_history) > 100:
            command_history.pop()
        # Send to device
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

    def show_history_dialog():
        """Show command history dialog."""
        dialog = ui.dialog()
        with dialog, ui.card().classes('p-4 w-96 max-h-80 overflow-y-auto').style('background: #16181d; border: 1px solid rgba(255,255,255,0.10)'):
            ui.label('Command History').classes('text-white font-semibold mb-4')
            if not command_history:
                ui.label('No commands in history').classes('text-[#52525b] text-sm py-6')
            else:
                with ui.column().classes('w-full gap-0.5'):
                    for entry in command_history[:20]:
                        with ui.row().classes('w-full items-center gap-3 px-3 py-2 rounded-lg hover:bg-[rgba(255,255,255,0.03)]') \
                            .on('click', lambda e=entry: replay_command(e)):
                            ui.label(entry['timestamp']).classes('text-[#52525b] text-xs font-mono w-16')
                            ui.label(entry['cmd']).classes('text-[#e4e4e7] text-sm font-mono flex-1')
                            ui.label('↗').classes('text-[#5c8af0] text-xs')

    def show_macros_dialog():
        """Show macros management dialog."""
        dialog = ui.dialog()
        with dialog, ui.card().classes('p-4 w-96').style('background: #16181d; border: 1px solid rgba(255,255,255,0.10)'):
            with ui.row().classes('w-full items-center justify-between mb-3'):
                ui.label('Macros').classes('text-white font-medium')
                ui.button('+ New', on_click=lambda: show_create_macro_dialog()).classes('bg-[#5c6fd0] text-white px-3 py-1 text-xs rounded-lg font-medium')

            if not macros:
                ui.label('No macros defined yet').classes('text-[#52525b] text-sm py-6')
            else:
                with ui.column().classes('w-full gap-0.5'):
                    for i, macro in enumerate(macros):
                        with ui.row().classes('w-full items-center gap-3 px-3 py-2 rounded-lg').style('background: rgba(255,255,255,0.02)'):
                            ui.label(macro['name']).classes('text-[#e4e4e7] text-sm font-medium flex-1')
                            cmd_count = len(macro['commands'])
                            ui.label(f"{cmd_count} commands").classes('text-[#52525b] text-xs')
                            ui.button('▶ Run', on_click=lambda m=macro: run_macro(m)).classes('bg-[#22c55e] text-white px-2 py-0.5 text-xs rounded')
                            ui.button('x', on_click=lambda idx=i: delete_macro(idx)).classes('text-[#ef4444] text-xs px-2 py-1 rounded hover:bg-[rgba(239,68,68,0.1)]')

    def show_create_macro_dialog():
        """Dialog to create a new macro."""
        macro_dialog = ui.dialog()
        with macro_dialog, ui.card().classes('p-4 w-96').style('background: #16181d; border: 1px solid rgba(255,255,255,0.10)'):
            ui.label('New Macro').classes('text-white font-medium mb-3')
            name_input = ui.input('Name', value='My Macro').classes('w-full mb-2').props('outlined').style('color: #e4e4e7')
            cmds_input = ui.textarea('Commands (one per line)', value='AT\r\nAT+STATUS').classes('w-full mb-3').props('outlined').style('color: #e4e4e7; font-family: monospace')
            with ui.row().classes('gap-2 justify-end w-full'):
                ui.button('Cancel', on_click=macro_dialog.close).props('flat').classes('text-[#71717a]')
                ui.button('Create', on_click=lambda: create_macro(name_input.value, cmds_input.value, macro_dialog)).classes('bg-[#5c6fd0] text-white px-4 py-2 rounded-lg')

    def create_macro(name, commands_text, dialog):
        """Create a new macro."""
        commands = [c.strip() for c in commands_text.strip().split('\n') if c.strip()]
        if not commands:
            ui.notify('Add at least one command', type='warning')
            return
        macros.append({'name': name or 'Unnamed', 'commands': commands})
        dialog.close()
        ui.notify(f"Macro '{name}' created with {len(commands)} commands", type='positive')

    def delete_macro(index):
        """Delete a macro."""
        if 0 <= index < len(macros):
            name = macros[index]['name']
            macros.pop(index)
            ui.notify(f"Deleted macro '{name}'", type='info')

    async def run_macro(macro):
        """Execute a macro sequence."""
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

    def replay_command(entry):
        """Replay a command from history."""
        cmd_input.value = entry['cmd']

    # Wire up Enter key on command input
    cmd_input.on('keydown.enter', lambda: send_command())

    # Search & Filter bar
    with ui.row().classes('w-full gap-2 items-center p-3').style('background: #16181d; border-radius: 8px'):
            search_input = ui.input('Search (Ctrl+F)', placeholder='Type to search...').classes('flex-1').props('outlined dense').style('color: #e4e4e7; font-family: JetBrains Mono, monospace; font-size: 12px')
            search_input.bind_value(terminal_state, 'search')
            case_toggle = ui.checkbox('Case sensitive').classes('text-[#71717a] text-xs').bind_value(terminal_state, 'case_sensitive')
            regex_toggle = ui.checkbox('Regex').classes('text-[#71717a] text-xs').bind_value(terminal_state, 'regex')
            level_select = ui.select(['all', 'ERROR', 'WARN', 'INFO', 'DEBUG', 'metric', 'json'], value='all', label='Filter').classes('w-24').props('outlined dense').bind_value(terminal_state, 'filter_level')
            metric_input = ui.input('Metric', placeholder='e.g. TEMP').classes('w-28').props('outlined dense').bind_value(terminal_state, 'filter_metric')

    # Match navigation bar
    with ui.row().classes('w-full gap-2 items-center p-3').style('background: #16181d; border-radius: 8px'):
        match_label = ui.label('No matches').classes('text-[#52525b] text-xs flex-1')
        ui.button('◀', on_click=lambda: navigate_match(-1)).classes('bg-[rgba(255,255,255,0.03)] text-[#71717a] border border-[rgba(255,255,255,0.10)] px-2 py-0.5 text-xs rounded')
        ui.button('▶', on_click=lambda: navigate_match(1)).classes('bg-[rgba(255,255,255,0.03)] text-[#71717a] border border-[rgba(255,255,255,0.10)] px-2 py-0.5 text-xs rounded')
        ui.button('Clear', on_click=lambda: clear_search()).classes('bg-[rgba(255,255,255,0.03)] text-[#71717a] border border-[rgba(255,255,255,0.10)] px-2 py-0.5 text-xs rounded')

    # Log area
    log_area = ui.column().classes('w-full gap-0 overflow-y-auto') \
        .style('max-height: 55vh; background: #0d0f12; padding: 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.06); font-family: JetBrains Mono, monospace; font-size: 13px; width: 100%')

    def _apply_search_filter():
        """Apply search and filter to all stored lines, re-render log area."""
        search = terminal_state['search']
        case_sensitive = terminal_state['case_sensitive']
        use_regex = terminal_state['regex']
        level = terminal_state['filter_level']
        metric_filter = terminal_state['filter_metric'].strip().upper()

        import re as _re
        matches = []

        # Compile regex if needed
        pattern = None
        if search:
            flags = 0 if case_sensitive else _re.IGNORECASE
            if use_regex:
                try:
                    pattern = _re.compile(search, flags)
                except _re.error:
                    pattern = None
            else:
                pattern = _re.compile(_re.escape(search), flags)

        for i, (timestamp, line, line_type) in enumerate(terminal_state['lines']):
            # Level filter
            if level != 'all':
                if level == 'ERROR' and 'ERROR' not in line.upper():
                    continue
                elif level == 'WARN' and not any(w in line.upper() for w in ['WARN', 'WARNING']):
                    continue
                elif level == 'INFO' and 'INFO' not in line.upper():
                    continue
                elif level == 'DEBUG' and 'DEBUG' not in line.upper():
                    continue
                elif level == 'metric' and line_type != 'metric':
                    continue
                elif level == 'json' and line_type != 'json':
                    continue

            # Metric filter
            if metric_filter and metric_filter not in line.upper():
                continue

            # Search filter
            is_match = True
            if pattern:
                check_line = line if case_sensitive else line.lower()
                is_match = bool(pattern.search(check_line))

            matches.append((i, timestamp, line, line_type, is_match))

        # Render filtered results
        log_area.clear()
        match_indices = [idx for idx, (_, _, _, _, m) in enumerate(matches) if m and search]
        terminal_state['match_count'] = len(match_indices)

        if not match_label:
            pass
        if match_indices:
            match_label.text = f"Match {terminal_state['current_match'] + 1} of {len(match_indices)}"
        elif search:
            match_label.text = "No matches"
        else:
            match_label.text = f"{len(terminal_state['lines'])} lines"

        with log_area:
            for idx, (orig_i, ts, line, line_type, is_match) in enumerate(matches):
                # Color based on line type
                if line_type == 'error':
                    color = '#ef4444'
                elif line_type == 'warn':
                    color = '#eab308'
                elif line_type == 'metric':
                    color = '#5c8af0'
                elif line_type == 'json':
                    color = '#22c55e'
                else:
                    color = '#e4e4e7'

                # Highlight search matches
                bg_style = 'background: rgba(113,112,255,0.2); border-radius: 2px;' if is_match and search else ''
                ui.label(f"[{ts}] {line}").classes(f'leading-relaxed font-mono').style(f'color: {color}; {bg_style}')

    def navigate_match(direction):
        """Navigate to next/prev match."""
        if direction == '__init__':
            return
        # Re-run search to get match count
        _apply_search_filter()
        if terminal_state['match_count'] == 0:
            return
        terminal_state['current_match'] = (terminal_state['current_match'] + direction) % terminal_state['match_count']
        _apply_search_filter()

    def clear_search():
        """Clear search and reset filters."""
        terminal_state['search'] = ''
        terminal_state['filter_level'] = 'all'
        terminal_state['filter_metric'] = ''
        terminal_state['current_match'] = 0
        _apply_search_filter()

    # Wire up reactive search
    search_input.on_value_change(lambda: _apply_search_filter())
    case_toggle.on_value_change(lambda: _apply_search_filter())
    regex_toggle.on_value_change(lambda: _apply_search_filter())
    level_select.on_value_change(lambda: _apply_search_filter())
    metric_input.on_value_change(lambda: _apply_search_filter())

    async def stream_loop():
        if not selected_device:
            return
        queue = asyncio.Queue()

        async def on_data(line=""):
            await queue.put(line)

        await serial_reader.start_device(selected_device, "terminal", on_data)

        try:
            while True:
                line = await asyncio.wait_for(queue.get(), timeout=1)
                ts = datetime.utcnow().strftime('%H:%M:%S')

                # Detect line type
                line_upper = line.upper()
                if any(w in line_upper for w in ['ERROR', 'FATAL']):
                    line_type = 'error'
                elif any(w in line_upper for w in ['WARN', 'WARNING']):
                    line_type = 'warn'
                elif line.startswith('{') and line.endswith('}'):
                    line_type = 'json'
                elif any(line_upper.startswith(m) for m in ['TEMP', 'VOLTAGE', 'HUMIDITY', 'PRESSURE', 'CURRENT', 'POWER', 'ADC', 'PWM', 'FREQ', 'RSSI', 'SNR']):
                    line_type = 'metric'
                else:
                    line_type = 'log'

                terminal_state['lines'].append((ts, line, line_type))

                # Keep max 5000 lines in memory
                if len(terminal_state['lines']) > 5000:
                    terminal_state['lines'] = terminal_state['lines'][-5000:]

                # Incremental render (every 10 lines for performance)
                if len(terminal_state['lines']) % 1 == 0:
                    _apply_search_filter()
        except asyncio.TimeoutError:
            pass

    asyncio.create_task(stream_loop())


def charts_page():
    """Live charts - telemetry visualization with custom dashboard builder."""
    global selected_device

    if not selected_device:
        ui.label('Select a device from Devices tab to view charts').classes('text-[#52525b]').style('padding: 40px')
        return

    # Dashboard state
    dashboard_state = {
        'widgets': [],  # list of {id, type, metric, title, size}
        'edit_mode': False,
        'next_id': 1,
    }

    with ui.column().classes('w-full gap-4 p-6 max-w-[1400px] mx-auto'):
        # Header with controls
        with ui.row().classes('w-full items-center justify-between mb-3'):
            with ui.row().classes('items-center gap-3'):
                ui.label(f"📊 Dashboard - {selected_device.name}").classes('text-[#e4e4e7] font-medium')
                ui.button('⊞ Edit', on_click=lambda: toggle_edit()).classes('bg-[rgba(255,255,255,0.03)] text-[#71717a] border border-[rgba(255,255,255,0.10)] px-3 py-1 text-sm rounded-lg')
                ui.button('+ Add Widget', on_click=show_add_widget_dialog).classes('bg-[#5c6fd0] text-white px-3 py-1 text-sm rounded-lg')

        # Available metrics info
        latest = telemetry_engine.get_latest_values(selected_device.id)
        if latest:
            with ui.row().classes('w-full gap-2 flex-wrap mb-2'):
                for name, value in latest.items():
                    ui.label(f"{name}: {value:.2f}").classes('text-[#52525b] text-xs font-mono bg-[rgba(255,255,255,0.02)] px-2 py-0.5 rounded')

        # Dashboard grid
        dashboard_container = ui.column().classes('w-full gap-4 p-6 max-w-[1400px] mx-auto')

    def toggle_edit():
        dashboard_state['edit_mode'] = not dashboard_state['edit_mode']
        refresh_dashboard()

    def show_add_widget_dialog():
        dialog = ui.dialog()
        with dialog, ui.card().classes('p-6 w-96').style('background: #16181d; border: 1px solid rgba(255,255,255,0.10)'):
            ui.label('Add Widget').classes('text-white font-medium mb-4 text-lg')
            type_select = ui.select(['Metric Card', 'Line Chart', 'Gauge', 'Alert Summary', 'Log Table'], value='Metric Card').classes('w-full mb-3').props('outlined').style('color: #e4e4e7')
            title_input = ui.input('Title', value='').classes('w-full mb-3').props('outlined').style('color: #e4e4e7')
            metric_select = ui.select(
                list(latest.keys()) if latest else ['TEMP'],
                value=list(latest.keys())[0] if latest else 'TEMP',
                label='Metric'
            ).classes('w-full mb-3').props('outlined').style('color: #e4e4e7')
            size_select = ui.select(['Small', 'Medium', 'Large'], value='Medium').classes('w-full mb-4').props('outlined').style('color: #e4e4e7')
            with ui.row().classes('gap-2 justify-end w-full'):
                ui.button('Cancel', on_click=dialog.close).props('flat').classes('text-[#71717a]')
                ui.button('Add', on_click=lambda: add_widget(
                    type_select.value, title_input.value or f"{metric_select.value}",
                    metric_select.value, size_select.value, dialog
                )).classes('bg-[#5c6fd0] text-white px-4 py-2 rounded-lg')

    def add_widget(widget_type, title, metric, size, dialog):
        widget = {
            'id': dashboard_state['next_id'],
            'type': widget_type,
            'title': title,
            'metric': metric,
            'size': size,
            'history': [],  # for charts
        }
        dashboard_state['next_id'] += 1
        dashboard_state['widgets'].append(widget)
        dialog.close()
        ui.notify(f"Widget '{title}' added", type='positive')
        refresh_dashboard()

    def remove_widget(widget_id):
        dashboard_state['widgets'] = [w for w in dashboard_state['widgets'] if w['id'] != widget_id]
        refresh_dashboard()

    def refresh_dashboard():
        dashboard_container.clear()
        widgets = dashboard_state['widgets']

        if not widgets:
            with dashboard_container:
                with ui.card().classes('w-full p-12 text-center') \
                    .style('background: rgba(255,255,255,0.02); border: 1px dashed rgba(255,255,255,0.1)'):
                    ui.label('◇').classes('text-4xl text-[#5c8af0] mb-2')
                    ui.label('No widgets yet').classes('text-[#e4e4e7] font-medium')
                    ui.label('Click "+ Add Widget" to build your dashboard').classes('text-[#52525b] text-sm')
            return

        # Render grid
        with dashboard_container:
            cols = 2 if widgets else 1
            for i in range(0, len(widgets), cols):
                with ui.row().classes('w-full gap-3'):
                    for widget in widgets[i:i+cols]:
                        _render_widget(widget)

    def _render_widget(widget):
        """Render a single dashboard widget."""
        size_classes = {'Small': 'min-w-36', 'Medium': 'flex-1', 'Large': 'w-full'}
        size_class = size_classes.get(widget['size'], 'flex-1')

        with ui.card().classes(f'p-4 {size_class}') \
            .style('background: #16181d; border-left: 2px solid #5c8af0'):
            with ui.row().classes('w-full items-center justify-between mb-2'):
                ui.label(widget['title']).classes('text-white font-medium text-sm')
                if dashboard_state['edit_mode']:
                    ui.button('✕', on_click=lambda w=widget: remove_widget(w['id'])).classes('text-[#ef4444] text-xs px-1')

            # Metric Card
            if widget['type'] == 'Metric Card':
                latest = telemetry_engine.get_latest_values(selected_device.id)
                val = latest.get(widget['metric'], 0)
                ui.label(f"{val:.2f}").classes('text-2xl font-medium text-white font-mono')
                ui.label(widget['metric']).classes('text-[#71717a] text-xs uppercase tracking-wider')

            # Gauge
            elif widget['type'] == 'Gauge':
                latest = telemetry_engine.get_latest_values(selected_device.id)
                val = latest.get(widget['metric'], 0)
                # Simple text-based gauge
                pct = min(100, max(0, (val / 100) * 100))  # assume 0-100 range
                filled = int(pct / 5)
                empty = 20 - filled
                ui.label(f"{val:.1f}").classes('text-xl font-medium text-white font-mono')
                ui.label('█' * filled + '░' * empty).classes('text-[#5c8af0] text-xs font-mono')
                ui.label(widget['metric']).classes('text-[#71717a] text-[10px] uppercase')

            # Line Chart (text-based sparkline)
            elif widget['type'] == 'Line Chart':
                history = widget.get('history', [])
                if len(history) > 1:
                    chart_vals = history[-20:]
                    max_v = max(chart_vals) if chart_vals else 1
                    min_v = min(chart_vals) if chart_vals else 0
                    range_v = max_v - min_v if max_v != min_v else 1
                    bars = []
                    for v in chart_vals:
                        height = int(((v - min_v) / range_v) * 8) if range_v > 0 else 4
                        bars.append(' ▁▂▃▄▅▆▇█'[min(height, 8)])
                    ui.label(''.join(bars)).classes('text-[#22c55e] text-lg font-mono leading-none')
                    ui.label(f"{history[-1]:.2f} ({min_v:.1f}-{max_v:.1f})").classes('text-[#71717a] text-xs font-mono')
                else:
                    ui.label('Collecting data...').classes('text-[#52525b] text-sm')
                ui.label(widget['metric']).classes('text-[#71717a] text-[10px] uppercase')

            # Alert Summary
            elif widget['type'] == 'Alert Summary':
                events = alert_engine.get_alert_history()
                unack = len([a for a in events if not a.get('acknowledged')])
                with ui.row().classes('items-center gap-2'):
                    alert_color = '#ef4444' if unack > 0 else '#22c55e'
                    ui.label(str(unack)).classes('text-xl font-medium').style(f'color: {alert_color}')
                    ui.label('unacked alerts').classes('text-[#71717a] text-xs')

            # Log Table
            elif widget['type'] == 'Log Table':
                with ui.column().classes('w-full gap-0.5 max-h-32 overflow-y-auto'):
                    for ts, line, ltype in terminal_state.get('lines', [])[-5:]:
                        color = {'error': '#ef4444', 'warn': '#eab308', 'metric': '#5c8af0', 'json': '#22c55e'}.get(ltype, '#e4e4e7')
                        ui.label(f"[{ts}] {line[:50]}").classes('text-xs font-mono').style(f'color: {color}')

    # Background update loop
    async def dashboard_refresh_loop():
        while True:
            await asyncio.sleep(2)
            # Update chart histories
            latest = telemetry_engine.get_latest_values(selected_device.id)
            for widget in dashboard_state['widgets']:
                if widget['type'] == 'Line Chart' and widget['metric'] in latest:
                    widget['history'].append(latest[widget['metric']])
                    if len(widget['history']) > 100:
                        widget['history'] = widget['history'][-100:]
            refresh_dashboard()

    asyncio.create_task(dashboard_refresh_loop())
    refresh_dashboard()


def alerts_page():
    """Alert management - rules, history, acknowledgment."""
    def refresh_alerts():
        rules = get_alert_rules()
        events = get_alert_events()

        # Stats
        unack = len([a for a in events if not a.get('acknowledged')])
        by_sev = {}
        for a in events:
            s = a.get('severity', 'warning')
            by_sev[s] = by_sev.get(s, 0) + 1
        with ui.row().classes('w-full gap-3 mb-4'):
            for label, val, color in [
                ('Unacknowledged', unack, '#ef4444'),
                ('Total Alerts', len(events), '#f7f8f8'),
                ('Critical', by_sev.get('critical', 0), '#ef4444'),
                ('Warning', by_sev.get('warning', 0), '#eab308'),
                ('Active Rules', len(rules), '#5c8af0'),
            ]:
                with ui.card().classes('flex-1 p-4') \
                    .style('background: #16181d; border-left: 2px solid #5c8af0'):
                    ui.label(str(val)).classes('text-xl font-medium').style(f'color: {color}')
                    ui.label(label).classes('text-[10px] text-[#71717a] uppercase tracking-widest')

        # Rules
        with ui.card().classes('w-full p-4 mb-4').style('background: #16181d; border-left: 2px solid #5c8af0'):
            with ui.row().classes('w-full items-center justify-between mb-3'):
                ui.label('Alert Rules').classes('text-white font-medium')
                ui.button('+ New Rule', on_click=show_add_rule_dialog).classes('bg-[#5c6fd0] text-white px-3 py-1 text-sm rounded-lg')

            if not rules:
                ui.label('No alert rules configured').classes('text-[#52525b] text-sm py-4')
            else:
                with ui.column().classes('w-full gap-3 p-6 max-w-[1400px] mx-auto'):
                    for rule in rules:
                        with ui.row().classes('w-full items-center justify-between p-2 rounded-lg').style('background: rgba(255,255,255,0.01)'):
                            with ui.row().classes('items-center gap-3'):
                                sev = severity_color(rule.severity or 'warning')
                                ui.label('●').style(f'color: {sev}').classes('text-xs')
                                with ui.column().classes('gap-0'):
                                    ui.label(rule.name).classes('text-[#e4e4e7] text-sm font-medium')
                                    ui.label(f"{rule.metric_name} {rule.condition} {rule.threshold}").classes('text-[#52525b] text-xs font-mono')
                            with ui.row().classes('gap-2 mt-1'):
                                ui.label(f"{rule.cooldown}s").classes('text-[#52525b] text-xs')
                                ui.button('Delete', on_click=lambda r=rule: delete_rule(r)).classes('bg-[rgba(229,72,77,0.1)] text-[#ef4444] px-2 py-0.5 text-xs rounded')

        # Alert history
        with ui.card().classes('w-full p-4').style('background: #16181d; border-left: 2px solid #5c8af0'):
            with ui.row().classes('w-full items-center justify-between mb-3'):
                ui.label('Recent Alerts').classes('text-white font-medium')
                if events:
                    ui.button('Ack All', on_click=ack_all).classes('bg-[rgba(255,255,255,0.03)] text-[#71717a] border border-[rgba(255,255,255,0.10)] px-3 py-1 text-sm rounded-lg')

            if not events:
                ui.label('No alerts yet').classes('text-[#52525b] text-sm py-4')
            else:
                with ui.column().classes('w-full gap-1 max-h-72 overflow-y-auto'):
                    for alert in reversed(events[-20:]):
                        acked = alert.get('acknowledged', False)
                        with ui.row().classes(f'w-full items-center gap-2 p-2 rounded-lg {"opacity-50" if acked else ""}').style('background: rgba(255,255,255,0.01)'):
                            sev = severity_color(alert.get('severity', 'warning'))
                            ui.label('●').style(f'color: {sev}').classes('text-xs')
                            ui.label(alert.get('timestamp', '')[:19]).classes('text-[#52525b] text-xs font-mono')
                            ui.label(alert.get('message', '')).classes(f'text-[#e4e4e7] text-sm flex-1 {"line-through" if acked else ""}')
                            if not acked:
                                ui.button('✓ Ack', on_click=lambda a=alert: ack_alert(a)).classes('bg-[rgba(113,112,255,0.1)] text-[#5c8af0] px-2 py-0.5 text-xs rounded font-medium')
                            else:
                                ui.label('✓ Acked').classes('text-[#22c55e] text-xs')

    def show_add_rule_dialog():
        dialog = ui.dialog()
        with dialog, ui.card().classes('p-6 w-96').style('background: #16181d; border: 1px solid rgba(255,255,255,0.10)'):
            ui.label('New Alert Rule').classes('text-white font-medium mb-4 text-lg')
            name = ui.input('Name', value='High Temperature').classes('mb-3 w-full').props('outlined').style('color: #e4e4e7')
            metric = ui.input('Metric', value='TEMP').classes('mb-3 w-full').props('outlined').style('color: #e4e4e7')
            condition = ui.select(['gt', 'lt', 'eq', 'range', 'change'], value='gt').classes('mb-1 w-full').props('outlined').style('color: #e4e4e7')
            ui.label('gt=greater than, lt=less than, eq=equals, range=outside range, change=delta exceeds threshold').classes('text-[#52525b] text-[10px] mb-3 ml-1')
            threshold_label = 'Min Δ (delta)' if condition.value == 'change' else 'Threshold'
            threshold = ui.number(threshold_label, value=30).classes('mb-3 w-full').props('outlined').style('color: #e4e4e7')
            cooldown = ui.number('Cooldown (s)', value=60).classes('mb-4 w-full').props('outlined').style('color: #e4e4e7')
            with ui.row().classes('gap-2 justify-end w-full'):
                ui.button('Cancel', on_click=dialog.close).props('flat').classes('text-[#71717a]')
                ui.button('Create', on_click=lambda: create_rule(
                    name.value, metric.value, condition.value, threshold.value, cooldown.value, dialog
                )).classes('bg-[#5c6fd0] text-white px-4 py-2 rounded-lg')

    async def create_rule(name, metric, condition, threshold, cooldown, dialog):
        rule = AlertRule(
            id=str(uuid.uuid4()),
            name=name, metric_name=metric, condition=condition,
            threshold=threshold, cooldown=cooldown
        )
        alert_engine.add_rule(rule)
        dialog.close()
        ui.notify(f"Rule '{name}' created", type='positive')
        refresh_alerts()

    async def delete_rule(rule):
        alert_engine.remove_rule(rule.id)
        refresh_alerts()

    async def ack_alert(alert):
        alert_engine.acknowledge_alert(alert.get('id', ''))
        refresh_alerts()

    async def ack_all():
        for alert in get_alert_events():
            alert_engine.acknowledge_alert(alert.get('id', ''))
        refresh_alerts()

    # Poll for new alerts every 2 seconds and show toast notifications
    import asyncio
    _last_alert_count = len(get_alert_events())

    async def check_new_alerts():
        nonlocal _last_alert_count
        while True:
            await asyncio.sleep(2)
            current = get_alert_events()
            if len(current) > _last_alert_count:
                new = current[_last_alert_count:]
                for a in new:
                    if not a.get('acknowledged'):
                        sev = a.get('severity', 'warning')
                        color = {'critical': 'negative', 'warning': 'warning', 'info': 'info'}.get(sev, 'info')
                        ui.notify(f"🚨 {a.get('message', '')}", type=color, timeout=6000)
                _last_alert_count = len(current)

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
    """Session detail with timeline replay."""
    global selected_session

    if not selected_session:
        ui.label('No session selected').classes('text-[#52525b]').style('padding: 40px')
        return

    session = selected_session

    with ui.column().classes('w-full gap-4'):
        with ui.row().classes('w-full items-center gap-3'):
            ui.button('← Back', on_click=go_back).classes('bg-[rgba(255,255,255,0.03)] text-[#71717a] border border-[rgba(255,255,255,0.10)] px-3 py-1 text-sm rounded-lg')
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
                        ui.button('▶ Replay', on_click=start_replay).classes('bg-[#5c6fd0] text-white px-3 py-1 text-sm rounded-lg')
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

    def go_back():
        global current_tab, selected_session
        current_tab = 'sessions'
        selected_session = None
        rebuild()

    async def start_replay():
        ui.notify('Replay started', type='info')


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
                ui.button('+ Add Broker', on_click=show_add_broker_dialog).classes('bg-[#5c6fd0] text-white px-3 py-1 text-sm rounded-lg')

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
    def show_add_broker_dialog():
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

    with ui.column().classes('w-full gap-4'):
        # DBC file loader
        with ui.card().classes('w-full p-4').style('background: rgba(255,255,255,0.02); border: 1px solid rgba(113,112,255,0.2)'):
            with ui.row().classes('w-full items-center justify-between mb-2'):
                ui.label('📁 CAN Database (.dbc)').classes('text-white font-medium')
                ui.button('Load DBC File', on_click=show_dbc_upload_dialog).classes('bg-[#5c8af0] text-white px-3 py-1 text-sm rounded-lg')
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

        def show_dbc_upload_dialog():
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


@ui.page('/')
def main_page():
    global content_container

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
