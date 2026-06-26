"""MQTT Management API routes."""
from fastapi import APIRouter, HTTPException
from typing import Optional, Dict, Any

from app.core.mqtt_client import (
    mqtt_manager,
    MQTTConnectionProfile,
    MQTTMessage,
)

router = APIRouter(prefix="/mqtt", tags=["mqtt"])


@router.get("/profiles")
async def list_profiles():
    """List all MQTT connection profiles."""
    profiles = mqtt_manager.get_all_profiles()
    return {
        "profiles": [
            {
                "id": p.id,
                "name": p.name,
                "broker": p.broker,
                "port": p.port,
                "topic_prefix": p.topic_prefix,
                "connected": p.connected,
                "subscribed_topics": p.subscribed_topics,
                "messages_received": p.messages_received,
                "bytes_received": p.bytes_received,
                "connected_at": p.connected_at.isoformat() if p.connected_at else None,
                "last_error": p.last_error,
            }
            for p in profiles
        ]
    }


@router.post("/profiles")
async def create_profile(body: Dict[str, Any]):
    """Create a new MQTT connection profile."""
    profile = MQTTConnectionProfile(
        name=body.get("name", "New Connection"),
        broker=body.get("broker", "localhost"),
        port=body.get("port", 1883),
        username=body.get("username"),
        password=body.get("password"),
        topic_prefix=body.get("topic_prefix", "uartscope"),
        qos=body.get("qos", 0),
        use_tls=body.get("use_tls", False),
    )
    mqtt_manager.add_profile(profile)
    return {"id": profile.id, "name": profile.name}


@router.delete("/profiles/{profile_id}")
async def delete_profile(profile_id: str):
    """Delete an MQTT connection profile."""
    profile = mqtt_manager.get_profile(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    mqtt_manager.remove_profile(profile_id)
    return {"status": "deleted", "id": profile_id}


@router.post("/profiles/{profile_id}/connect")
async def connect_profile(profile_id: str):
    """Connect to MQTT broker using a profile."""
    success = await mqtt_manager.connect(profile_id)
    if not success:
        raise HTTPException(status_code=400, detail="Connection failed")
    profile = mqtt_manager.get_profile(profile_id)
    return {"status": "connected", "id": profile_id, "broker": f"{profile.broker}:{profile.port}" if profile else None}


@router.post("/profiles/{profile_id}/disconnect")
async def disconnect_profile(profile_id: str):
    """Disconnect from MQTT broker."""
    success = await mqtt_manager.disconnect(profile_id)
    return {"status": "disconnected", "id": profile_id}


@router.post("/profiles/{profile_id}/subscribe")
async def subscribe_topic(profile_id: str, body: Dict[str, Any]):
    """Subscribe to an additional topic."""
    topic = body.get("topic", "")
    qos = body.get("qos", 0)
    if not topic:
        raise HTTPException(status_code=400, detail="Topic required")
    success = await mqtt_manager.subscribe(profile_id, topic, qos)
    if not success:
        raise HTTPException(status_code=400, detail="Subscribe failed")
    return {"status": "subscribed", "topic": topic}


@router.post("/profiles/{profile_id}/unsubscribe")
async def unsubscribe_topic(profile_id: str, body: Dict[str, Any]):
    """Unsubscribe from a topic."""
    topic = body.get("topic", "")
    if not topic:
        raise HTTPException(status_code=400, detail="Topic required")
    success = await mqtt_manager.unsubscribe(profile_id, topic)
    return {"status": "unsubscribed", "topic": topic}


@router.post("/profiles/{profile_id}/publish")
async def publish_message(profile_id: str, body: Dict[str, Any]):
    """Publish a message to an MQTT topic."""
    topic = body.get("topic", "")
    payload = body.get("payload", "")
    qos = body.get("qos", 0)
    if not topic:
        raise HTTPException(status_code=400, detail="Topic required")
    success = await mqtt_manager.publish(profile_id, topic, payload, qos)
    if not success:
        raise HTTPException(status_code=400, detail="Publish failed")
    return {"status": "published", "topic": topic}


@router.get("/profiles/{profile_id}/stats")
async def get_profile_stats(profile_id: str):
    """Get statistics for a specific MQTT connection."""
    stats = mqtt_manager.get_stats(profile_id)
    if not stats:
        raise HTTPException(status_code=404, detail="Profile not found")
    return stats


@router.get("/stats")
async def get_mqtt_stats():
    """Get aggregate MQTT statistics."""
    return mqtt_manager.get_stats()


@router.get("/messages")
async def get_messages(limit: int = 50, profile_id: Optional[str] = None):
    """Get recent MQTT messages."""
    messages = mqtt_manager.get_message_history(limit=limit, connection_id=profile_id)
    return {
        "messages": [
            {
                "id": m.id,
                "connection_id": m.connection_id,
                "topic": m.topic,
                "payload": m.payload,
                "json": m.json_data,
                "qos": m.qos,
                "timestamp": m.timestamp.isoformat(),
            }
            for m in messages
        ],
        "count": len(messages),
    }
