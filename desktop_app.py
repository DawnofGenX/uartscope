"""UARTScope Pro — Desktop Application (NiceGUI)"""
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

def format_duration(started, ended=None):
    try:
        s = datetime.fromisoformat(started)
        e = datetime.fromisoformat(ended) if ended else datetime.utcnow()
        d = int((e - s).total_seconds())
    except:
        return "—"
    if d < 60: return f"{d}s"
    if d < 3600: return f"{d//60}m {d%60}s"
    return f"{d//3600}h {(d%3600)//60}m"

def severity_color(sev):
    return {'critical': '#e5484d', 'warning': '#f5a623', 'info': '#3b82f6'}.get(sev, '#8a8f98')

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
    with ui.left_drawer(fixed=True).classes('bg-[#0f1011] border-r border-[rgba(255,255,255,0.05)]').style('width: 220px'):
        with ui.column().classes('p-4 gap-1'):
            with ui.row().classes('items-center gap-2 mb-6'):
                ui.label('◈').classes('text-[#7170ff] text-xl')
                ui.label('UARTScope').classes('text-white font-medium')

            nav_items = [
                ('devices', '◈', 'Devices'),
                ('terminal', '▸', 'Terminal'),
                ('charts', '◇', 'Charts'),
                ('alerts', '◉', 'Alerts'),
                ('sessions', '⟳', 'Sessions'),
                ('decoder', '⬡', 'Decoder'),
            ]

            for tab_id, icon, label in nav_items:
                is_active = current_tab == tab_id
                bg = 'rgba(255,255,255,0.05)' if is_active else 'transparent'
                text_color = '#f7f8f8' if is_active else '#8a8f98'
                active_border = 'border-l-2 border-[#7170ff]' if is_active else ''
                ui.button(
                    f'{icon}  {label}',
                    on_click=lambda t=tab_id: switch_tab(t)
                ).props(f'flat no-caps').classes(
                    f'w-full justify-start px-3 py-2 rounded-md text-left {active_border}'
                ).style(f'background: {bg}; color: {text_color}')

        # Footer stats
        stats = get_stats()
        with ui.column().classes('mt-auto p-4 border-t border-[rgba(255,255,255,0.05)] gap-2'):
            with ui.row().classes('justify-between'):
                ui.label(f"{stats['connected']}/{stats['total']}").classes('text-white text-sm font-mono')
                ui.label('Devices').classes('text-[#62666d] text-xs uppercase')
            with ui.row().classes('justify-between'):
                ui.label(format_bytes(stats['total_bytes_received'])).classes('text-white text-sm font-mono')
                ui.label('Data').classes('text-[#62666d] text-xs uppercase')


# ─── Pages ───────────────────────────────────────────────────────────────────

def devices_page():
    """Devices panel — register, start/stop, auto-reconnect."""
    container = ui.column().classes('w-full gap-3')

    def refresh_devices():
        stats = get_stats()
        devices = get_devices()
        container.clear()

        # Stats bar
        with ui.row().classes('w-full gap-3 mb-2'):
            for label, val in [
                ('Devices', f"{stats['connected']}/{stats['total']}"),
                ('Data', format_bytes(stats['total_bytes_received'])),
                ('Streaming', str(stats['streaming'])),
                ('WS Clients', str(stats.get('websocket_clients', 0))),
            ]:
                with ui.card().classes('flex-1 p-3') \
                    .style('background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05)'):
                    ui.label(val).classes('text-xl font-medium text-white')
                    ui.label(label).classes('text-[10px] text-[#8a8f98] uppercase tracking-wider')

        if not devices:
            with container:
                with ui.card().classes('w-full p-8 text-center') \
                    .style('background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05)'):
                    ui.label('◈').classes('text-4xl text-[#23252a] mb-2')
                    ui.label('No devices registered').classes('text-[#d0d6e0] font-medium')
                    ui.label('Connect a serial device to get started').classes('text-[#62666d] text-sm')
        else:
            for device in devices:
                with container:
                    with ui.card().classes('w-full p-4') \
                        .style('background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05)'):
                        with ui.row().classes('w-full items-center justify-between'):
                            with ui.column().classes('gap-1'):
                                with ui.row().classes('items-center gap-2'):
                                    sc = '#27a644' if device.status == 'streaming' else ('#3b82f6' if device.status == 'connected' else '#62666d')
                                    ui.label('●').classes('text-xs').style(f'color: {sc}')
                                    ui.label(device.name or 'Unnamed').classes('text-white font-medium')
                                ui.label(f"{device.port} · {device.baudrate} baud").classes('text-[#62666d] text-xs font-mono')
                            with ui.row().classes('gap-2'):
                                if device.status == 'streaming':
                                    ui.button('Stop', on_click=lambda d=device: stop_device(d)).classes('bg-[#e5484d] text-white px-3 py-1 text-sm rounded-md')
                                    ui.button('Terminal', on_click=lambda d=device: open_terminal(d)).classes('bg-[#5e6ad2] text-white px-3 py-1 text-sm rounded-md')
                                else:
                                    ui.button(f"{'⟳ Auto' if device.auto_reconnect else '⟳ Manual'}",
                                              on_click=lambda d=device: toggle_reconnect(d)).classes('bg-[rgba(255,255,255,0.03)] text-[#8a8f98] border border-[rgba(255,255,255,0.08)] px-3 py-1 text-sm rounded-md')
                                    ui.button('Start', on_click=lambda d=device: start_device(d)).classes('bg-[#5e6ad2] text-white px-3 py-1 text-sm rounded-md')

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
    """Terminal view — real-time serial output."""
    global selected_device

    if not selected_device:
        ui.label('No device selected — go to Devices tab').classes('text-[#62666d]').style('padding: 40px')
        return

    ui.label(f"Device: {selected_device.name} ({selected_device.port})").classes('text-[#8a8f98] text-sm mb-2')

    log_area = ui.column().classes('w-full gap-0.5 overflow-y-auto') \
        .style('max-height: 60vh; background: #0f1011; padding: 12px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.05); font-family: JetBrains Mono, monospace; font-size: 13px; width: 100%')

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
                with log_area:
                    ts = datetime.utcnow().strftime('%H:%M:%S')
                    ui.label(f"[{ts}] {line}").classes('text-[#d0d6e0] leading-relaxed')
        except asyncio.TimeoutError:
            pass

    asyncio.create_task(stream_loop())


