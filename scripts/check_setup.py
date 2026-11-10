"""Checks every external dependency one by one and tells you exactly what to fix.

    python scripts/check_setup.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import alerts, email_client  # noqa: E402
from app.config import settings  # noqa: E402
from app.llm import LLMError, embed_texts, embedding_backend, generate_text  # noqa: E402


def step(name, fn):
    try:
        print(f"✅ {name}: {fn()}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"❌ {name}: {exc}")
        return False


def gemini_text():
    if not settings.llm_configured:
        raise LLMError("GEMINI_API_KEY missing in .env")
    return generate_text("Reply with exactly: OK", temperature=0).strip()[:40]


def gemini_embed():
    if embedding_backend() == "local":
        return "using the local fallback embedder (no API call)"
    return f"vector of {len(embed_texts(['hello world'])[0])} dimensions from {settings.EMBED_MODEL}"


def imap():
    if not settings.imap_configured:
        return "skipped (IMAP_USER / IMAP_PASSWORD not set – you can still use the demo inbox)"
    info = email_client.check_connection()
    return f"logged in as {info['user']}, folder {info['folder']} has {info['messages']} messages"


def telegram():
    if not settings.telegram_configured:
        return "skipped (not configured – alerts will only appear inside the app)"
    ok, info = alerts.send_telegram("✅ Email Analyser setup check")
    if not ok:
        raise RuntimeError(info)
    return "test message sent to your Telegram chat"


if __name__ == "__main__":
    results = [step("Gemini text generation", gemini_text), step("Embeddings", gemini_embed),
               step("Mailbox (IMAP)", imap), step("Telegram alerts", telegram)]
    sys.exit(0 if all(results) else 1)
