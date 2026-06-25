"""Alert Engine — rule-based monitoring and notifications."""
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

from app.config import settings
from app.core.telemetry_engine import Metric

logger = logging.getLogger(__name__)


class AlertRule:
    def __init__(self, id: str, name: str, metric_name: str, condition: str,
                 threshold: float, secondary_threshold: Optional[float] = None,
                 cooldown: int = 60, severity: str = "warning"):
        self.id = id
        self.name = name
        self.metric_name = metric_name
        self.condition = condition
        self.threshold = threshold
        self.secondary_threshold = secondary_threshold
        self.cooldown = cooldown
        self.severity = severity
        self.enabled = True
        self.last_triggered: Optional[datetime] = None
        self.trigger_count = 0
        self.last_value: Optional[float] = None

    def check(self, value: float) -> bool:
        """Check if a value triggers this rule."""
        if not self.enabled:
            return False

        # Cooldown check
        if self.last_triggered:
            elapsed = (datetime.utcnow() - self.last_triggered).total_seconds()
            if elapsed < self.cooldown:
                return False

        triggered = False
        if self.condition == "gt":
            triggered = value > self.threshold
        elif self.condition == "lt":
            triggered = value < self.threshold
        elif self.condition == "eq":
            triggered = abs(value - self.threshold) < 0.001
        elif self.condition == "gte":
            triggered = value >= self.threshold
        elif self.condition == "lte":
            triggered = value <= self.threshold
        elif self.condition == "range":
            low = self.threshold
            high = self.secondary_threshold if self.secondary_threshold is not None else self.threshold
            triggered = not (low <= value <= high)
        elif self.condition == "change":
            # Trigger on any change exceeding threshold (delta)
            if self.last_value is not None:
                delta = abs(value - self.last_value)
                # threshold for 'change' = minimum delta to trigger
                min_delta = self.threshold if self.threshold > 0 else 0.01
                triggered = delta >= min_delta
            else:
                triggered = False

        self.last_value = value

        if triggered:
            self.last_triggered = datetime.utcnow()
            self.trigger_count += 1

        return triggered


class AlertEngine:
    """Evaluates alert rules against incoming telemetry."""

    def __init__(self):
        self._rules: Dict[str, AlertRule] = {}
        self._callbacks: List = []
        self._alert_history: List[Dict[str, Any]] = []
        self._acknowledged: set = set()  # Set of alert IDs that have been acknowledged

    def register_callback(self, fn):
        """Register callback for alert events."""
        self._callbacks.append(fn)

    def add_rule(self, rule: AlertRule):
        """Add an alert rule."""
        self._rules[rule.id] = rule
        logger.info(f"Alert rule added: {rule.name} ({rule.metric_name} {rule.condition} {rule.threshold})")

    def remove_rule(self, rule_id: str):
        """Remove an alert rule."""
        self._rules.pop(rule_id, None)

    def get_rule(self, rule_id: str) -> Optional[AlertRule]:
        return self._rules.get(rule_id)

    def get_all_rules(self) -> List[AlertRule]:
        return list(self._rules.values())

    async def evaluate(self, device_id: str, session_id: str, metric: Metric):
        """Evaluate all rules against a new metric value."""
        for rule in self._rules.values():
            if rule.metric_name.upper() != metric.name.upper():
                continue

            if rule.check(metric.value):
                alert = {
                    "id": f"{rule.id}-{datetime.utcnow().timestamp()}",
                    "rule_id": rule.id,
                    "rule_name": rule.name,
                    "device_id": device_id,
                    "session_id": session_id,
                    "metric_name": metric.name,
                    "value": metric.value,
                    "severity": rule.severity,
                    "message": f"{rule.name}: {metric.name} = {metric.value} ({rule.condition} {rule.threshold})",
                    "timestamp": datetime.utcnow().isoformat(),
                    "acknowledged": False,
                }
                self._alert_history.append(alert)

                # Notify callbacks (includes WebSocket broadcast)
                for cb in self._callbacks:
                    try:
                        if asyncio.iscoroutinefunction(cb):
                            await cb(alert)
                        else:
                            cb(alert)
                    except Exception as e:
                        logger.error(f"Alert callback error: {e}")

    def acknowledge_alert(self, alert_id: str) -> bool:
        """Acknowledge an alert."""
        self._acknowledged.add(alert_id)
        for alert in self._alert_history:
            if alert.get("id") == alert_id:
                alert["acknowledged"] = True
                return True
        return False

    def get_alert_history(self, limit: int = 100, unacknowledged_only: bool = False) -> List[Dict]:
        """Get alert trigger history."""
        history = self._alert_history
        if unacknowledged_only:
            history = [a for a in history if not a.get("acknowledged", False)]
        return history[-limit:]

    def clear_history(self):
        self._alert_history.clear()
        self._acknowledged.clear()


# Singleton
alert_engine = AlertEngine()
