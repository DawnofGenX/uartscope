"""MQTT Connection Manager — multi-broker connections, subscriptions, message history, WS bridge."""
import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

try:
    import aiomqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False


@dataclass
class MQTTConnectionProfile:
    """Configuration for a single MQTT broker connection."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "Default"
    broker: str = "localhost"
    port: int = 1883
    username: Optional[str] = None
    password: Optional[str] = None
    topic_prefix: str = "uartscope"
    qos: int = 0
    client_id: Optional[str] = None
    use_tls: bool = False
    keepalive: int = 60
    connected: bool = False
    last_error: Optional[str] = None
    subscribed_topics: List[str] = field(default_factory=list)
    messages_received: int = 0
    bytes_received: int = 0
    connected_at: Optional[datetime] = None


@dataclass
class MQTTMessage:
    """A received MQTT message."""
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    connection_id: str = ""
    topic: str = ""
    payload: str = ""
    json_data: Optional[Dict[str, Any]] = None
    qos: int = 0
    timestamp: datetime = field(default_factory=datetime.utcnow)


class MQTTManager:
    """Manages multiple MQTT broker connections with subscriptions and message history."""

    def __init__(self):
        self._connections: Dict[str, MQTTConnectionProfile] = {}
        self._clients: Dict[str, Any] = {}  # profile_id -> aiomqtt.Client
        self._tasks: Dict[str, asyncio.Task] = {}  # profile_id -> listen task
        self._message_history: List[MQTTMessage] = []
        self._max_history: int = 1000
        self._callbacks: List[Callable[[MQTTMessage], None]] = []
        self._ws_bridge_enabled: bool = True
        self._lock = asyncio.Lock()

    def register_callback(self, fn: Callable):
        """Register callback for received MQTT messages."""
        self._callbacks.append(fn)

    def get_profile(self, profile_id: str) -> Optional[MQTTConnectionProfile]:
        return self._connections.get(profile_id)

    def get_all_profiles(self) -> List[MQTTConnectionProfile]:
        return list(self._connections.values())

    def add_profile(self, profile: MQTTConnectionProfile):
        """Add a new connection profile."""
        self._connections[profile.id] = profile
        logger.info(f"MQTT profile added: {profile.name} ({profile.broker}:{profile.port})")

    def remove_profile(self, profile_id: str):
        """Remove a connection profile and disconnect if connected."""
        profile = self._connections.pop(profile_id, None)
        if profile:
            asyncio.create_task(self._disconnect_profile(profile_id))
            logger.info(f"MQTT profile removed: {profile.name}")

    async def connect(self, profile_id: str) -> bool:
        """Connect to an MQTT broker using a profile."""
        if not MQTT_AVAILABLE:
            logger.warning("aiomqtt not installed. MQTT integration disabled.")
            return False

        profile = self._connections.get(profile_id)
        if not profile:
            logger.error(f"MQTT profile {profile_id} not found")
            return False

        if profile.connected:
            logger.info(f"MQTT profile {profile.name} already connected")
            return True

        try:
            client_kwargs = {
                "hostname": profile.broker,
                "port": profile.port,
                "keepalive": profile.keepalive,
            }
            if profile.username:
                client_kwargs["username"] = profile.username
            if profile.password:
                client_kwargs["password"] = profile.password
            if profile.client_id:
                client_kwargs["identifier"] = profile.client_id
            if profile.use_tls:
                client_kwargs["tls_context"] = None  # Use default TLS context

            client = aiomqtt.Client(**client_kwargs)
            self._clients[profile_id] = client

            # Start listen task
            task = asyncio.create_task(self._listen_loop(profile_id))
            self._tasks[profile_id] = task

            profile.connected = True
            profile.connected_at = datetime.utcnow()
            profile.last_error = None
            logger.info(f"MQTT connected to {profile.broker}:{profile.port} ({profile.name})")
            return True

        except Exception as e:
            profile.connected = False
            profile.last_error = str(e)
            logger.error(f"MQTT connection failed for {profile.name}: {e}")
            return False

    async def disconnect(self, profile_id: str) -> bool:
        """Disconnect from a specific MQTT broker."""
        profile = self._connections.get(profile_id)
        if not profile:
            return False
        await self._disconnect_profile(profile_id)
        return True

    async def _disconnect_profile(self, profile_id: str):
        """Internal disconnect logic."""
        # Cancel listen task
        task = self._tasks.pop(profile_id, None)
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # Close client — aiomqtt handles cleanup on context exit
        self._clients.pop(profile_id, None)

        profile = self._connections.get(profile_id)
        if profile:
            profile.connected = False
            profile.subscribed_topics = []
            logger.info(f"MQTT disconnected: {profile.name}")

    async def _listen_loop(self, profile_id: str):
        """Main listen loop for a connection."""
        profile = self._connections.get(profile_id)
        client = self._clients.get(profile_id)
        if not profile or not client:
            return

        topic_pattern = f"{profile.topic_prefix}/#"
        try:
            async with client:
                await client.subscribe(topic_pattern, qos=profile.qos)
                logger.info(f"MQTT subscribed to {topic_pattern} (QoS {profile.qos})")
                profile.subscribed_topics = [topic_pattern]

                async for message in client.messages:
                    await self._handle_message(profile_id, message)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            profile.connected = False
            profile.last_error = str(e)
            logger.error(f"MQTT listener error for {profile.name}: {e}")

    async def _handle_message(self, profile_id: str, message):
        """Process an incoming MQTT message."""
        profile = self._connections.get(profile_id)
        if not profile:
            return

        try:
            payload = message.payload.decode("utf-8", errors="replace")
            topic = str(message.topic)
            qos = message.qos if hasattr(message, 'qos') else 0

            json_data = None
            try:
                json_data = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                pass

            msg = MQTTMessage(
                connection_id=profile_id,
                topic=topic,
                payload=payload,
                json_data=json_data,
                qos=qos,
            )

            # Update stats
            profile.messages_received += 1
            profile.bytes_received += len(payload)

            # Store in history
            self._message_history.append(msg)
            if len(self._message_history) > self._max_history:
                self._message_history = self._message_history[-self._max_history:]

            # Notify callbacks
            for cb in self._callbacks:
                try:
                    if asyncio.iscoroutinefunction(cb):
                        await cb(msg)
                    else:
                        cb(msg)
                except Exception as e:
                    logger.error(f"MQTT callback error: {e}")

        except Exception as e:
            logger.error(f"MQTT message handling error: {e}")

    async def subscribe(self, profile_id: str, topic: str, qos: int = 0) -> bool:
        """Subscribe to an additional topic on an existing connection."""
        profile = self._connections.get(profile_id)
        client = self._clients.get(profile_id)
        if not profile or not client or not profile.connected:
            return False

        try:
            await client.subscribe(topic, qos=qos)
            if topic not in profile.subscribed_topics:
                profile.subscribed_topics.append(topic)
            logger.info(f"MQTT subscribed to {topic} on {profile.name}")
            return True
        except Exception as e:
            logger.error(f"MQTT subscribe error on {profile.name}: {e}")
            return False

    async def unsubscribe(self, profile_id: str, topic: str) -> bool:
        """Unsubscribe from a topic."""
        profile = self._connections.get(profile_id)
        client = self._clients.get(profile_id)
        if not profile or not client or not profile.connected:
            return False

        try:
            await client.unsubscribe(topic)
            if topic in profile.subscribed_topics:
                profile.subscribed_topics.remove(topic)
            return True
        except Exception as e:
            logger.error(f"MQTT unsubscribe error: {e}")
            return False

    async def publish(self, profile_id: str, topic: str, payload: Any, qos: int = 0) -> bool:
        """Publish a message to an MQTT topic."""
        profile = self._connections.get(profile_id)
        client = self._clients.get(profile_id)
        if not profile or not client or not profile.connected:
            return False

        try:
            if isinstance(payload, (dict, list)):
                payload = json.dumps(payload)
            if isinstance(payload, str):
                payload = payload.encode("utf-8")

            full_topic = f"{profile.topic_prefix}/{topic}" if profile.topic_prefix else topic
            await client.publish(full_topic, payload, qos=qos)
            logger.debug(f"MQTT published to {full_topic}")
            return True
        except Exception as e:
            logger.error(f"MQTT publish error: {e}")
            return False

    def get_message_history(self, limit: int = 100, connection_id: Optional[str] = None) -> List[MQTTMessage]:
        """Get recent MQTT messages."""
        msgs = self._message_history
        if connection_id:
            msgs = [m for m in msgs if m.connection_id == connection_id]
        return msgs[-limit:]

    def get_stats(self, profile_id: Optional[str] = None) -> Dict:
        """Get MQTT statistics."""
        if profile_id:
            profile = self._connections.get(profile_id)
            if not profile:
                return {}
            return {
                "id": profile.id,
                "name": profile.name,
                "connected": profile.connected,
                "broker": f"{profile.broker}:{profile.port}",
                "subscribed_topics": len(profile.subscribed_topics),
                "messages_received": profile.messages_received,
                "bytes_received": profile.bytes_received,
                "connected_at": profile.connected_at.isoformat() if profile.connected_at else None,
                "last_error": profile.last_error,
            }

        total_messages = sum(p.messages_received for p in self._connections.values())
        total_bytes = sum(p.bytes_received for p in self._connections.values())
        connected_count = sum(1 for p in self._connections.values() if p.connected)

        return {
            "total_connections": len(self._connections),
            "connected": connected_count,
            "total_messages": total_messages,
            "total_bytes": total_bytes,
            "history_size": len(self._message_history),
        }

    async def shutdown(self):
        """Disconnect all connections on shutdown."""
        for profile_id in list(self._connections.keys()):
            await self._disconnect_profile(profile_id)
        logger.info("MQTT manager shut down")


# Singleton
mqtt_manager = MQTTManager()