def charts_page():
    """Live charts — telemetry visualization."""
    global selected_device

    if not selected_device:
        ui.label('Select a device from Devices tab to view charts').classes('text-[#62666d]').style('padding: 40px')
        return

    ui.label(f"Live Telemetry — {selected_device.name}").classes('text-[#d0d6e0] font-medium mb-4')

    latest = telemetry_engine.get_latest_values(selected_device.id)
    if latest:
        with ui.row().classes('w-full gap-3 flex-wrap'):
            for name, value in latest.items():
                with ui.card().classes('p-4 min-w-32') \
                    .style('background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05)'):
                    ui.label(f"{value:.2f}").classes('text-xl font-medium text-white font-mono')
                    ui.label(name).classes('text-[#8a8f98] text-xs uppercase tracking-wider')
    else:
        ui.label('Waiting for telemetry data...').classes('text-[#62666d]')


def alerts_page():
    """Alert management — rules, history, acknowledgment."""
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
                ('Unacknowledged', unack, '#e5484d'),
                ('Total Alerts', len(events), '#f7f8f8'),
                ('Critical', by_sev.get('critical', 0), '#e5484d'),
                ('Warning', by_sev.get('warning', 0), '#f5a623'),
                ('Active Rules', len(rules), '#7170ff'),
            ]:
                with ui.card().classes('flex-1 p-3') \
                    .style('background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05)'):
                    ui.label(str(val)).classes('text-xl font-medium').style(f'color: {color}')
                    ui.label(label).classes('text-[10px] text-[#8a8f98] uppercase tracking-wider')

        # Rules
        with ui.card().classes('w-full p-4 mb-4').style('background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05)'):
            with ui.row().classes('w-full items-center justify-between mb-3'):
                ui.label('Alert Rules').classes('text-white font-medium')
                ui.button('+ New Rule', on_click=show_add_rule_dialog).classes('bg-[#5e6ad2] text-white px-3 py-1 text-sm rounded-md')

            if not rules:
                ui.label('No alert rules configured').classes('text-[#62666d] text-sm py-4')
            else:
                with ui.column().classes('w-full gap-2'):
                    for rule in rules:
                        with ui.row().classes('w-full items-center justify-between p-2 rounded-md').style('background: rgba(255,255,255,0.01)'):
                            with ui.row().classes('items-center gap-3'):
                                sev = severity_color(rule.severity or 'warning')
                                ui.label('●').style(f'color: {sev}').classes('text-xs')
                                with ui.column().classes('gap-0'):
                                    ui.label(rule.name).classes('text-[#d0d6e0] text-sm font-medium')
                                    ui.label(f"{rule.metric_name} {rule.condition} {rule.threshold}").classes('text-[#62666d] text-xs font-mono')
                            with ui.row().classes('gap-2'):
                                ui.label(f"{rule.cooldown}s").classes('text-[#62666d] text-xs')
                                ui.button('Delete', on_click=lambda r=rule: delete_rule(r)).classes('bg-[rgba(229,72,77,0.1)] text-[#e5484d] px-2 py-0.5 text-xs rounded')

        # Alert history
        with ui.card().classes('w-full p-4').style('background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05)'):
            with ui.row().classes('w-full items-center justify-between mb-3'):
                ui.label('Recent Alerts').classes('text-white font-medium')
                if events:
                    ui.button('Ack All', on_click=ack_all).classes('bg-[rgba(255,255,255,0.03)] text-[#8a8f98] border border-[rgba(255,255,255,0.08)] px-3 py-1 text-sm rounded-md')

            if not events:
                ui.label('No alerts yet').classes('text-[#62666d] text-sm py-4')
            else:
                with ui.column().classes('w-full gap-1 max-h-72 overflow-y-auto'):
                    for alert in reversed(events[-20:]):
                        acked = alert.get('acknowledged', False)
                        with ui.row().classes(f'w-full items-center gap-2 p-2 rounded-md {"opacity-50" if acked else ""}').style('background: rgba(255,255,255,0.01)'):
                            sev = severity_color(alert.get('severity', 'warning'))
                            ui.label('●').style(f'color: {sev}').classes('text-xs')
                            ui.label(alert.get('timestamp', '')[:19]).classes('text-[#62666d] text-xs font-mono')
                            ui.label(alert.get('message', '')).classes(f'text-[#d0d6e0] text-sm flex-1 {"line-through" if acked else ""}')
                            if not acked:
                                ui.button('✓ Ack', on_click=lambda a=alert: ack_alert(a)).classes('bg-[rgba(113,112,255,0.1)] text-[#7170ff] px-2 py-0.5 text-xs rounded font-medium')
                            else:
                                ui.label('✓ Acked').classes('text-[#27a644] text-xs')

    def show_add_rule_dialog():
        dialog = ui.dialog()
        with dialog, ui.card().classes('p-6 w-96').style('background: #191a1b; border: 1px solid rgba(255,255,255,0.08)'):
            ui.label('New Alert Rule').classes('text-white font-medium mb-4 text-lg')
            name = ui.input('Name', value='High Temperature').classes('mb-3 w-full').props('outlined').style('color: #d0d6e0')
            metric = ui.input('Metric', value='TEMP').classes('mb-3 w-full').props('outlined').style('color: #d0d6e0')
            condition = ui.select(['gt', 'lt', 'eq', 'range', 'change'], value='gt').classes('mb-1 w-full').props('outlined').style('color: #d0d6e0')
            ui.label('gt=greater than, lt=less than, eq=equals, range=outside range, change=delta exceeds threshold').classes('text-[#62666d] text-[10px] mb-3 ml-1')
            threshold_label = 'Min Δ (delta)' if condition.value == 'change' else 'Threshold'
            threshold = ui.number(threshold_label, value=30).classes('mb-3 w-full').props('outlined').style('color: #d0d6e0')
            cooldown = ui.number('Cooldown (s)', value=60).classes('mb-4 w-full').props('outlined').style('color: #d0d6e0')
            with ui.row().classes('gap-2 justify-end w-full'):
                ui.button('Cancel', on_click=dialog.close).props('flat').classes('text-[#8a8f98]')
                ui.button('Create', on_click=lambda: create_rule(
                    name.value, metric.value, condition.value, threshold.value, cooldown.value, dialog
                )).classes('bg-[#5e6ad2] text-white px-4 py-2 rounded-md')

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
                with ui.card().classes('flex-1 p-3') \
                    .style('background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05)'):
                    ui.label(str(val)).classes('text-xl font-medium text-white')
                    ui.label(label).classes('text-[10px] text-[#8a8f98] uppercase tracking-wider')

        if not sessions:
            with ui.card().classes('w-full p-8 text-center') \
                .style('background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05)'):
                ui.label('⟳').classes('text-4xl text-[#23252a] mb-2')
                ui.label('No sessions yet').classes('text-[#d0d6e0] font-medium')
                ui.label('Start streaming to create sessions').classes('text-[#62666d] text-sm')
        else:
            with ui.column().classes('w-full gap-2'):
                for session in reversed(sessions):
                    with ui.card().classes('w-full p-4 cursor-pointer hover:border-[rgba(255,255,255,0.12)]') \
                        .style('background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05)') \
                        .on('click', lambda s=session: open_session(s)):
                        with ui.row().classes('w-full items-center justify-between'):
                            with ui.row().classes('items-center gap-3'):
                                is_live = session.get('status') == 'recording'
                                ui.label('●').classes('text-xs').style(f'color: {"#27a644" if is_live else "#62666d"}')
                                with ui.column().classes('gap-0.5'):
                                    ui.label(session.get('name', 'Unnamed')).classes('text-white font-medium text-sm')
                                    ui.label(f"{session.get('packet_count', 0)} pkts · {session.get('metric_count', 0)} metrics").classes('text-[#62666d] text-xs font-mono')
                            with ui.row().classes('items-center gap-2'):
                                if is_live:
                                    ui.label('● LIVE').classes('text-[#27a644] text-xs font-medium')
                                ui.label(format_duration(session.get('started_at', ''), session.get('ended_at'))).classes('text-[#8a8f98] text-xs font-mono')

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
        ui.label('No session selected').classes('text-[#62666d]').style('padding: 40px')
        return

    session = selected_session

    with ui.column().classes('w-full gap-4'):
        with ui.row().classes('w-full items-center gap-3'):
            ui.button('← Back', on_click=go_back).classes('bg-[rgba(255,255,255,0.03)] text-[#8a8f98] border border-[rgba(255,255,255,0.08)] px-3 py-1 text-sm rounded-md')
            with ui.column():
                ui.label(session.get('name', 'Unnamed')).classes('text-white font-medium')
                ui.label(f"{session.get('packet_count', 0)} packets").classes('text-[#62666d] text-xs')

        # Tabs
        tabs = ui.tabs().classes('w-full')
        with tabs:
            t1 = ui.tab('Timeline')
            t2 = ui.tab('Metrics')
            t3 = ui.tab('Export')

        with ui.tab_panels(tabs, value=t1).classes('w-full p-0'):
            with ui.tab_panel(t1):
                with ui.column().classes('w-full gap-3'):
                    with ui.row().classes('w-full items-center gap-3'):
                        ui.button('▶ Replay', on_click=start_replay).classes('bg-[#5e6ad2] text-white px-3 py-1 text-sm rounded-md')
                        ui.select([0.5, 1, 2, 5, 10], value=1).classes('bg-[rgba(255,255,255,0.02)] text-[#d0d6e0] border border-[rgba(255,255,255,0.08)] px-2 py-1 text-sm rounded-md')
                        ui.label(f"0 packets").classes('text-[#8a8f98] text-xs font-mono')

                    ui.label('Timeline replay coming soon').classes('text-[#62666d] text-sm py-4')

            with ui.tab_panel(t2):
                ui.label('Metrics chart coming soon').classes('text-[#62666d] py-8')

            with ui.tab_panel(t3):
                with ui.column().classes('w-full gap-3'):
                    ui.button('Export JSON', on_click=lambda: ui.notify('JSON export', type='info')).classes('bg-[#5e6ad2] text-white px-4 py-2 rounded-md w-full')
                    ui.button('Export CSV', on_click=lambda: ui.notify('CSV export', type='info')).classes('bg-[rgba(255,255,255,0.03)] text-[#8a8f98] border border-[rgba(255,255,255,0.08)] px-4 py-2 rounded-md w-full')

    def go_back():
        global current_tab, selected_session
        current_tab = 'sessions'
        selected_session = None
        rebuild()

    async def start_replay():
        ui.notify('Replay started', type='info')


