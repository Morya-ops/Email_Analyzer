"""Read emails from any mailbox over IMAP (works with Gmail, Outlook, Yahoo... no OAuth needed).

Gmail setup: enable IMAP in Gmail settings + create an App Password (needs 2-Step Verification).
The connection is read-only and uses BODY.PEEK so emails are NOT marked as read.
"""
import imaplib
import re
from datetime import timezone
from email import message_from_bytes, policy
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from typing import Optional

from .config import settings


class MailboxError(Exception):
    pass


# ───────────────────────── text cleaning ─────────────────────────
class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self._skip += 1
        if tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _HTMLText()
    parser.feed(html)
    return "".join(parser.parts)


_REPLY_MARKERS = [
    re.compile(r"^\s*On .{5,200}wrote:\s*$", re.I),
    re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}", re.I),
    re.compile(r"^\s*From:\s.*@.*", re.I),        # forwarded / quoted headers
    re.compile(r"^_{5,}\s*$"),
]
_SIGNATURE_MARKERS = [re.compile(r"^--\s*$"), re.compile(r"^Sent from my (iPhone|iPad|Android|Samsung)", re.I)]


def clean_body(text: str, max_chars: Optional[int] = None) -> str:
    """Drop quoted replies, signatures and excess whitespace so the LLM only sees what is new."""
    max_chars = max_chars or settings.MAX_BODY_CHARS
    kept: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if any(p.match(line) for p in _REPLY_MARKERS + _SIGNATURE_MARKERS) and len(kept) > 2:
            break
        if line.lstrip().startswith(">"):
            continue
        kept.append(line.rstrip())
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(kept)).strip()
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out[:max_chars]


def normalize_subject(subject: str) -> str:
    s = subject or ""
    while True:
        new = re.sub(r"^\s*(re|fwd?|fw)\s*:\s*", "", s, flags=re.I)
        if new == s:
            break
        s = new
    return re.sub(r"\s+", " ", s).strip().lower()


# ───────────────────────── parsing ─────────────────────────
def parse_message(raw: bytes, fallback_id: str = "") -> dict:
    msg = message_from_bytes(raw, policy=policy.default)
    name, addr = parseaddr(str(msg.get("From", "")))
    subject = str(msg.get("Subject", "") or "(no subject)")
    try:
        dt = parsedate_to_datetime(str(msg.get("Date")))
        dt = dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        from datetime import datetime
        dt = datetime.now(timezone.utc)

    body = ""
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is not None:
        try:
            content = part.get_content()
        except Exception:
            content = ""
        body = html_to_text(content) if part.get_content_type() == "text/html" else content
    body = clean_body(body)

    message_id = str(msg.get("Message-ID", "")).strip() or f"imap-{fallback_id}"
    return {
        "message_id": message_id,
        "thread_key": normalize_subject(subject),
        "sender_name": name or addr.split("@")[0],
        "sender_email": addr.lower(),
        "subject": subject,
        "body": body or "(empty message)",
        "received_at": dt.replace(microsecond=0).isoformat(),
        "source": "imap",
    }


# ───────────────────────── IMAP ─────────────────────────
def _connect() -> imaplib.IMAP4_SSL:
    if not settings.imap_configured:
        raise MailboxError("IMAP_USER / IMAP_PASSWORD are not set in .env")
    try:
        conn = imaplib.IMAP4_SSL(settings.IMAP_HOST, settings.IMAP_PORT)
        conn.login(settings.IMAP_USER, settings.IMAP_PASSWORD)
        return conn
    except imaplib.IMAP4.error as exc:
        raise MailboxError(
            f"Login failed ({exc}). For Gmail use an App Password (not your normal password) and make sure IMAP is enabled."
        ) from exc
    except OSError as exc:
        raise MailboxError(f"Could not reach {settings.IMAP_HOST}:{settings.IMAP_PORT} ({exc})") from exc


def check_connection() -> dict:
    conn = _connect()
    try:
        typ, data = conn.select(settings.IMAP_FOLDER, readonly=True)
        count = int(data[0]) if typ == "OK" and data and data[0] else 0
        return {"ok": True, "folder": settings.IMAP_FOLDER, "messages": count, "user": settings.IMAP_USER}
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def fetch_emails(limit: Optional[int] = None, since_uid: Optional[int] = None) -> tuple[list[dict], int]:
    """Fetch the newest `limit` emails (or those with UID > since_uid). Returns (emails, highest_uid_seen)."""
    limit = limit or settings.FETCH_LIMIT
    conn = _connect()
    emails: list[dict] = []
    highest = since_uid or 0
    try:
        typ, _ = conn.select(settings.IMAP_FOLDER, readonly=True)
        if typ != "OK":
            raise MailboxError(f"Could not open folder '{settings.IMAP_FOLDER}'")
        typ, data = conn.uid("search", None, "ALL")
        uids = [int(u) for u in (data[0] or b"").split()]
        if since_uid:
            uids = [u for u in uids if u > since_uid]
        uids = uids[-limit:]
        for uid in uids:
            typ, msg_data = conn.uid("fetch", str(uid), "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not isinstance(msg_data[0], tuple):
                continue
            emails.append(parse_message(msg_data[0][1], fallback_id=str(uid)))
            highest = max(highest, uid)
    finally:
        try:
            conn.logout()
        except Exception:
            pass
    return emails, highest
