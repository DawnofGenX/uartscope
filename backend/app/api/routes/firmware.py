"""Firmware flashing API routes."""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core.board_detector import SUPPORTED_BOARDS, detect_board

router = APIRouter(prefix="/api/firmware", tags=["firmware"])


class CompileRequest(BaseModel):
    sketch_dir: str
    fqbn: str


class FlashRequest(BaseModel):
    bin_path: str
    port: str
    baud: int = 921600


@router.get("/boards")
def list_boards():
    """Return supported boards and auto-detected connected boards."""
    return {
        "supported": SUPPORTED_BOARDS,
        "detected": detect_board(),
    }


@router.get("/examples")
def list_examples():
    """Return available example sketches."""
    examples_dir = Path(__file__).resolve().parents[4] / "hardware" / "examples"
    examples = []
    if examples_dir.exists():
        for protocol_dir in sorted(examples_dir.iterdir()):
            if protocol_dir.is_dir():
                for ino in protocol_dir.glob("*.ino"):
                    examples.append({
                        "protocol": protocol_dir.name,
                        "name": ino.stem,
                        "path": str(ino),
                    })
    return examples


@router.post("/compile")
def compile_firmware(req: CompileRequest):
    """Compile a sketch to .bin."""
    from app.core.firmware_compiler import compile_sketch, find_compiled_bin

    sketch_dir = Path(req.sketch_dir)
    if not sketch_dir.exists():
        raise HTTPException(404, "Sketch directory not found")

    result = compile_sketch(sketch_dir, req.fqbn)
    if result.returncode != 0:
        raise HTTPException(500, f"Compilation failed: {result.stderr}")

    bin_file = find_compiled_bin(sketch_dir)
    if not bin_file:
        raise HTTPException(500, "Compilation succeeded but no .bin found")

    return {"bin_path": str(bin_file), "status": "ok"}


@router.post("/flash")
def flash_firmware(req: FlashRequest):
    """Flash a .bin file to a device."""
    from app.core.firmware_flasher import flash_firmware

    bin_path = Path(req.bin_path)
    if not bin_path.exists():
        raise HTTPException(404, "Binary file not found")

    result = flash_firmware(bin_path, req.port, req.baud)
    if result.returncode != 0:
        raise HTTPException(500, f"Flash failed: {result.stderr}")

    return {"status": "ok", "output": result.stdout}
