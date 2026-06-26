"""Protocol decoder API routes."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.core.protocol_decoder import protocol_manager

router = APIRouter(prefix="/protocols", tags=["protocols"])


@router.get("/")
async def list_protocols():
    """List all available protocol decoders."""
    return {"decoders": protocol_manager.list_decoders()}


@router.post("/decode")
async def decode_data(body: dict):
    """Decode raw data using specified or auto-detected protocol."""
    raw_hex = body.get("raw_hex", "")
    protocol_id = body.get("protocol_id", "auto")

    try:
        raw_data = bytes.fromhex(raw_hex)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid hex data")

    if protocol_id == "auto":
        decoder = protocol_manager.auto_detect(raw_data)
        if not decoder:
            return {
                "success": False,
                "message": "No protocol detected with sufficient confidence",
                "raw_hex": raw_hex,
            }
        protocol_id = decoder.protocol_id

    result = protocol_manager.decode(protocol_id, raw_data)
    decoder = protocol_manager.get_decoder(protocol_id)

    return {
        "success": True,
        "protocol_id": protocol_id,
        "protocol_name": decoder.name if decoder else "Unknown",
        "decoded": result,
    }


@router.post("/encode")
async def encode_data(body: dict):
    """Encode structured data to raw bytes using specified protocol."""
    protocol_id = body.get("protocol_id", "")
    data = body.get("data", {})

    decoder = protocol_manager.get_decoder(protocol_id)
    if not decoder:
        raise HTTPException(status_code=404, detail="Protocol not found")

    raw_bytes = decoder.encode(data)
    return {
        "protocol_id": protocol_id,
        "raw_hex": raw_bytes.hex(),
        "length": len(raw_bytes),
    }


@router.post("/dbc/load")
async def load_dbc_file(body: dict):
    """Load DBC/LDF file content and parse message definitions."""
    content = body.get("content", "")
    filename = body.get("filename", "unnamed.dbc")

    if not content:
        raise HTTPException(status_code=400, detail="File content required")

    decoder = protocol_manager.get_decoder("can_dbc")
    if not decoder:
        raise HTTPException(status_code=500, detail="DBC decoder not available")

    if filename.endswith(".ldf"):
        result = {"message": "LDF format not yet implemented", "signals": [], "messages": []}
    else:
        result = decoder.load_dbc_text(content)

    return {"success": True, "filename": filename, "result": result}


@router.get("/dbc/loaded")
async def get_loaded_dbc_info():
    """Get information about currently loaded DBC data."""
    decoder = protocol_manager.get_decoder("can_dbc")
    if not decoder:
        raise HTTPException(status_code=500, detail="DBC decoder not available")

    if not decoder._messages:
        return {"loaded": False, "messages": 0, "signals": 0}

    total_signals = sum(len(m['signals']) for m in decoder._messages.values())
    return {
        "loaded": True,
        "messages": len(decoder._messages),
        "total_signals": total_signals,
        "message_ids": [f"0x{mid:03X}" for mid in decoder._messages.keys()],
        "message_names": {f"0x{mid:03X}": m['name'] for mid, m in decoder._messages.items()},
    }
