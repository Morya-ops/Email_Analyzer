"""Email analysis: priority + explanation, category, summary, action flag and deadlines.

One Gemini request analyses a small batch of emails and returns a JSON array. That keeps us
well inside the free-tier request limits (e.g. 100 emails = 20 requests with batch size 5).
If Gemini is unavailable the app falls back to simple keyword heuristics so nothing crashes.
"""
import logging
import re
from datetime import datetime, timezone
from typing import Callable, Optional

from .config import settings
from .llm import LLMError, generate_json, llm_available

log = logging.getLogger("analyzer")

PRIORITIES = ["High", "Medium", "Low"]
CATEGORIES = ["Academic", "Work", "Recruitment", "Finance", "Security", "Personal", "Promotions", "Other"]

SYSTEM_PROMPT = """You are an email triage assistant. For every email you receive, produce a JSON object.

PRIORITY RUBRIC
- High: needs action within ~48 hours, OR comes from someone important (professor, HoD, exam cell, placement cell,
  recruiter, manager, bank / security team) with real consequences if ignored (interview, payment due, offer, exam change).
- Medium: action needed but not urgent (3-10 days away), or useful information from important senders, or personal messages.
- Low: promotions, newsletters, automated notifications with no action needed, and suspicious / phishing emails.
  (For phishing, say clearly in priority_reason that it looks suspicious and must not be clicked.)

Always explain the priority in ONE short sentence that names the concrete signals
(who the sender is, the deadline, the tone, whether action is required).

CATEGORIES (choose exactly one): Academic, Work, Recruitment, Finance, Security, Personal, Promotions, Other

DEADLINES: extract every task with a due date or time. Resolve relative dates ("by Friday", "tomorrow", "next Monday")
using the email's received date given in the input. Output due_date as YYYY-MM-DD, or null if no date is stated.
Never invent deadlines. confidence is "high" for explicit dates, "medium" for resolved relative dates.

SUMMARY: 1-2 plain sentences capturing what the email wants / says. No greetings, no fluff.

Return ONLY JSON, with no markdown fences."""

OUTPUT_SPEC = """Return a JSON array with exactly one object per email, in the same order, shaped like:
[
  {
    "id": <the email id given in the input>,
    "priority": "High" | "Medium" | "Low",
    "priority_reason": "<one sentence naming the concrete signals>",
    "category": "<one of the categories>",
    "summary": "<1-2 sentences>",
    "action_required": true | false,
    "deadlines": [{"task": "<short task>", "due_date": "YYYY-MM-DD" | null, "confidence": "high" | "medium"}]
  }
]"""


def _context_block() -> str:
    lines = [f"ABOUT THE MAILBOX OWNER: {settings.USER_CONTEXT}"]
    if settings.VIP_SENDERS:
        lines.append("VIP senders (treat as important): " + ", ".join(settings.VIP_SENDERS))
    return "\n".join(lines)


def _format_email(e: dict) -> str:
    received = e["received_at"]
    try:
        dt = datetime.fromisoformat(received)
        received = f"{dt.strftime('%Y-%m-%d')} ({dt.strftime('%A')})"
    except ValueError:
        pass
    body = (e.get("body") or "")[: settings.ANALYSIS_BODY_CHARS]
    return (f"### EMAIL id={e['id']}\nFrom: {e.get('sender_name')} <{e.get('sender_email')}>\n"
            f"Received: {received}\nSubject: {e.get('subject')}\n\n{body}")


def _clean_date(value) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    m = re.match(r"^\d{4}-\d{2}-\d{2}", value.strip())
    if not m:
        return None
    try:
        datetime.strptime(m.group(0), "%Y-%m-%d")
        return m.group(0)
    except ValueError:
        return None


def normalize_analysis(raw: dict) -> dict:
    """Validate / coerce one object coming back from the LLM."""
    priority = str(raw.get("priority", "")).strip().capitalize()
    if priority not in PRIORITIES:
        priority = "Medium"
    category = str(raw.get("category", "")).strip().capitalize()
    category = next((c for c in CATEGORIES if c.lower() == category.lower()), "Other")
    deadlines = []
    for d in raw.get("deadlines") or []:
        if isinstance(d, dict) and d.get("task"):
            conf = str(d.get("confidence", "medium")).lower()
            deadlines.append({
                "task": str(d["task"]).strip()[:200],
                "due_date": _clean_date(d.get("due_date")),
                "confidence": conf if conf in ("high", "medium", "low") else "medium",
            })
    return {
        "priority": priority,
        "priority_reason": str(raw.get("priority_reason") or "No explanation returned.").strip(),
        "category": category,
        "summary": str(raw.get("summary") or "").strip(),
        "action_required": bool(raw.get("action_required", False)),
        "deadlines": deadlines,
    }


