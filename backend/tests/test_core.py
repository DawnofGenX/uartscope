import pytest
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.core.telemetry_engine import TelemetryEngine, Metric, ParsedMessage
from app.core.device_manager import DeviceManager, DeviceInfo, DeviceCreate
from app.core.alert_engine import AlertEngine, AlertRule
from app.core.performance_tracker import PerformanceTracker, DevicePerformance
from app.core.protocol_decoder import (
    UARTTextDecoder, ModbusRTUDecoder, I2CDecoder, SPIDecoder, CANDecoder, DBCDecoder
)
from app.core.mqtt_client import MQTTManager, MQTTConnectionProfile


# ─── Telemetry Engine ─────────────────────────────────────────────────────────

class TestTelemetryEngine:
    def setup_method(self):
        self.engine = TelemetryEngine()

    @pytest.mark.asyncio
    async def test_process_line_key_value(self):
        await self.engine.process_line("dev1", "sess1", "TEMP:25.5")
        latest = self.engine.get_latest_values("dev1")
        assert "TEMP" in latest
        assert latest["TEMP"] == 25.5

    @pytest.mark.asyncio
    async def test_process_line_json(self):
        await self.engine.process_line("dev1", "sess1", '{"temp": 30, "humidity": 60}')
        latest = self.engine.get_latest_values("dev1")
        assert "TEMP" in latest
        assert latest["TEMP"] == 30.0

    @pytest.mark.asyncio
    async def test_metric_history(self):
        for i in range(10):
            await self.engine.process_line("dev1", "sess1", f"VOLTAGE:{3.0 + i * 0.1}")
        history = self.engine.get_history("dev1", "VOLTAGE")
        assert len(history) == 10
        assert history[-1].value == 3.9

    @pytest.mark.asyncio
    async def test_clear_history(self):
        await self.engine.process_line("dev1", "sess1", "TEMP:20")
        self.engine.clear_history("dev1")
        latest = self.engine.get_latest_values("dev1")
        assert len(latest) == 0

    @pytest.mark.asyncio
    async def test_infer_unit(self):
        assert self.engine._infer_unit("temp") == "°C"
        assert self.engine._infer_unit("voltage") == "V"
        assert self.engine._infer_unit("humidity") == "%"
        assert self.engine._infer_unit("pressure") == "hPa"
        assert self.engine._infer_unit("unknown") is None


# ─── Device Manager ───────────────────────────────────────────────────────────

class TestDeviceManager:
    def setup_method(self):
        self.manager = DeviceManager()

    @pytest.mark.asyncio
    async def test_add_device(self):
        create = DeviceCreate(name="Test", port="/dev/ttyUSB0", protocol="uart", baudrate=115200)
        device = await self.manager.add_device(create)
        assert device.id is not None
        assert device.name == "Test"

    @pytest.mark.asyncio
    async def test_get_all_devices(self):
        await self.manager.add_device(DeviceCreate(name="D1", port="/dev/ttyUSB0", protocol="uart", baudrate=115200))
        await self.manager.add_device(DeviceCreate(name="D2", port="/dev/ttyUSB1", protocol="uart", baudrate=115200))
        devices = self.manager.get_all_devices()
        assert len(devices) == 2

    def test_get_stats_empty(self):
        stats = self.manager.get_stats()
        assert stats['total'] == 0
        assert stats['connected'] == 0

    def test_guess_board(self):
        from unittest.mock import MagicMock
        port = MagicMock()
        port.description = "CH340"
        port.manufacturer = ""
        assert "CH340" in self.manager._guess_board(port) or "Arduino" in self.manager._guess_board(port)


# ─── Alert Engine ─────────────────────────────────────────────────────────────

class TestAlertEngine:
    def setup_method(self):
        self.engine = AlertEngine()

    @pytest.mark.asyncio
    async def test_add_rule(self):
        rule = AlertRule(id="r1", name="High Temp", metric_name="TEMP", condition="gt", threshold=40, cooldown=10)
        self.engine.add_rule(rule)
        assert len(self.engine.get_all_rules()) == 1

    @pytest.mark.asyncio
    async def test_evaluate_gt_trigger(self):
        self.engine.add_rule(AlertRule(id="r1", name="Hot", metric_name="TEMP", condition="gt", threshold=30, cooldown=0))
        metric = Metric(name="TEMP", value=35)
        await self.engine.evaluate("dev1", "sess1", metric)
        events = self.engine.get_alert_history()
        assert len(events) == 1

    @pytest.mark.asyncio
    async def test_evaluate_no_trigger(self):
        self.engine.add_rule(AlertRule(id="r1", name="Hot", metric_name="TEMP", condition="gt", threshold=50, cooldown=0))
        metric = Metric(name="TEMP", value=35)
        await self.engine.evaluate("dev1", "sess1", metric)
        events = self.engine.get_alert_history()
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_acknowledge_alert(self):
        self.engine.add_rule(AlertRule(id="r1", name="Hot", metric_name="TEMP", condition="gt", threshold=30, cooldown=0))
        await self.engine.evaluate("dev1", "sess1", Metric(name="TEMP", value=40))
        alert = self.engine.get_alert_history()[0]
        self.engine.acknowledge_alert(alert['id'])
        events = self.engine.get_alert_history()
        assert events[0]['acknowledged'] == True

    @pytest.mark.asyncio
    async def test_remove_rule(self):
        self.engine.add_rule(AlertRule(id="r1", name="Test", metric_name="TEMP", condition="gt", threshold=30, cooldown=0))
        self.engine.remove_rule("r1")
        assert len(self.engine.get_all_rules()) == 0

    def test_get_stats_empty(self):
        assert len(self.engine.get_all_rules()) == 0
        assert len(self.engine.get_alert_history()) == 0


