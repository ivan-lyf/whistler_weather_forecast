"""SMS alert service: checks rules against predictions and sends Twilio SMS."""

import logging
import operator as op
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.models.alert import AlertHistory, AlertRule, AlertSubscriber
from app.models.model_prediction import ModelPrediction

log = logging.getLogger("alert_service")

OPERATORS = {
    ">": op.gt,
    ">=": op.ge,
    "<": op.lt,
    "<=": op.le,
    "==": op.eq,
}

VALID_TARGETS = {"snowfall_24h", "wind_6h", "wind_12h", "freezing_level", "precip_type"}

RATE_LIMIT_HOURS = 6  # max 1 alert per subscriber per target per this many hours
LOC_NAMES = {1: "base", 2: "mid", 3: "alpine"}


def send_sms(phone: str, message: str) -> str | None:
    """Send SMS via Twilio. Returns message SID or None if disabled/failed."""
    if not settings.alert_enabled:
        log.info("[DRY RUN] SMS to %s: %s", phone, message[:80])
        return None

    if not all([settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_phone_number]):
        log.warning("Twilio not configured — skipping SMS to %s", phone)
        return None

    try:
        from twilio.rest import Client
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        msg = client.messages.create(
            body=message,
            from_=settings.twilio_phone_number,
            to=phone,
        )
        log.info("SMS sent to %s (SID: %s)", phone, msg.sid)
        return msg.sid
    except Exception:
        log.exception("Failed to send SMS to %s", phone)
        return None