# ───────────────────────── heuristic fallback ─────────────────────────
_URGENT = re.compile(r"\b(urgent|asap|immediately|deadline|due|tomorrow|today|final notice|interview|offer|overdue|action required|expires?)\b", re.I)
_PROMO = re.compile(r"\b(sale|% off|discount|newsletter|unsubscribe|deal|coupon|offer ends|limited time|webinar|digest)\b", re.I)
_SECURITY = re.compile(r"\b(password|login|sign-in|verify your|security alert|suspended|otp)\b", re.I)
_MONEY = re.compile(r"\b(invoice|payment|statement|credit card|bank|transaction|bill)\b", re.I)


def heuristic_analysis(e: dict) -> dict:
    text = f"{e.get('subject', '')} {e.get('body', '')}"
    if _PROMO.search(text):
        prio, reason, cat = "Low", "Looks promotional / newsletter-like (keyword heuristic, Gemini unavailable).", "Promotions"
    elif _URGENT.search(text):
        prio, reason, cat = "High", "Contains urgency or deadline words (keyword heuristic, Gemini unavailable).", "Other"
    else:
        prio, reason, cat = "Medium", "No strong signals found (keyword heuristic, Gemini unavailable).", "Other"
    if _SECURITY.search(text):
        cat = "Security"
    elif _MONEY.search(text):
        cat = "Finance"
    sentences = re.split(r"(?<=[.!?])\s+", (e.get("body") or "").strip())
    return {"priority": prio, "priority_reason": reason, "category": cat,
            "summary": " ".join(sentences[:2])[:300], "action_required": prio == "High", "deadlines": []}


# ───────────────────────── LLM analysis ─────────────────────────
def _analyze_batch_llm(batch: list[dict]) -> dict[int, dict]:
    prompt = (f"{_context_block()}\n\n{OUTPUT_SPEC}\n\nEMAILS TO ANALYSE ({len(batch)}):\n\n"
              + "\n\n".join(_format_email(e) for e in batch))
    data = generate_json(prompt, system=SYSTEM_PROMPT, temperature=0.1, throttle=True)
    if isinstance(data, dict):  # model sometimes wraps the list
        data = data.get("emails") or data.get("results") or [data]
    results: dict[int, dict] = {}
    for item in data:
        if isinstance(item, dict) and "id" in item:
            try:
                results[int(item["id"])] = normalize_analysis(item)
            except (ValueError, TypeError):
                continue
    return results


def iter_analysis(emails: list[dict], use_llm: bool = True):
    """Yields (batch_results, done, total) after every batch so callers can save progress incrementally.
    batch_results = [(email, analysis, method)] with method 'gemini' or 'heuristic'."""
    llm_ok = use_llm and llm_available()
    size = settings.ANALYSIS_BATCH_SIZE
    for i in range(0, len(emails), size):
        batch = emails[i:i + size]
        results: dict[int, dict] = {}
        if llm_ok:
            try:
                results = _analyze_batch_llm(batch)
                for e in [e for e in batch if e["id"] not in results]:  # retry individually what the model skipped
                    results.update(_analyze_batch_llm([e]))
            except LLMError as exc:
                log.warning("Gemini analysis failed for a batch (%s). Using heuristics for what is missing.", exc)
                if "quota" in str(exc).lower() or "rate limit" in str(exc).lower():
                    llm_ok = False  # stop hammering the API once the quota is gone
        out = [(e, results[e["id"]], "gemini") if e["id"] in results else (e, heuristic_analysis(e), "heuristic")
               for e in batch]
        yield out, min(i + size, len(emails)), len(emails)


def analyze_emails(emails: list[dict], on_progress: Optional[Callable[[int, int], None]] = None,
                   use_llm: bool = True) -> list[tuple[dict, dict, str]]:
    all_results: list[tuple[dict, dict, str]] = []
    for batch_results, done, total in iter_analysis(emails, use_llm=use_llm):
        all_results.extend(batch_results)
        if on_progress:
            on_progress(done, total)
    return all_results
