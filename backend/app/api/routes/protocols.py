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
