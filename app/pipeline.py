"""The end-to-end pipeline:  fetch -> analyse (Gemini) -> store (SQLite) -> index (Chroma) -> alert.

Every function is safe to call repeatedly: emails are de-duplicated by Message-ID, analysed once and indexed once.
"""
import logging
from typing import Callable, Optional

from . import alerts, analyzer, db, demo_data, email_client, rag
from .config import settings

log = logging.getLogger("pipeline")
Progress = Optional[Callable[[str], None]]


def _say(progress: Progress, msg: str) -> None:
    log.info(msg)
    if progress:
        progress(msg)


def sync_imap(progress: Progress = None, limit: Optional[int] = None) -> dict:
    """Pull new emails from the mailbox into SQLite."""
    account_key = f"{settings.IMAP_USER}|{settings.IMAP_FOLDER}"
    if db.get_meta("imap_account") != account_key:  # different mailbox than last time -> start fresh
        db.set_meta("imap_account", account_key)
        db.set_meta("last_uid", 0)
    since = db.get_meta("last_uid", 0) or None
    _say(progress, f"Connecting to {settings.IMAP_HOST} as {settings.IMAP_USER}…")
    emails, highest = email_client.fetch_emails(limit=limit, since_uid=since)
    new = sum(1 for e in emails if db.insert_email(e))
    db.set_meta("last_uid", highest)
    _say(progress, f"Fetched {len(emails)} emails ({new} new).")
    return {"fetched": len(emails), "new": new}


def analyze_pending(progress: Progress = None, use_llm: bool = True) -> dict:
    """Analyse every email that has no analysis yet; results are saved after each batch."""
    pending = db.get_unanalyzed()
    if not pending:
        return {"analyzed": 0, "gemini": 0, "heuristic": 0}
    counts = {"gemini": 0, "heuristic": 0}
    total = len(pending)
    _say(progress, f"Analysing {total} emails ({'Gemini' if use_llm and settings.llm_configured else 'keyword heuristics'})…")
    for batch, done, _ in analyzer.iter_analysis(pending, use_llm=use_llm):
        for email, analysis, method in batch:
            db.save_analysis(email["id"], analysis, method)
            counts[method] += 1
        _say(progress, f"Analysed {done}/{total} emails…")
    return {"analyzed": total, **counts}


def index_pending(progress: Progress = None) -> int:
    _say(progress, "Indexing emails for the chatbot…")
    n = rag.index_pending()
    _say(progress, f"Indexed {n} emails.")
    return n


def process(sync: bool = True, send_alerts: bool = True, use_llm: bool = True, progress: Progress = None) -> dict:
    """Full run used by the 'Sync' button and the scheduler."""
    result: dict = {}
    if sync:
        result["sync"] = sync_imap(progress)
    result["analysis"] = analyze_pending(progress, use_llm=use_llm)
    result["indexed"] = index_pending(progress)
    if send_alerts:
        _say(progress, "Checking alert rules…")
        result["alerts"] = alerts.run_alerts()
    _say(progress, "Done.")
    return result


def load_demo(use_gemini: bool = False, send_alerts: bool = True, reset: bool = True, progress: Progress = None) -> dict:
    """Load the synthetic inbox. use_gemini=False stores the precomputed analyses (instant, zero API usage);
    use_gemini=True lets Gemini analyse every email for real."""
    if reset:
        _say(progress, "Clearing previous data…")
        db.reset_all()
        rag.reset()
    data = demo_data.build_dataset()
    _say(progress, f"Loading {len(data)} demo emails…")
    inserted = 0
    for item in data:
        email_id = db.insert_email(item["email"])
        if email_id:
            inserted += 1
            if not use_gemini:
                db.save_analysis(email_id, item["analysis"], "precomputed")
    result = {"loaded": inserted}
    result["analysis"] = analyze_pending(progress) if use_gemini else {"analyzed": inserted, "method": "precomputed"}
    result["indexed"] = index_pending(progress)
    if send_alerts:
        _say(progress, "Checking alert rules…")
        result["alerts"] = alerts.run_alerts()
    _say(progress, "Demo inbox ready.")
    return result
