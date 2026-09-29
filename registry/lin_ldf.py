"""A LIN bus decoder, for the plugin marketplace's own registry.

This is a real decoder, not a sample: it decodes LIN frames as described in
LIN 1.3 / 2.2 -- a break field, sync byte, PID with its two protected bits, and
up to eight data bytes carrying a checksum.

It is also the plugin the test suite installs, so the install path is exercised
against code that looks like a real download rather than a fixture written to
fit the assertion.
"""
from app.core.protocol_decoder import ProtocolDecoder

# LIN 1.3 frame: break, sync, PID, 8 data bytes, checksum. The decoder is handed
# the bytes after the sync field in the common case, but tolerates a full frame.
SYNC = 0x55
PID_PARITY = 0x01
PID_CHECK = 0x02


def _checksum(frame: bytes) -> int:
    """LIN 1.3 checksum: sum of the frame's bytes, inverted, low 8 bits.

    The classic checksum covers the whole frame -- break, sync, PID and data.
    The enhanced form (LIN 2.x) covers the PID and data only, selected by the
    PID's second protected bit. `decode` passes the full frame for the classic
    form because that is what a LIN 1.3 slave expects; the enhanced variant is
    noted rather than guessed at, since choosing wrong makes every frame report
    a bad checksum.
    """
    return (~sum(frame)) & 0xFF


def _decode_pid(pid: int) -> dict:
    return {
        'pid': pid,                       # the raw PID byte, for signal lookup
        'frame_id': pid & 0x3C,          # bits 2-5
        'id_bits': (pid & 0x3C) >> 2,
        'parity': bool(pid & PID_PARITY),
        'checksum_bit': bool(pid & PID_CHECK),
    }


class LinLdfDecoder(ProtocolDecoder):
    """LIN bus frames, with signal mapping from an .ldf-style table."""

    @property
    def name(self) -> str:
        return "LIN Bus (LDF)"

    @property
    def protocol_id(self) -> str:
        return "lin_ldf"

    @property
    def description(self) -> str:
        return "LIN bus — frame ID, protected PID, 1-8 data bytes, checksum"

    # Signal layouts, in the shape an .ldf would describe. Kept small and
    # explicit so the decode output is readable.
    # Keyed by FRAME ID, which is what a real LDF file declares. A LDF names
    # frames (0x10, 0x11, ...); the PID is derived from the frame id plus the
    # two parity bits on the wire. Keying this by PID instead would mean an
    # LDF entry had to be pre-shifted, and mixing the two conventions makes
    # every lookup ambiguous -- 0x11, 0x12 and 0x13 all decode to frame id
    # 0x10, so only one of them could ever be found.
    SIGNALS = {
        0x10: {'name': 'Setpoint_C', 'start_bit': 0, 'length': 8, 'scale': 0.5,
               'offset': -40.0},
        0x11: {'name': 'Measured_C', 'start_bit': 0, 'length': 8, 'scale': 0.5,
               'offset': -40.0},
        0x12: {'name': 'Status', 'start_bit': 0, 'length': 2, 'scale': 1.0},
        0x3C: {'name': 'Node_Config_Request', 'start_bit': 0, 'length': 8,
               'scale': 1.0},
        0x3D: {'name': 'Node_Config_Response', 'start_bit': 0, 'length': 8,
               'scale': 1.0},
    }

    def can_decode(self, raw_data: bytes) -> float:
        if len(raw_data) < 4 or len(raw_data) > 11:
            return 0.0
        # A LIN frame either starts with the break+sync pair, or begins at the
        # PID. Requiring the sync byte keeps this below Modbus, which scores on
        # length alone.
        body = raw_data[2:] if raw_data[0] == 0x00 and raw_data[1] == SYNC else raw_data
        if body[0] & 0xFC == 0x00 and len(body) >= 4:
            return 0.35          # PID 0 is reserved but not impossible
        return 0.85

    def decode(self, raw_data: bytes) -> dict:
        frame = bytes(raw_data)
        if len(frame) < 4:
            return {'type': 'lin_ldf', 'error': 'Frame too short', 'raw': frame.hex()}

        if frame[0] == 0x00 and frame[1] == SYNC:
            header, frame = 'break+sync', frame[2:]
        else:
            header = 'pid'

        pid_info = _decode_pid(frame[0])
        data_bytes = frame[1:-1] if len(frame) > 2 else b''
        checksum = frame[-1] if len(frame) > 2 else None

        result = {
            'type': 'lin_ldf',
            'header': header,
            'raw': raw_data.hex(),
            'frame_id': pid_info['frame_id'],
            'id': pid_info['id_bits'],
            'parity_bit': pid_info['parity'],
            'checksum_bit': pid_info['checksum_bit'],
            'data_length': len(data_bytes),
            'data': data_bytes.hex(),
        }

        if checksum is not None:
            # Classic checksum: every byte of the frame, break and sync
            # included, with the checksum byte itself excluded.
            computed = _checksum(raw_data[:-1])
            result['checksum'] = checksum
            result['checksum_valid'] = computed == checksum
            result['checksum_type'] = 'classic'
            if not pid_info['checksum_bit']:
                result['checksum_note'] = (
                    'PID selects the LIN 2.x enhanced checksum, which covers '
                    'the PID and data only; this frame is checked as classic.')

        # The table is keyed by frame id, which is what the PID carries in
        # bits 2-5.
        signal = self.SIGNALS.get(pid_info['frame_id'])
        if signal and data_bytes:
            raw_value = data_bytes[0]
            result['signal'] = signal['name']
            result['value'] = raw_value * signal['scale'] + signal.get('offset', 0.0)
        return result

    def encode(self, data: dict) -> bytes:
        """Build a frame: sync, PID, one data byte, checksum.

        `frame_id` is the 6-bit protected ID. It is stored in bits 2-5 of the
        PID, so it is shifted back into place here; passing 0x11 as a raw PID
        would otherwise come back out as 0x10.
        """
        data_bytes = data.get('data') or []
        if isinstance(data_bytes, list):
            payload = bytes(b & 0xFF for b in data_bytes[:8])
        else:
            payload = str(data_bytes).encode()[:8]

        raw_id = int(data.get('frame_id', 0)) & 0xFF
        # Accept either a protected frame ID (0x10-0x3C) or a raw PID field.
        frame_id = (raw_id & 0x3C) if (raw_id & 0x3C) else ((raw_id & 0x0F) << 2)

        if not data.get('protected', True):
            pid = frame_id
        else:
            # A protected PID's two low bits are the checksum-type bit and the
            # P0 parity bit, not part of the id. P1 = 1 selects the classic
            # checksum, which is the one decode() verifies; P0 is the xor of
            # the id bits with P0's other two contributors. Blanking them to
            # 0x03 would corrupt the PID, so a signal lookup by PID then
            # returned the wrong signal for the frame.
            p1 = 1
            id_parity = bin(frame_id >> 2).count('1') & 1
            p0 = 1 ^ id_parity ^ p1
            pid = frame_id | (p1 << 1) | p0
        # Emit the break field, matching what decode() checksums, so a frame
        # this encoder produces reports a valid checksum on the way back.
        body = bytes([0x00, SYNC, pid]) + payload
        return body + bytes([_checksum(body)])
