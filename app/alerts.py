"""Alerts: Telegram (free) when configured, always logged inside the app.

An email triggers an alert once when it is High priority OR has an open deadline within ALERT_DEADLINE_HOURS.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional

import requests

from . import db
from .config import settings

log = logging.getLogger("alerts")


def send_telegram(text: str) -> tuple[bool, str]:
    if not settings.telegram_configured:
        return False, "Telegram not configured"
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": settings.TELEGRAM_CHAT_ID, "text": text[:4000], "disable_web_page_preview": True},
            timeout=15,
        )
        if r.ok:
            return True, "sent"
        return False, f"Telegram error {r.status_code}: {r.text[:150]}"
    except requests.RequestException as exc:
        return False, f"Telegram unreachable: {exc}"


def _format(c: dict) -> tuple[str, str]:
    icon = "🔴" if c["priority"] == "High" else "⏰"
    kind = "high_priority" if c["priority"] == "High" else "deadline_soon"
    lines = [f"{icon} {c['priority'].upper()} · {c['subject']}", f"From: {c['sender_name']}"]
    if c.get("summary"):
        lines.append(c["summary"])
    if c.get("priority_reason"):
        lines.append(f"Why: {c['priority_reason']}")
    if c.get("soon_deadlines"):
        lines.append(f"Due soon: {c['soon_deadlines']}")
    return kind, "\n".join(lines)


def _dispatch(email_id, kind: str, message: str) -> str:
    ok, info = send_telegram(message)
    channel = "telegram" if ok else "app"
    if not ok and settings.telegram_configured:
        log.warning("Telegram failed: %s", info)
    log.info("ALERT [%s] %s", channel, message.replace("\n", " | ")[:160])
    db.add_alert(email_id, kind, message, channel)
    return channel


def run_alerts(max_alerts: Optional[int] = None) -> dict:
    """Send alerts for new important emails. Extra ones beyond the cap are summarised in one message."""
    cap = max_alerts if max_alerts is not None else settings.MAX_ALERTS_PER_RUN
    today = datetime.now().date()
    cutoff = today + timedelta(days=max(1, round(settings.ALERT_DEADLINE_HOURS / 24)))
    candidates = db.pending_alert_candidates(cutoff.isoformat(), today.isoformat())
    if not candidates:
        return {"candidates": 0, "sent": 0, "suppressed": 0}
    sent = 0
    for c in candidates[:cap]:
        kind, msg = _format(c)
        _dispatch(c["id"], kind, msg)
        sent += 1
    rest = candidates[cap:]
    if rest:
        _dispatch(None, "summary", f"📬 {len(rest)} more important emails need attention (open the dashboard to see them).")
    db.mark_alerted([c["id"] for c in candidates])
    return {"candidates": len(candidates), "sent": sent, "suppressed": len(rest)}


def send_test_alert() -> dict:
    msg = "✅ Email Analyser test alert – your alert channel works."
    channel = _dispatch(None, "test", msg)
    return {"channel": channel, "telegram_configured": settings.telegram_configured}
