import logging
import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.alert_service import VALID_TARGETS
from app.database import get_db
from app.models.alert import AlertHistory, AlertRule, AlertSubscriber

log = logging.getLogger("alerts_router")

router = APIRouter(prefix="/api/alerts")

PHONE_REGEX = re.compile(r"^\+?[1-9]\d{6,14}$")
VALID_OPERATORS = {">", ">=", "<", "<=", "=="}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class SubscribeRequest(BaseModel):
    phone_number: str
    name: str | None = None
    location: str = "alpine"

    @field_validator("phone_number")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        v = v.strip().replace(" ", "").replace("-", "")
        if not PHONE_REGEX.match(v):
            raise ValueError("Invalid phone number. Use international format: +1234567890")
        return v


class RuleRequest(BaseModel):
    phone_number: str
    target_name: str
    operator: str = ">"
    threshold: float

    @field_validator("target_name")
    @classmethod
    def validate_target(cls, v: str) -> str:
        if v not in VALID_TARGETS:
            raise ValueError(f"Invalid target. Must be one of: {VALID_TARGETS}")
        return v

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v: str) -> str:
        if v not in VALID_OPERATORS:
            raise ValueError(f"Invalid operator. Must be one of: {VALID_OPERATORS}")
        return v


class UnsubscribeRequest(BaseModel):
    phone_number: str | None = None
    token: str | None = None


LOC_IDS = {"base": 1, "mid": 2, "alpine": 3}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/subscribe")
def subscribe(req: SubscribeRequest, db: Session = Depends(get_db)):
    """Subscribe a phone number to alerts."""
    loc_id = LOC_IDS.get(req.location, 3)

    existing = db.execute(
        select(AlertSubscriber).where(AlertSubscriber.phone_number == req.phone_number)
    ).scalar_one_or_none()

    if existing:
        if not existing.is_active:
            existing.is_active = True
            existing.location_id = loc_id
            db.commit()
            return {"status": "reactivated", "subscriber_id": existing.id}
        return {"status": "already_subscribed", "subscriber_id": existing.id}

    import uuid
    sub = AlertSubscriber(
        phone_number=req.phone_number,
        name=req.name,
        location_id=loc_id,
        is_active=True,
        is_admin=False,
        created_at=datetime.now(timezone.utc),
        unsubscribe_token=uuid.uuid4().hex[:16],
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)

    log.info("New subscriber: %s (id=%d)", req.phone_number, sub.id)
    return {"status": "subscribed", "subscriber_id": sub.id}


@router.post("/rules")
def add_rule(req: RuleRequest, db: Session = Depends(get_db)):
    """Add an alert rule for a subscriber."""
    sub = db.execute(
        select(AlertSubscriber).where(AlertSubscriber.phone_number == req.phone_number)
    ).scalar_one_or_none()

    if not sub:
        raise HTTPException(status_code=404, detail="Phone number not subscribed. Subscribe first.")
    if not sub.is_active:
        raise HTTPException(status_code=400, detail="Subscriber is inactive. Re-subscribe first.")

    rule = AlertRule(
        subscriber_id=sub.id,
        target_name=req.target_name,
        operator=req.operator,
        threshold=req.threshold,
        is_enabled=True,
        created_at=datetime.now(timezone.utc),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)

    log.info("New rule: subscriber %d, %s %s %.1f", sub.id, req.target_name, req.operator, req.threshold)
    return {
        "status": "rule_created",
        "rule_id": rule.id,
        "target_name": rule.target_name,
        "operator": rule.operator,
        "threshold": rule.threshold,
    }


@router.get("/rules/{phone_number}")
def list_rules(phone_number: str, db: Session = Depends(get_db)):
    """List all alert rules for a phone number."""
    sub = db.execute(
        select(AlertSubscriber).where(AlertSubscriber.phone_number == phone_number)
    ).scalar_one_or_none()

    if not sub:
        raise HTTPException(status_code=404, detail="Phone number not found")

    rules = db.execute(
        select(AlertRule).where(AlertRule.subscriber_id == sub.id)
    ).scalars().all()

    return {
        "subscriber_id": sub.id,
        "phone_number": sub.phone_number,
        "location": {1: "base", 2: "mid", 3: "alpine"}.get(sub.location_id, "alpine"),
        "is_active": sub.is_active,
        "rules": [
            {
                "id": r.id,
                "target_name": r.target_name,
                "operator": r.operator,
                "threshold": r.threshold,
                "is_enabled": r.is_enabled,
            }
            for r in rules
        ],
    }


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: int, db: Session = Depends(get_db)):
    """Delete an alert rule."""
    rule = db.get(AlertRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    db.delete(rule)
    db.commit()
    return {"status": "deleted", "rule_id": rule_id}


@router.post("/unsubscribe")
def unsubscribe(req: UnsubscribeRequest, db: Session = Depends(get_db)):
    """Unsubscribe by phone number or token."""
    sub = None
    if req.token:
        sub = db.execute(
            select(AlertSubscriber).where(AlertSubscriber.unsubscribe_token == req.token)
        ).scalar_one_or_none()
    elif req.phone_number:
        sub = db.execute(
            select(AlertSubscriber).where(AlertSubscriber.phone_number == req.phone_number)
        ).scalar_one_or_none()

    if not sub:
        raise HTTPException(status_code=404, detail="Subscriber not found")

    sub.is_active = False
    db.commit()
    log.info("Unsubscribed: %s (id=%d)", sub.phone_number, sub.id)
    return {"status": "unsubscribed"}


@router.get("/history")
def alert_history(limit: int = 50, db: Session = Depends(get_db)):
    """Recent alert history (admin view)."""
    rows = db.execute(
        select(AlertHistory)
        .order_by(AlertHistory.sent_at.desc())
        .limit(limit)
    ).scalars().all()

    return [
        {
            "id": r.id,
            "subscriber_id": r.subscriber_id,
            "alert_type": r.alert_type,
            "message": r.message,
            "predicted_value": r.predicted_value,
            "sent_at": r.sent_at.isoformat(),
            "twilio_sid": r.twilio_sid,
        }
        for r in rows
    ]
