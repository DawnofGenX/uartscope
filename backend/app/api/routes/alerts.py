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
async def get_alert_history(limit: int = 100, unacknowledged_only: bool = False):
    """Get alert trigger history."""
    return alert_engine.get_alert_history(limit, unacknowledged_only)


@router.post("/acknowledge/{alert_id}")
async def acknowledge_alert(alert_id: str):
    """Acknowledge an alert."""
    success = alert_engine.acknowledge_alert(alert_id)
    if not success:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"acknowledged": True}


@router.post("/acknowledge/all")
async def acknowledge_all():
    """Acknowledge all unacknowledged alerts."""
    count = 0
    for alert in alert_engine.get_alert_history(unacknowledged_only=True):
        alert_engine.acknowledge_alert(alert["id"])
        count += 1
    return {"acknowledged_count": count}


@router.get("/stats")
async def alert_stats():
    """Get alert statistics."""
    history = alert_engine.get_alert_history(limit=10000)
    unacknowledged = len([a for a in history if not a.get("acknowledged", False)])
    by_severity = {}
    for alert in history:
        sev = alert.get("severity", "warning")
        by_severity[sev] = by_severity.get(sev, 0) + 1
    return {
        "total_alerts": len(history),
        "unacknowledged": unacknowledged,
        "by_severity": by_severity,
        "active_rules": len([r for r in alert_engine.get_all_rules() if r.enabled]),
        "total_rules": len(alert_engine.get_all_rules()),
    }


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
