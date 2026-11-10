"""Context-aware reply drafting: earlier emails from the same sender / thread (+ similar emails via RAG)
are given to Gemini so the drafts are consistent with the conversation so far."""
import logging
from typing import Optional

from . import db, rag
from .config import settings
from .llm import LLMError, generate_json

log = logging.getLogger("replies")

SYSTEM = """You write email replies on behalf of the mailbox owner.
Return ONLY JSON: {"options": [{"tone": "Formal", "subject": "...", "body": "..."},
{"tone": "Friendly", "subject": "...", "body": "..."}, {"tone": "Brief", "subject": "...", "body": "..."}]}
Rules:
- Exactly three options in that order: Formal, Friendly, Brief (Brief = 1-3 sentences).
- Be consistent with the earlier conversation context. Never invent facts, dates, attachments or commitments that are
  not supported by the emails or the owner's extra instructions. If something is unknown, ask or leave a [placeholder].
- Address the sender naturally, answer what was asked, and end with a sign-off but do not invent a surname.
- No markdown. Plain email text with line breaks as \\n."""


def _short(e: dict, n: int = 500) -> str:
    return f"[{e['received_at'][:10]}] From {e['sender_name']}: {e['subject']}\n{(e['body'] or '')[:n]}"


def gather_context(email: dict, max_items: int = 5) -> list[dict]:
    seen = {email["id"]}
    ctx: list[dict] = []
    for e in db.emails_by_thread(email.get("thread_key"), email["id"], 5) + \
            db.emails_by_sender(email["sender_email"], email["received_at"], email["id"], 5):
        if e["id"] not in seen:
            seen.add(e["id"])
            ctx.append(e)
    if len(ctx) < max_items:  # top up with semantically similar emails
        for h in rag.similar_to(f"{email['subject']}\n{email['body'][:600]}", email["id"], k=2):
            if h["email_id"] not in seen:
                found = db.get_emails_by_ids([h["email_id"]])
                if found:
                    seen.add(h["email_id"])
                    ctx.append(found[0])
    return sorted(ctx, key=lambda e: e["received_at"])[-max_items:]


def generate_replies(email_id: int, instructions: Optional[str] = None) -> dict:
    email = db.get_email(email_id)
    if not email:
        raise KeyError(email_id)
    context = gather_context(email)
    ctx_text = "\n\n".join(_short(e) for e in context) or "(no earlier emails with this sender)"
    prompt = (
        f"MAILBOX OWNER: {settings.USER_CONTEXT}\n\n"
        f"EARLIER CONTEXT (oldest first):\n{ctx_text}\n\n"
        f"EMAIL TO REPLY TO:\n[{email['received_at'][:10]}] From {email['sender_name']} <{email['sender_email']}>\n"
        f"Subject: {email['subject']}\n\n{(email['body'] or '')[:2500]}\n\n"
        f"EXTRA INSTRUCTIONS FROM THE OWNER: {instructions.strip() if instructions and instructions.strip() else '(none)'}"
    )
    data = generate_json(prompt, system=SYSTEM, temperature=0.5, throttle=False)
    options = data.get("options") if isinstance(data, dict) else data
    if not isinstance(options, list) or not options:
        raise LLMError("Gemini returned no reply options.")
    clean = [{"tone": str(o.get("tone", "Option")), "subject": str(o.get("subject") or f"Re: {email['subject']}"),
              "body": str(o.get("body", "")).strip()} for o in options if isinstance(o, dict)]
    return {"email_id": email_id, "options": clean,
            "context_used": [{"id": e["id"], "subject": e["subject"], "received_at": e["received_at"]} for e in context]}