def decoder_page():
    """Protocol decoder — hex input, decode, structured output."""
    with ui.column().classes('w-full gap-4'):
        with ui.row().classes('w-full items-center gap-3'):
            protocol = ui.select(
                ['auto'] + [p['id'] for p in protocol_manager.list_decoders()],
                value='auto', label='Protocol'
            ).classes('bg-[rgba(255,255,255,0.02)] text-[#d0d6e0] border border-[rgba(255,255,255,0.08)] px-3 py-2 rounded-md w-48')
            raw_input = ui.input('Hex Data', placeholder='e.g. 7848656C6C6F00 or 010300010001').classes('flex-1').props('outlined').style('color: #d0d6e0; font-family: JetBrains Mono, monospace')
            ui.button('Decode', on_click=lambda: do_decode(raw_input.value, protocol.value)).classes('bg-[#5e6ad2] text-white px-4 py-2 rounded-md')

        result_container = ui.column().classes('w-full gap-2')

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
                        ui.label('No protocol detected').classes('text-[#e5484d]').style('padding: 20px')
                    return
                proto_id = decoder.protocol_id

            decoded = protocol_manager.decode(proto_id, raw_data)
            decoder = protocol_manager.get_decoder(proto_id)

            with result_container:
                with ui.card().classes('w-full p-4').style('background: rgba(255,255,255,0.02); border: 1px solid rgba(113,112,255,0.2)'):
                    with ui.row().classes('items-center gap-2 mb-3'):
                        ui.label(decoder.name).classes('text-[#7170ff] font-medium text-sm').style('background: rgba(113,112,255,0.15); padding: 2px 8px; border-radius: 9999px')
                        ui.label(proto_id).classes('text-[#62666d] text-xs font-mono')
                    with ui.column().classes('gap-1 font-mono text-sm'):
                        for key, value in decoded.items():
                            with ui.row().classes('gap-3'):
                                ui.label(key).classes('text-[#8a8f98] min-w-32')
                                ui.label(str(value)).classes('text-[#d0d6e0]')


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
