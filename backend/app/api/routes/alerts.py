"""Alert management API routes."""
from fastapi import APIRouter, HTTPException
from typing import List

from app.core.alert_engine import alert_engine, AlertRule
from app.models import AlertRuleCreate, AlertRuleResponse

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.post("/rules", response_model=dict)
async def create_rule(rule: AlertRuleCreate):
    """Create a new alert rule."""
    import uuid
    rule_id = str(uuid.uuid4())
    alert_rule = AlertRule(
        id=rule_id,
        name=rule.name,
        metric_name=rule.metric_name,
        condition=rule.condition,
        threshold=rule.threshold,
        secondary_threshold=rule.secondary_threshold,
        cooldown=rule.cooldown_seconds,
        severity=rule.severity,
    )
    alert_engine.add_rule(alert_rule)
    return {"id": rule_id, "created": True}


@router.get("/rules", response_model=List[dict])
async def list_rules():
    """List all alert rules."""
    rules = alert_engine.get_all_rules()
    return [
        {
            "id": r.id,
            "name": r.name,
            "metric_name": r.metric_name,
            "condition": r.condition,
            "threshold": r.threshold,
            "secondary_threshold": r.secondary_threshold,
            "cooldown": r.cooldown,
            "severity": r.severity,
            "enabled": r.enabled,
            "trigger_count": r.trigger_count,
        }
        for r in rules
    ]


@router.delete("/rules/{rule_id}")
async def delete_rule(rule_id: str):
    """Delete an alert rule."""
    alert_engine.remove_rule(rule_id)
    return {"deleted": True}


@router.put("/rules/{rule_id}/enable")
async def enable_rule(rule_id: str, enabled: bool = True):
    """Enable or disable an alert rule."""
    rule = alert_engine.get_rule(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    rule.enabled = enabled
    return {"enabled": enabled}


@router.get("/history", response_model=List[dict])
async def get_alert_history(limit: int = 100):
    """Get alert trigger history."""
    return alert_engine.get_alert_history(limit)


@router.post("/test")
async def test_rule(rule: dict):
    """Test a rule against a value without saving it."""
    from app.core.telemetry_engine import Metric
    test_rule_obj = AlertRule(
        id="test",
        name=rule.get("name", "Test"),
        metric_name=rule.get("metric_name", "TEMP"),
        condition=rule.get("condition", "gt"),
        threshold=rule.get("threshold", 0),
        secondary_threshold=rule.get("secondary_threshold"),
    )
    test_value = rule.get("test_value", 0)
    triggered = test_rule_obj.check(test_value)
    return {"triggered": triggered, "value": test_value}
