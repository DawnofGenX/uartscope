"""A J1939 decoder, for the plugin marketplace's own registry.

J1939 is the SAE standard carried on CAN for heavy-duty vehicles. A J1939
message is a CAN frame whose 29-bit identifier is laid out as:

    28..26  priority      (3 bits)
    25..16  extended PF   (8 bits)
    15..8   PS            (8 bits, a destination address, 0xFF = broadcast)
    7..0    source address

The PGN -- the parameter group number -- is the meaningful part, and is
normally PF * 256, except for PDU1 formats (PF < 240) where the PS byte is a
destination and the PGN is PF * 256 + 0x00 (PDU1 Format) or PG = PS (PDU2
Format).

The transport protocol (TP.CM / TP.DT) is decoded far enough to reassemble a
multi-packet broadcast, which is how most engine and brake data actually
arrives. The engine ECU (address 0) and the brake ECU (address 1) are the two
that matter in practice.
"""
from typing import Dict

from app.core.protocol_decoder import ProtocolDecoder

# Priority 6 is the default for a node that has not set one.
DEFAULT_PRIORITY = 6


def _pgn(can_id: int) -> dict:
    """Split a 29-bit J1939 identifier into its fields."""
    priority = (can_id >> 26) & 0x07
    pf = (can_id >> 16) & 0xFF
    ps = (can_id >> 8) & 0xFF
    source = can_id & 0xFF
    pdu_format = 'PDU1' if pf < 240 else 'PDU2'
    if pdu_format == 'PDU1':
        pgn = (pf << 8) & 0x3FFFF          # group extension is zero for PDU1
        destination = ps if ps != 0xFF else None
    else:
        pgn = (pf << 8) | ps
        destination = None                  # PS is the group number
    return {
        'priority': priority,
        'pdu_format': pdu_format,
        'pf': pf,
        'pgn': pgn,
        'destination': destination,
        'source': source,
    }


# A useful subset of PGNs. Offsets are little-endian, as J1939 specifies.
PGNS = {
    0x00F004: {'name': 'Engine_1', 'length': 8, 'signals': [
        ('Engine_Speed', 0, 2, 0.125, 0.0),          # rpm
        ('Engine_Instantaneous_Fuel', 2, 1, 0.4, 0.0),  # % (0.4 L/h per bit)
        ('Engine_Actual_Percent_Torque', 3, 1, 1.0, -125.0),
    ]},
    0x00F00D: {'name': 'Engine_2', 'length': 8, 'signals': [
        ('Engine_Requested_Torque', 0, 1, 1.0, -125.0),
        ('Engine_Starter_Mode', 1, 4, 1.0, 0.0),
        ('Engine_Actual_Percent_Torque', 2, 1, 1.0, -125.0),
    ]},
    0x00F014: {'name': 'Brakes', 'length': 8, 'signals': [
        ('Brake_Switch', 0, 2, 1.0, 0.0),
        ('Brake_Pedal_Position', 1, 1, 0.4, 0.0),
    ]},
    0x00FE46: {'name': 'Vehicle_Position', 'length': 8, 'signals': [
        ('Latitude', 0, 4, 1e-7, -90.0),
        ('Longitude', 4, 4, 1e-7, -180.0),
    ]},
    0x00FE49: {'name': 'Vehicle_Dynamics', 'length': 8, 'signals': [
        ('Roll_Angle', 0, 2, 0.05, -1.57),
        ('Pitch_Angle', 1, 2, 0.05, -1.57),
        ('Yaw_Rate', 2, 2, 0.01, -3.14),
    ]},
    0x00FEE7: {'name': 'Vehicle_Power', 'length': 8, 'signals': [
        ('Fuel_Level', 0, 1, 0.5, 0.0),               # %
        ('Fuel_Rate', 2, 2, 0.05, -250.0),            # L/h, can be negative
    ]},
}

# Transport protocol management frames.
TP_CM_RTS = 0x10
TP_CM_CTS = 0x11
TP_CM_END = 0x13
TP_DT = 0xEB


def _le_value(data: bytes, start: int, length: int) -> int:
    total = 0
    for i in range(length):
        if start + i < len(data):
            total |= data[start + i] << (8 * i)
    return total