def _was_recently_alerted(db: Session, subscriber_id: int, target_name: str) -> bool:
    """Check if we already sent an alert for this target within the rate limit window."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=RATE_LIMIT_HOURS)
    count = db.execute(
        select(AlertHistory.id).where(
            AlertHistory.subscriber_id == subscriber_id,
            AlertHistory.sent_at >= cutoff,
            AlertHistory.message.contains(target_name),
        ).limit(1)
    ).first()
    return count is not None


def _get_latest_prediction(db: Session, target_name: str, location_id: int) -> float | str | None:
    """Get the most recent prediction value for a target+location."""
    row = db.execute(
        select(ModelPrediction)
        .where(
            ModelPrediction.target_name == target_name,
            ModelPrediction.location_id == location_id,
        )
        .order_by(ModelPrediction.target_time.desc())
        .limit(1)
    ).scalar_one_or_none()

    if not row:
        return None
    return row.predicted_value if row.predicted_value is not None else row.predicted_class


def _get_prediction_summary(db: Session, location_id: int) -> dict:
    """Get latest values for all targets at a location (for context in alert message)."""
    summary = {}
    for target in ["snowfall_24h", "wind_6h", "freezing_level"]:
        val = _get_latest_prediction(db, target, location_id)
        if val is not None:
            summary[target] = val
    return summary


def check_weather_alerts(db: Session) -> int:
    """Check all active subscriber rules against latest predictions. Returns alert count."""
    subscribers = db.execute(
        select(AlertSubscriber).where(AlertSubscriber.is_active == True)
    ).scalars().all()

    if not subscribers:
        log.info("No active subscribers")
        return 0

    now = datetime.now(timezone.utc)
    sent_count = 0

    for sub in subscribers:
        rules = db.execute(
            select(AlertRule).where(
                AlertRule.subscriber_id == sub.id,
                AlertRule.is_enabled == True,
            )
        ).scalars().all()

        for rule in rules:
            if rule.target_name not in VALID_TARGETS:
                continue

            # Rate limit check
            if _was_recently_alerted(db, sub.id, rule.target_name):
                continue

            # Get latest prediction
            pred_value = _get_latest_prediction(db, rule.target_name, sub.location_id)
            if pred_value is None:
                continue

            # For classification targets, skip numeric comparison
            if isinstance(pred_value, str):
                continue

            # Check threshold
            op_func = OPERATORS.get(rule.operator)
            if not op_func:
                continue

            if not op_func(pred_value, rule.threshold):
                continue

            # Threshold met — build and send alert
            loc_name = LOC_NAMES.get(sub.location_id, "alpine")
            summary = _get_prediction_summary(db, sub.location_id)

            target_labels = {
                "snowfall_24h": "24h snowfall",
                "wind_6h": "6h max wind",
                "wind_12h": "12h max wind",
                "freezing_level": "Freezing level",
            }
            target_label = target_labels.get(rule.target_name, rule.target_name)
            target_unit = {"snowfall_24h": "cm", "wind_6h": "km/h", "wind_12h": "km/h", "freezing_level": "m"}.get(rule.target_name, "")

            message = (
                f"WHISTLER FORECAST ALERT\n"
                f"{loc_name.upper()} {target_label}: {pred_value:.1f}{target_unit} "
                f"(your threshold: {rule.operator}{rule.threshold:.0f}{target_unit})\n"
            )
            if "snowfall_24h" in summary and rule.target_name != "snowfall_24h":
                message += f"Snowfall: {summary['snowfall_24h']:.1f}cm\n"
            if "freezing_level" in summary and rule.target_name != "freezing_level":
                message += f"Freezing level: {summary['freezing_level']:.0f}m\n"
            message += "— whistler_forecast.v1\nReply STOP to unsubscribe"

            sid = send_sms(sub.phone_number, message)

            # Log to history
            db.add(AlertHistory(
                subscriber_id=sub.id,
                rule_id=rule.id,
                alert_type="weather",
                message=message,
                predicted_value=pred_value,
                sent_at=now,
                twilio_sid=sid,
            ))
            db.commit()
            sent_count += 1

    # --- "Good Ski Day" compound alert for all subscribers ---
    for sub in subscribers:
        if _was_recently_alerted(db, sub.id, "good_ski_day"):
            continue

        summary = _get_prediction_summary(db, sub.location_id)
        snow_24h = summary.get("snowfall_24h")
        wind = _get_latest_prediction(db, "wind_6h", sub.location_id)
        precip = _get_latest_prediction(db, "precip_type", sub.location_id)
        fzl = _get_latest_prediction(db, "freezing_level", sub.location_id)

        # Good ski day: significant snow, manageable wind, snowing (not rain)
        is_good_day = (
            snow_24h is not None and isinstance(snow_24h, (int, float)) and snow_24h >= 10
            and wind is not None and isinstance(wind, (int, float)) and wind < 40
            and precip == "snow"
        )

        if is_good_day:
            loc_name = LOC_NAMES.get(sub.location_id, "alpine")
            message = (
                f"POWDER DAY ALERT!\n"
                f"{loc_name.upper()}: {snow_24h:.0f}cm expected in 24h\n"
                f"Wind: {wind:.0f}km/h | Precip: SNOW"
            )
            if fzl and isinstance(fzl, (int, float)):
                message += f" | FZL: {fzl:.0f}m"
            message += "\n— whistler_forecast.v1\nReply STOP to unsubscribe"

            sid = send_sms(sub.phone_number, message)
            db.add(AlertHistory(
                subscriber_id=sub.id, rule_id=None,
                alert_type="good_ski_day", message=message,
                predicted_value=snow_24h, sent_at=now, twilio_sid=sid,
            ))
            db.commit()
            sent_count += 1
            log.info("Good ski day alert sent to %s (snow=%.0fcm, wind=%.0f, precip=%s)",
                     sub.phone_number, snow_24h, wind, precip)

    log.info("Weather alerts sent: %d", sent_count)
    return sent_count


def check_drift_alerts(db: Session, drift_alerts: list[dict]) -> int:
    """Send drift alerts to admin subscribers."""
    if not drift_alerts:
        return 0

    admins = db.execute(
        select(AlertSubscriber).where(
            AlertSubscriber.is_active == True,
            AlertSubscriber.is_admin == True,
        )
    ).scalars().all()

    if not admins:
        log.info("No admin subscribers for drift alerts")
        return 0

    now = datetime.now(timezone.utc)
    message = "[SYSTEM] Model drift detected\n"
    for a in drift_alerts:
        if "rolling_mae" in a:
            message += f"{a['target']}/{a['location']}: MAE {a['rolling_mae']:.1f} vs baseline {a.get('baseline_mae', 0):.1f} ({a.get('ratio', 0):.1f}x)\n"
        if "rolling_accuracy" in a:
            message += f"{a['target']}/{a['location']}: accuracy {a['rolling_accuracy']:.3f}\n"
    message += "Action: retrain recommended"

    sent_count = 0
    for admin in admins:
        if _was_recently_alerted(db, admin.id, "drift"):
            continue
        sid = send_sms(admin.phone_number, message)
        db.add(AlertHistory(
            subscriber_id=admin.id,
            alert_type="drift",
            message=message,
            sent_at=now,
            twilio_sid=sid,
        ))
        db.commit()
        sent_count += 1

    log.info("Drift alerts sent: %d", sent_count)
    return sent_count
