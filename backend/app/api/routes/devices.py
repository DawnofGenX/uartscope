"""Device management API routes."""
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from typing import List, Optional

from app.database import get_db
from app.core.device_manager import device_manager
from app.models import DeviceCreate, DeviceResponse, DeviceStatus

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("/detect")
async def detect_devices():
    """Auto-detect connected serial devices."""
    ports = await device_manager.detect_ports()
    return {"devices": ports, "count": len(ports)}


@router.post("/", response_model=DeviceResponse)
async def create_device(device: DeviceCreate, db: AsyncSession = Depends(get_db)):
    """Register a new device."""
    existing = [d for d in device_manager.get_all_devices() if d.port == device.port]
    if existing:
        raise HTTPException(status_code=409, detail=f"Device on {device.port} already registered")

    dev = await device_manager.add_device(device)
    # Save to database
    from app.database import DeviceModel
    db_device = DeviceModel(
        name=dev.name,
        port=dev.port,
        protocol=dev.protocol,
        baudrate=dev.baudrate,
        board_type=dev.board_type,
        metadata_json=device.metadata,
    )
    db.add(db_device)
    await db.commit()
    await db.refresh(db_device)
    dev.id = str(db_device.id)
    return dev.to_response()


@router.get("/", response_model=List[DeviceResponse])
async def list_devices():
    """List all registered devices."""
    devices = device_manager.get_all_devices()
    return [d.to_response() for d in devices]


@router.get("/{device_id}", response_model=DeviceResponse)
async def get_device(device_id: str):
    """Get a specific device."""
    device = device_manager.get_device(device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device.to_response()


@router.post("/{device_id}/connect")
async def connect_device(device_id: str):
    """Connect to a device."""
    success = await device_manager.connect(device_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to connect")
    return {"status": "connected", "device_id": device_id}


@router.post("/{device_id}/disconnect")
async def disconnect_device(device_id: str):
    """Disconnect from a device."""
    success = await device_manager.disconnect(device_id)
    return {"status": "disconnected", "device_id": device_id}


@router.delete("/{device_id}")
async def delete_device(device_id: str, db: AsyncSession = Depends(get_db)):
    """Remove a device."""
    from app.database import DeviceModel
    await device_manager.remove_device(device_id)
    await db.execute(
        __import__("sqlalchemy").delete(DeviceModel).where(DeviceModel.id == device_id)
    )
    await db.commit()
    return {"status": "deleted", "device_id": device_id}


@router.post("/{device_id}/send")
async def send_to_device(device_id: str, data: str):
    """Send data to a device."""
    success = await device_manager.write(device_id, data.encode() + b"\n")
    if not success:
        raise HTTPException(status_code=400, detail="Failed to send")
    return {"status": "sent"}