class J1939Decoder(ProtocolDecoder):
    """CAN frames carrying SAE J1939, plus the transport protocol reassembly."""

    @property
    def name(self) -> str:
        return "J1939 (Heavy Duty)"

    @property
    def protocol_id(self) -> str:
        return "j1939"

    @property
    def description(self) -> str:
        return "SAE J1939 for trucks, buses and agricultural vehicles"

    # Reassembly state. A multi-packet broadcast arrives as 255-byte transfers
    # at consecutive PGNs (0x00EC00, 0x00ED00, ...), so the buffer keys on the
    # originating PGN. Bounded so a capture of a chatty network cannot grow it
    # without limit.
    MAX_SESSIONS = 8
    MAX_MESSAGE_BYTES = 1785

    def __init__(self):
        self._sessions: Dict[int, bytearray] = {}

    ID_BYTES = 4
    DATA_BYTES = 8

    def can_decode(self, raw_data: bytes) -> float:
        # A J1939 message is a 4-byte CAN id followed by the full 8 data bytes.
        if len(raw_data) != self.ID_BYTES + self.DATA_BYTES:
            return 0.0
        can_id = int.from_bytes(raw_data[:self.ID_BYTES], 'big')
        if not (can_id & 0x80000000):
            return 0.0                    # J1939 needs the 29-bit (extended) form
        fields = _pgn(can_id)
        if fields['pgn'] in PGNS:
            return 0.95
        if fields['pf'] in (0xEC, 0xEB):  # transport protocol
            return 0.8
        # Any extended-frame CAN id is a plausible J1939 id, but say so with a
        # low score so a purpose-built CAN decoder still wins.
        return 0.5

    def decode(self, raw_data: bytes) -> dict:
        frame = bytes(raw_data)
        if len(frame) != self.ID_BYTES + self.DATA_BYTES:
            return {'type': 'j1939',
                    'error': f'Expected {self.ID_BYTES + self.DATA_BYTES} bytes '
                             f'(CAN id + data), got {len(frame)}',
                    'raw': frame.hex()}

        can_id = int.from_bytes(frame[:self.ID_BYTES], 'big')
        if not (can_id & 0x80000000):
            return {'type': 'j1939', 'error': 'Not an extended CAN identifier',
                    'raw': frame.hex()}

        fields = _pgn(can_id)
        result = {
            'type': 'j1939',
            'can_id': f"0x{can_id:08X}",
            'priority': fields['priority'],
            'pdu_format': fields['pdu_format'],
            'pgn': f"0x{fields['pgn']:05X}",
            'source': fields['source'],
            'raw': frame.hex(),
        }
        if fields['destination'] is not None:
            result['destination'] = fields['destination']
        if fields['pgn'] in PGNS:
            result['pgn_name'] = PGNS[fields['pgn']]['name']

        data = frame[self.ID_BYTES:self.ID_BYTES + self.DATA_BYTES]
        if fields['pf'] == 0xEC:
            result.update(self._transport_control(fields, data))
            return result
        if fields['pf'] == 0xEB:
            result.update(self._transport_data(fields, data))
            return result

        signals = PGNS.get(fields['pgn'], {}).get('signals', [])
        if signals:
            result['signals'] = {
                name: round(_le_value(data, start, length) * scale + offset, 3)
                for name, start, length, scale, offset in signals
            }
        return result

    # ── Transport protocol ─────────────────────────────────────────────────
    def _trim_sessions(self) -> None:
        while len(self._sessions) > self.MAX_SESSIONS:
            self._sessions.pop(next(iter(self._sessions)))

    def _transport_control(self, fields: dict, data: bytes) -> dict:
        control = data[0] & 0xFF
        out = {'tp': 'CM'}
        if control == TP_CM_RTS:
            size = int.from_bytes(data[1:3], 'little')
            # The transferred message's PGN is 3 bytes on the wire (data[3:6]).
            # Reading a 4th byte would fold the frame's padding into the value
            # and produce a PGN no ECU ever sent.
            total = int.from_bytes(data[3:6], 'little')
            out['request'] = 'RTS'
            out['message_size'] = size
            out['total_bytes'] = total
            key = (total & 0x3FFFF)
            self._sessions[key] = bytearray()
            self._trim_sessions()
        elif control == TP_CM_CTS:
            out['request'] = 'CTS'
            out['can_send'] = data[1] & 0xFF
        elif control == TP_CM_END:
            out['request'] = 'EndOfMsgAck'
            # The reassembled payload is what the caller actually wanted.
            key = (fields['pgn'] & 0x3FF00)
            for candidate, buffer in list(self._sessions.items()):
                if candidate & 0x3FF00 == key or len(self._sessions) == 1:
                    out['message'] = bytes(buffer).hex()
                    out['message_bytes'] = len(buffer)
                    self._sessions.pop(candidate, None)
                    break
        else:
            out['request'] = f"unknown({control})"
        return out

    def _transport_data(self, fields: dict, data: bytes) -> dict:
        sequence = data[0] & 0xFF
        # Packets are keyed by the originating PGN's first sequence slot.
        key = (fields['pgn'] >> 8) << 8
        buffer = self._sessions.setdefault(key, bytearray())
        if len(buffer) < self.MAX_MESSAGE_BYTES:
            buffer.extend(data[1:8])
        self._trim_sessions()
        return {
            'tp': 'DT',
            'sequence': sequence,
            'received_so_far': len(buffer),
        }

    def encode(self, data: dict) -> bytes:
        """Build a J1939 frame from a PGN and its signals.

        Bit 31 must be set: a J1939 message is always an extended CAN frame, and
        an id without it would decode back as "not J1939".
        """
        pgn = int(str(data.get('pgn', '0')), 0) & 0x3FFFF
        source = int(data.get('source', 0)) & 0xFF
        priority = int(data.get('priority', DEFAULT_PRIORITY)) & 0x07
        destination = int(data.get('destination', 0xFF)) & 0xFF

        pf = (pgn >> 8) & 0xFF
        ps = destination if pf < 240 else (pgn & 0xFF)
        can_id = (0x80000000 | (priority << 26) | (pf << 16) | (ps << 8) | source)
        can_id &= 0xFFFFFFFF
        payload = bytearray(8)
        signals = PGNS.get(pgn, {}).get('signals', [])
        raw_signals = data.get('signals') or {}
        for name, start, length, scale, offset in signals:
            if name not in raw_signals:
                continue
            value = int((float(raw_signals[name]) - offset) / (scale or 1.0))
            value &= (1 << (length * 8)) - 1
            for i in range(length):
                if start + i < 8:
                    payload[start + i] = (value >> (8 * i)) & 0xFF
        return can_id.to_bytes(4, 'big') + bytes(payload)
