"""MQTT client for remote IoT device telemetry streaming."""
import asyncio
import json
import logging
from typing import Optional, Dict, Any, Callable

from app.config import settings

logger = logging.getLogger(__name__)

try:
    import aiomqtt
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False


class MQTTClient:
    """MQTT client for receiving remote device telemetry."""

    def __init__(self):
        self._client = None
        self._connected = False
        self._callbacks: List[Callable] = []

    def register_callback(self, fn: Callable):
        """Register callback for received MQTT messages."""
        self._callbacks.append(fn)

    async def connect(self):
        """Connect to MQTT broker."""
        if not MQTT_AVAILABLE:
            logger.warning("aiomqtt not installed. MQTT integration disabled.")
            return

        if not settings.mqtt_enabled:
            logger.info("MQTT disabled in config.")
            return

        try:
            self._client = aiomqtt.Client(
                hostname=settings.mqtt_broker,
                port=settings.mqtt_port,
            )
            self._connected = True
            logger.info(f"MQTT connected to {settings.mqtt_broker}:{settings.mqtt_port}")
            asyncio.create_task(self._listen())
        except Exception as e:
            logger.error(f"MQTT connection failed: {e}")

    async def _listen(self):
        """Listen for MQTT messages."""
        if not self._client:
            return

        topic = f"{settings.mqtt_topic_prefix}/#"
        try:
            async with self._client:
                await self._client.subscribe(topic)
                logger.info(f"MQTT subscribed to {topic}")
                async for message in self._client.messages:
                    await self._handle_message(message)
        except Exception as e:
            logger.error(f"MQTT listener error: {e}")
            self._connected = False

    async def _handle_message(self, message):
        """Process an incoming MQTT message."""
        try:
            payload = message.payload.decode("utf-8", errors="replace")
            topic = str(message.topic)
            data = {
                "source": "mqtt",
                "topic": topic,
                "payload": payload,
            }
            # Try JSON parse
            try:
                data["json"] = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                pass

            for cb in self._callbacks:
                try:
                    if asyncio.iscoroutinefunction(cb):
                        await cb(data)
                    else:
                        cb(data)
                except Exception as e:
                    logger.error(f"MQTT callback error: {e}")
        except Exception as e:
            logger.error(f"MQTT message handling error: {e}")

    async def publish(self, topic: str, payload: Dict[str, Any]):
        """Publish data to MQTT."""
        if not self._connected or not self._client:
            return
        try:
            await self._client.publish(
                f"{settings.mqtt_topic_prefix}/{topic}",
                json.dumps(payload).encode(),
            )
        except Exception as e:
            logger.error(f"MQTT publish error: {e}")

    async def disconnect(self):
        """Disconnect from MQTT broker."""
        self._connected = False
        if self._client:
            # aiomqtt handles cleanup on context exit
            self._client = None
        logger.info("MQTT disconnected")

    @property
    def is_connected(self) -> bool:
        return self._connected


# Singleton
mqtt_client = MQTTClient()