# ─── Performance Tracker ──────────────────────────────────────────────────────

class TestPerformanceTracker:
    def setup_method(self):
        self.tracker = PerformanceTracker()

    @pytest.mark.asyncio
    async def test_on_device_connected(self):
        await self.tracker.on_device_connected("dev1", "Test Device")
        perf = self.tracker.get_device_perf("dev1")
        assert perf is not None
        assert perf.device_name == "Test Device"

    @pytest.mark.asyncio
    async def test_on_packet_received(self):
        await self.tracker.on_device_connected("dev1", "Test")
        await self.tracker.on_packet_received("dev1", 50, 5.0)
        perf = self.tracker.get_device_perf("dev1")
        assert perf.total_bytes == 50
        assert perf.total_packets == 1
        assert perf.avg_latency_ms == 5.0

    @pytest.mark.asyncio
    async def test_on_error(self):
        await self.tracker.on_device_connected("dev1", "Test")
        await self.tracker.on_error("dev1", "checksum")
        perf = self.tracker.get_device_perf("dev1")
        assert perf.error_count == 1
        assert perf.checksum_errors == 1

    def test_get_stats_empty(self):
        stats = self.tracker.get_summary()
        assert stats['total_bytes'] == 0
        assert stats['total_packets'] == 0

    @pytest.mark.asyncio
    async def test_on_device_disconnected(self):
        await self.tracker.on_device_connected("dev1", "Test")
        await self.tracker.on_device_disconnected("dev1")
        perf = self.tracker.get_device_perf("dev1")
        assert perf.disconnected_at is not None


# ─── Protocol Decoders ────────────────────────────────────────────────────────

class TestProtocolDecoders:
    def test_uart_text_decode(self):
        dec = UARTTextDecoder()
        result = dec.decode(b"TEMP:25.5")
        assert result["type"] == "text"
        assert "TEMP" in result.get("content", "")

    def test_uart_text_at_command(self):
        dec = UARTTextDecoder()
        result = dec.decode(b"AT+STATUS\r\n")
        assert result.get("subtype") == "at_command"

    def test_modbus_rtu_decode(self):
        dec = ModbusRTUDecoder()
        result = dec.decode(bytes([0x01, 0x03, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00]))
        assert result["type"] == "modbus_rtu"
        assert result["device_addr"] == 1
        assert result["function_name"] == "Read Holding Registers"

    def test_i2c_decode(self):
        dec = I2CDecoder()
        result = dec.decode(bytes([0x3D, 0x00, 0xFF, 0x00]))
        assert result["type"] == "i2c"
        assert "0x1E" in result.get("address_7bit", "")

    def test_spi_decode(self):
        dec = SPIDecoder()
        result = dec.decode(bytes([0x06]))
        assert result["type"] == "spi"
        assert result.get("spi_command") == "Write Enable"

    def test_can_decode(self):
        dec = CANDecoder()
        # CAN frame: id_hi=0x00, id_lo=0x01 → CAN ID = 0x001, DLC=4
        result = dec.decode(bytes([0x00, 0x01, 0x04, 0x01, 0x02, 0x03, 0x04, 0x00, 0x00]))
        assert result["type"] == "can"
        assert "can_id" in result
        assert result["dlc"] == 4

    def test_can_dbc_load(self):
        dec = DBCDecoder()
        dbc = "BO_ 100 EngineData: 8 Vector__XXX\n SG_ RPM : 0|16@1+ (1,0) [0|8000] \"rpm\" Vector__XXX\n"
        result = dec.load_dbc_text(dbc)
        assert 'error' not in result
        assert result['messages'] == 1
        assert result['total_signals'] == 1

    def test_can_dbc_decode(self):
        dec = DBCDecoder()
        dbc = "BO_ 256 EngineData: 8 Vector__XXX\n SG_ RPM : 0|16@1+ (1,0) [0|8000] \"rpm\" Vector__XXX\n"
        dec.load_dbc_text(dbc)
        # CAN ID 256 = 0x0100 → big-endian 4 bytes = 0x00 0x00 0x01 0x00
        # Data: RPM=1000 = 0x03E8 big-endian in bytes 0-1
        raw = bytes([0x00, 0x00, 0x01, 0x00]) + bytes([0x03, 0xE8, 0x00, 0x00, 0x00, 0x00])
        result = dec.decode(raw)
        assert result.get("message") == "EngineData"


# ─── MQTT Manager ────────────────────────────────────────────────────────────

class TestMQTTManager:
    def setup_method(self):
        self.mgr = MQTTManager()

    def test_add_profile(self):
        profile = MQTTConnectionProfile(name="Test", broker="localhost")
        self.mgr.add_profile(profile)
        assert len(self.mgr.get_all_profiles()) == 1

    @pytest.mark.asyncio
    async def test_remove_profile(self):
        profile = MQTTConnectionProfile(name="Test", broker="localhost")
        self.mgr.add_profile(profile)
        self.mgr.remove_profile(profile.id)
        assert len(self.mgr.get_all_profiles()) == 0

    def test_get_stats_empty(self):
        stats = self.mgr.get_stats()
        assert stats['total_connections'] == 0

    @pytest.mark.asyncio
    async def test_shutdown_no_connections(self):
        await self.mgr.shutdown()
        # Should not raise
        assert True
