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

from app.core.device_manager import device_manager
from app.core.telemetry_engine import telemetry_engine
from app.core.session_recorder import session_recorder
from app.core.alert_engine import alert_engine, AlertRule
from app.core.serial_reader import serial_reader
from app.core.websocket_hub import ws_manager
from app.core.protocol_decoder import protocol_manager
from app.core.performance_tracker import performance_tracker
from app.core.mqtt_client import mqtt_manager

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
    return {'critical': '#ef4444', 'warning': '#eab308', 'info': '#3b82f6'}.get(sev, '#71717a')

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
def build_sidebar():
    with ui.left_drawer(fixed=True).classes('bg-[#0d0f12] border-r border-[rgba(255,255,255,0.06)]').style('width: 56px'):
        with ui.column().classes('px-2 py-4 gap-0.5'):
            with ui.row().classes('items-center gap-2 mb-6'):
                ui.label('◈').classes('text-[#5c8af0] text-xl')
                ui.label('UART').classes('text-white font-semibold text-sm tracking-wide')

            nav_items = [
                ('devices', '◈', 'Devices'),
                ('terminal', '▸', 'Terminal'),
                ('charts', '◇', 'Charts'),
                ('performance', '⚡', 'Performance'),
                ('mqtt', '☁', 'MQTT'),
                ('alerts', '◉', 'Alerts'),
                ('sessions', '⟳', 'Sessions'),
                ('decoder', '⬡', 'Decoder'),
                ('marketplace', '🛒', 'Marketplace'),
            ]

            for tab_id, icon, label in nav_items:
                is_active = current_tab == tab_id
                bg = 'rgba(255,255,255,0.06)' if is_active else 'transparent'
                text_color = '#f7f8f8' if is_active else '#71717a'
                active_border = 'border-l-[3px] border-[#5c8af0]' if is_active else ''
                ui.button(
                    f'{icon}',
                    on_click=lambda t=tab_id: switch_tab(t)
                ).props(f'flat no-caps').classes(
                    f'w-full justify-center px-0 py-2.5 rounded-lg text-center {active_border}'
                ).style(f'background: {bg}; color: {text_color}')

        # Footer stats
        stats = get_stats()
        with ui.column().classes('mt-auto px-3 py-4 border-t border-[rgba(255,255,255,0.06)] gap-3'):
            with ui.row().classes('justify-between'):
                ui.label(f"{stats['connected']}/{stats['total']}").classes('text-white text-sm font-mono')
                ui.label('DEV').classes('text-[#52525b] text-[10px] uppercase tracking-widest')
            with ui.row().classes('justify-between'):
                ui.label(format_bytes(stats['total_bytes_received'])).classes('text-white text-sm font-mono')
                ui.label('DATA').classes('text-[#52525b] text-[10px] uppercase tracking-widest')


# ─── Pages ───────────────────────────────────────────────────────────────────

def devices_page():
    """Devices panel - register, start/stop, auto-reconnect."""
    container = ui.column().classes('w-full gap-4 p-6 max-w-[1400px] mx-auto')

    def refresh_devices():
        stats = get_stats()
        devices = get_devices()
        container.clear()

        # Stats bar
        with ui.row().classes('w-full gap-3 mb-4'):
            for label, val in [
                ('Devices', f"{stats['connected']}/{stats['total']}"),
                ('Data', format_bytes(stats['total_bytes_received'])),
                ('Streaming', str(stats['streaming'])),
                ('WS Clients', str(stats.get('websocket_clients', 0))),
            ]:
                with ui.card().classes('flex-1 p-4') \
                    .style('background: #16181d; border-left: 2px solid #5c8af0'):
                    ui.label(val).classes('text-2xl font-semibold text-white')
                    ui.label(label).classes('text-[10px] text-[#71717a] uppercase tracking-widest')

        if not devices:
            with container:
                with ui.card().classes('w-full p-12 text-center') \
                    .style('background: #16181d; border-left: 2px solid #5c8af0'):
                    ui.label('◈').classes('text-4xl text-[#5c8af0] mb-2')
                    ui.label('No devices connected').classes('text-[#e4e4e7] font-semibold text-lg')
                    ui.label('Connect a serial device to start monitoring').classes('text-[#52525b] text-sm mt-1')
        else:
            for device in devices:
                with container:
                    with ui.card().classes('w-full p-4') \
                        .style('background: #16181d; border-left: 2px solid #5c8af0'):
                        with ui.row().classes('w-full items-center justify-between mb-3'):
                            with ui.column().classes('gap-0.5'):
                                with ui.row().classes('items-center gap-2'):
                                    sc = '#22c55e' if device.status == 'streaming' else ('#3b82f6' if device.status == 'connected' else '#52525b')
                                    ui.label(' ').classes('inline-block w-2 h-2 rounded-full').style(f'background: {sc}')
                                    ui.label(device.name or 'Unnamed').classes('text-white font-semibold')
                                ui.label(f"{device.port} · {device.baudrate} baud").classes('text-[#52525b] text-xs font-mono')
                            with ui.row().classes('gap-2 mt-1'):
                                if device.status == 'streaming':
                                    ui.button('Stop', on_click=lambda d=device: stop_device(d)).classes('bg-[#ef4444] text-white px-4 py-1.5 text-sm rounded-lg font-medium')
                                    ui.button('Terminal', on_click=lambda d=device: open_terminal(d)).classes('bg-[#5c6fd0] text-white px-4 py-1.5 text-sm rounded-lg font-medium')
                                else:
                                    ui.button(f"{'⟳ Auto' if device.auto_reconnect else '⟳ Manual'}",
                                              on_click=lambda d=device: toggle_reconnect(d)).classes('bg-[rgba(255,255,255,0.03)] text-[#71717a] border border-[rgba(255,255,255,0.10)] px-3 py-1 text-sm rounded-lg')
                                    ui.button('Start', on_click=lambda d=device: start_device(d)).classes('bg-[#5c6fd0] text-white px-4 py-1.5 text-sm rounded-lg font-medium')

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
                    await alert_engine.evaluate(dev_id, session_id, Metric(name=mn, value=val, unit=None, message_type="metric"))

            await serial_reader.start_device(device_manager._devices[device.id], session_id, on_data)
            ui.notify(f"Started streaming from {device.name}", type='positive')
            refresh_devices()
        except Exception as e:
            ui.notify(f"Failed: {e}", type='negative')

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
            ui.notify(f"Failed: {e}", type='negative')

    async def toggle_reconnect(device):
        device.auto_reconnect = not device.auto_reconnect
        refresh_devices()

    def open_terminal(device):
        global selected_device, current_tab
        selected_device = device
        current_tab = 'terminal'
        rebuild()

    refresh_devices()


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


@ui.page('/')
def main_page():
    global content_container

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

    # Content area
    content_container = ui.column().classes('p-6 w-full').style('max-width: 1000px; margin: 0 auto')
    render_content()


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        title='UARTScope Pro',
        port=3000,
        host='0.0.0.0',
        dark=True,
        reload=False,
        show=False,
        favicon='🎯',
    )
