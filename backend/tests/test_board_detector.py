"""Tests for USB board detection (VID/PID → FQBN mapping).

Run:  cd backend && python -m pytest tests/test_board_detector.py -v
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))

from app.core.board_detector import detect_board, board_from_vid_pid  # noqa: E402


def test_known_esp32_vid_pid():
    """CP210x VID/PID returns correct board info."""
    result = board_from_vid_pid(0x10C4, 0xEA60)
    assert result is not None
    assert result["fqbn"].startswith("esp32:esp32:")


def test_unknown_vid_pid():
    """Unknown VID/PID returns None."""
    result = board_from_vid_pid(0x1234, 0x5678)
    assert result is None


def test_detect_board_returns_list():
    """detect_board() returns a list (may be empty if no hardware)."""
    boards = detect_board()
    assert isinstance(boards, list)
