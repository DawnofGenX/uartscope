"""`can` encode must accept a numeric can_id.

Regression: the guard read

    can_id = data.get('can_id', 0)
    if isinstance(can_id, str):
        can_id = int(can_id, 16)

which protected the string path and left the integer path to reach the
unguarded `int(can_id, 16)`, raising
`TypeError: int() can't convert non-string with explicit base` and returning
HTTP 500 from POST /api/protocols/encode. An integer id is the more natural
JSON input, so the crash was on the common path.

Run:  .venv/bin/python -m pytest tests/test_can_encode.py -v
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.protocol_decoder import protocol_manager  # noqa: E402


@pytest.fixture
def can_decoder():
    decoder = protocol_manager.get_decoder("can")
    assert decoder is not None, "the built-in `can` decoder is missing"
    return decoder


class TestCanIdAcceptsBothForms:
    def test_hex_string_id(self, can_decoder):
        out = can_decoder.encode({"can_id": "0x100",
                                 "signals": [{"start": 0, "value": 1}]})
        assert out.hex() == "010000"

    def test_integer_id(self, can_decoder):
        # 0x100 == 256. This is the form that crashed.
        out = can_decoder.encode({"can_id": 256,
                                 "signals": [{"start": 0, "value": 1}]})
        assert out == can_decoder.encode({"can_id": "0x100",
                                          "signals": [{"start": 0, "value": 1}]})

    def test_integer_id_above_the_hex_range(self, can_decoder):
        out = can_decoder.encode({"can_id": 0x7FF,
                                 "signals": [{"start": 0, "value": 1}]})
        assert isinstance(out, bytes)

    def test_id_absent_defaults_without_raising(self, can_decoder):
        out = can_decoder.encode({"signals": [{"start": 0, "value": 1}]})
        assert isinstance(out, bytes)

    def test_api_returns_200_for_an_integer_id(self):
        """The endpoint passes data straight through, so it must not 500."""
        import asyncio

        from httpx import ASGITransport, AsyncClient

        from app.main import app

        async def go():
            async with AsyncClient(transport=ASGITransport(app=app),
                                   base_url="http://test") as c:
                return await c.post("/api/protocols/encode", json={
                    "protocol_id": "can",
                    "data": {"can_id": 256,
                             "signals": [{"start": 0, "value": 1}]},
                })

        r = asyncio.run(go())
        assert r.status_code == 200, r.text
