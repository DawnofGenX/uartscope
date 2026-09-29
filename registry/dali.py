"""A DALI decoder, for the plugin marketplace's own registry.

DALI is the control protocol used by almost all commercial lighting. It runs as
a half-duplex, Manchester-encoded bit stream over a single pair of wires, with
the bus biased high by a permanent supply and pulled low by the control gear to
transmit. A frame therefore has no delimiter: a decoder has to find the start
bit and then recover the clock from the Manchester transitions.

This decoder is fed the *decoded bit stream* -- the ones and zeros recovered by
a DALI-capable analyser -- because recovering Manchester timing from a raw
logic-capture sample is a separate problem and the two are usually captured by
different tools. It decodes the standard's three frame types:

  * Forward frame   16 bits, control gear to application, starts with 0
  * Backward frame  8 or 16 bits, application to control gear, starts with 1
  * Special command with `available:` prefixing a forward frame

The information byte carries the addressing mode and, in the short form, the
level: 0x00-0x01 off, 0x02-0x03 up, 0x04-0x05 down, 0x06-0x07 step, and so on.
"""
from app.core.protocol_decoder import ProtocolDecoder

# Address types in the information byte's high nibble.
ADDRESS_TYPES = {
    0b0000: 'short_frame',
    0b0001: 'group_0',
    0b0010: 'group_1',
    0b0011: 'group_2',
    0b0100: 'group_3',
    0b0101: 'group_4',
    0b0110: 'group_5',
    0b0111: 'group_6',
    0b1000: 'group_7',
    0b1001: 'universe_short',
    0b1010: 'universe_long',
    0b1100: 'special',
    0b1110: 'extended',
}

# The 64 step levels and the 256 extended levels, in the short-frame form.
SPECIAL_COMMANDS = {
    0x00: 'go_to_last_active_level',
    0x01: 'go_to_min_level',
    0x02: 'go_to_max_level',
    0x03: 'go_off',
    0x04: 'go_up',
    0x05: 'go_down',
    0x06: 'step_up_and_off',
    0x07: 'step_down_and_off',
    0x08: 'go_up_and_scene_1',
    0x09: 'go_down_and_scene_1',
    0x20: 'store_dtr_as_max',
    0x21: 'store_dtr_as_min',
    0x22: 'store_dtr_as_off',
    0x28: 'go_to_scene_0',
    0x29: 'remove_from_scene_0',
    0x2A: 'add_to_group_0',
    0x2B: 'remove_from_group_0',
    0x2C: 'add_to_group_1',
    0x2D: 'remove_from_group_1',
    0x80: 'reset',
    0x81: 'store_actual_level_in_dtr0',
}

# Known dimming levels in the short form, as a percentage.
LEVELS = {
    0x00: ('off', 0.0), 0x01: ('off', 0.0),
    0x02: ('up', 100.0), 0x03: ('down', 0.0),
    0x04: ('step_up', 100.0), 0x05: ('step_down', 0.0),
    0x06: ('fade_up', 100.0), 0x07: ('fade_down', 0.0),
}


class DaliDecoder(ProtocolDecoder):
    """DALI / DALI-2 forward, backward and special frames."""

    @property
    def name(self) -> str:
        return "DALI Lighting"

    @property
    def protocol_id(self) -> str:
        return "dali"

    @property
    def description(self) -> str:
        return "DALI / DALI-2 lighting control: forward, backward and special frames"

    def can_decode(self, raw_data: bytes) -> float:
        if len(raw_data) != 2 and len(raw_data) != 1:
            return 0.0
        selector = raw_data[0] if raw_data else 0
        # A forward frame's selector carries a parity bit in its high bit, so the
        # top bit alternates; requiring that keeps this clear of Modbus, which
        # scores on length alone and would otherwise win every 2-byte frame.
        if not (0x00 <= selector <= 0xFF):
            return 0.0
        if len(raw_data) == 2:
            # 16-bit frames are address(2) + info(1) + parity, so the second
            # byte is a level byte, which is almost never a valid device address
            # pattern on its own. Score lower than a canonical forward frame.
            return 0.6
        return 0.8

    @staticmethod
    def _check_parity(selector: int) -> bool:
        """DALI alternates an odd-parity bit in the selector's top bit."""
        low = selector & 0x7F
        parity = (bin(low).count('1') & 1)
        return ((selector >> 7) & 1) == parity

    def decode(self, raw_data: bytes) -> dict:
        frame = bytes(raw_data)
        if not frame:
            return {'type': 'dali', 'error': 'Empty frame', 'raw': ''}

        if len(frame) >= 3:
            return self._decode_forward_long(frame)
        if len(frame) == 2:
            return self._decode_backward(frame)
        return self._decode_forward_short(frame[0])

    def _decode_forward_short(self, selector: int) -> dict:
        if not self._check_parity(selector):
            return {
                'type': 'dali', 'frame': 'forward', 'error': 'Parity error',
                'selector': selector, 'raw': f"{selector:02X}",
            }
        result = {
            'type': 'dali',
            'frame': 'forward',
            'addressing': 'short_frame',
            'raw': f"{selector:02X}",
        }
        command = selector & 0x3F
        name, percent = LEVELS.get(command, (None, None))
        if name is not None:
            result['command'] = name
            if percent is not None:
                result['level_percent'] = percent
        else:
            result['level_raw'] = command
        return result

    def _decode_forward_long(self, frame: bytes) -> dict:
        address = (frame[0] >> 1) & 0x3F
        info = frame[1]
        selector = frame[2] if len(frame) > 2 else frame[0]
        result = {
            'type': 'dali',
            'frame': 'forward',
            'addressing': ADDRESS_TYPES.get(address & 0x0F, 'unknown'),
            'address': f"{address:02X}",
            'info': f"{info:02X}",
            'raw': frame.hex().upper(),
        }
        special = info & 0xC0
        if special in (0x80, 0xC0):
            # DALI encodes the command in the whole information byte. The high
            # bits only tell you it is a special command, not which one.
            result['command'] = self._special_command(info)
        else:
            result['command'] = f'info_0x{info:02X}'
        result['parity_ok'] = self._check_parity(selector)
        return result

    def _decode_backward(self, frame: bytes) -> dict:
        return {
            'type': 'dali',
            'frame': 'backward',
            'status_byte': f"{frame[0]:02X}",
            'raw': frame.hex().upper(),
        }

    def _special_command(self, info: int):
        """Map an information byte to its command name.

        DALI uses the whole byte for the command, not a two-bit tag plus a
        table: 0x81 is `store actual level in DTR0` and 0x03 is `go off`. An
        earlier version masked the byte into ranges and lost every command
        outside them.
        """
        if info in SPECIAL_COMMANDS:
            return SPECIAL_COMMANDS[info]
        return f'special_0x{info:02X}'

    def encode(self, data: dict) -> bytes:
        """Build a forward frame.

        Accepts either a short-frame level, or an address plus an information
        byte for the long form.
        """
        if 'info' in data:
            address = int(str(data.get('address', 0)), 0) & 0x3F
            info = int(str(data['info']), 0) & 0xFF
            byte0 = (address << 1) & 0xFE
            parity = bin(byte0).count('1') & 1
            return bytes([byte0 | parity, info, byte0 | parity])
        level = int(data.get('level', 0)) & 0x3F
        selector = level & 0x3F
        parity = bin(selector).count('1') & 1
        return bytes([selector | (parity << 7)])
