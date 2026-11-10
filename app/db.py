"""SQLite storage layer (plain sqlite3, no ORM)."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS emails (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id   TEXT UNIQUE NOT NULL,
    thread_key   TEXT,
    sender_name  TEXT,
    sender_email TEXT,
    subject      TEXT,
    body         TEXT,
    received_at  TEXT NOT NULL,
    source       TEXT DEFAULT 'imap',
    indexed      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_emails_received ON emails(received_at);
CREATE INDEX IF NOT EXISTS idx_emails_sender   ON emails(sender_email);

CREATE TABLE IF NOT EXISTS analyses (
    email_id        INTEGER PRIMARY KEY REFERENCES emails(id) ON DELETE CASCADE,
    priority        TEXT,
    priority_reason TEXT,
    category        TEXT,
    summary         TEXT,
    action_required INTEGER DEFAULT 0,
    method          TEXT,
    alerted         INTEGER DEFAULT 0,
    analyzed_at     TEXT
);

CREATE TABLE IF NOT EXISTS deadlines (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id   INTEGER NOT NULL REFERENCES emails(id) ON DELETE CASCADE,
    task       TEXT,
    due_date   TEXT,
    confidence TEXT,
    done       INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS alerts (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email_id   INTEGER,
    kind       TEXT,
    message    TEXT,
    channel    TEXT,
    created_at TEXT
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

PRIORITY_RANK_SQL = "CASE a.priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 WHEN 'Low' THEN 2 ELSE 3 END"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def get_conn():
    settings.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def _rows(cursor) -> list[dict]:
    return [dict(r) for r in cursor.fetchall()]


# ───────────────────────── emails ─────────────────────────
def insert_email(e: dict) -> Optional[int]:
    """Insert an email. Returns the new id, or None if message_id already exists."""
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT OR IGNORE INTO emails
               (message_id, thread_key, sender_name, sender_email, subject, body, received_at, source)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                e["message_id"], e.get("thread_key"), e.get("sender_name"), (e.get("sender_email") or "").lower(),
                e.get("subject"), e.get("body"), e["received_at"], e.get("source", "imap"),
            ),
        )
        return cur.lastrowid if cur.rowcount else None


def get_email(email_id: int) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute(
            """SELECT e.*, a.priority, a.priority_reason, a.category, a.summary, a.action_required,
                      a.method, a.alerted, a.analyzed_at
               FROM emails e LEFT JOIN analyses a ON a.email_id = e.id WHERE e.id = ?""",
            (email_id,),
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["deadlines"] = _rows(conn.execute("SELECT * FROM deadlines WHERE email_id=? ORDER BY due_date", (email_id,)))
        return data


def list_emails(
    priority: Optional[list[str]] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
    sort: str = "priority",
    limit: int = 500,
    offset: int = 0,
) -> list[dict]:
    where, params = ["1=1"], []
    if priority:
        where.append(f"a.priority IN ({','.join('?' * len(priority))})")
        params += priority
    if category and category != "All":
        where.append("a.category = ?")
        params.append(category)
    if search:
        like = f"%{search.lower()}%"
        where.append("(lower(e.subject) LIKE ? OR lower(e.sender_name) LIKE ? OR lower(e.sender_email) LIKE ? OR lower(a.summary) LIKE ?)")
        params += [like] * 4
    order = f"{PRIORITY_RANK_SQL}, e.received_at DESC" if sort == "priority" else "e.received_at DESC"
    sql = f"""SELECT e.id, e.message_id, e.sender_name, e.sender_email, e.subject, e.received_at, e.source,
                     substr(e.body, 1, 240) AS snippet,
                     a.priority, a.priority_reason, a.category, a.summary, a.action_required, a.method
              FROM emails e LEFT JOIN analyses a ON a.email_id = e.id
              WHERE {' AND '.join(where)} ORDER BY {order} LIMIT ? OFFSET ?"""
    with get_conn() as conn:
        emails = _rows(conn.execute(sql, params + [limit, offset]))
        if emails:
            ids = [e["id"] for e in emails]
            dl = _rows(conn.execute(
                f"SELECT * FROM deadlines WHERE email_id IN ({','.join('?' * len(ids))}) AND done=0 ORDER BY due_date", ids))
            by_email: dict[int, list] = {}
            for d in dl:
                by_email.setdefault(d["email_id"], []).append(d)
            for e in emails:
                e["deadlines"] = by_email.get(e["id"], [])
        return emails


def get_unanalyzed(limit: Optional[int] = None) -> list[dict]:
    sql = """SELECT e.* FROM emails e LEFT JOIN analyses a ON a.email_id = e.id
             WHERE a.email_id IS NULL ORDER BY e.received_at DESC"""
    if limit:
        sql += f" LIMIT {int(limit)}"
    with get_conn() as conn:
        return _rows(conn.execute(sql))


def get_unindexed(limit: Optional[int] = None) -> list[dict]:
    sql = """SELECT e.*, a.category FROM emails e LEFT JOIN analyses a ON a.email_id = e.id
             WHERE e.indexed = 0 ORDER BY e.received_at DESC"""
    if limit:
        sql += f" LIMIT {int(limit)}"
    with get_conn() as conn:
        return _rows(conn.execute(sql))


def mark_indexed(ids: Iterable[int]) -> None:
    ids = list(ids)
    if not ids:
        return
    with get_conn() as conn:
        conn.execute(f"UPDATE emails SET indexed=1 WHERE id IN ({','.join('?' * len(ids))})", ids)


def all_emails_basic() -> list[dict]:
    with get_conn() as conn:
        return _rows(conn.execute(
            """SELECT e.id, e.sender_name, e.sender_email, e.subject, e.body, e.received_at, a.category
               FROM emails e LEFT JOIN analyses a ON a.email_id = e.id"""))


def emails_by_sender(sender_email: str, before: str, exclude_id: int, limit: int = 5) -> list[dict]:
    with get_conn() as conn:
        return _rows(conn.execute(
            """SELECT * FROM emails WHERE sender_email=? AND id<>? AND received_at<=?
               ORDER BY received_at DESC LIMIT ?""",
            (sender_email, exclude_id, before, limit)))


def emails_by_thread(thread_key: str, exclude_id: int, limit: int = 5) -> list[dict]:
    if not thread_key:
        return []
    with get_conn() as conn:
        return _rows(conn.execute(
            "SELECT * FROM emails WHERE thread_key=? AND id<>? ORDER BY received_at DESC LIMIT ?",
            (thread_key, exclude_id, limit)))


def get_emails_by_ids(ids: list[int]) -> list[dict]:
    if not ids:
        return []
    with get_conn() as conn:
        return _rows(conn.execute(
            f"SELECT id, sender_name, sender_email, subject, body, received_at FROM emails WHERE id IN ({','.join('?' * len(ids))})", ids))


# ───────────────────────── analyses ─────────────────────────
def save_analysis(email_id: int, a: dict, method: str, alerted: int = 0) -> None:
    with get_conn() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO analyses
               (email_id, priority, priority_reason, category, summary, action_required, method, alerted, analyzed_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (email_id, a["priority"], a["priority_reason"], a["category"], a["summary"],
             1 if a.get("action_required") else 0, method, alerted, now_iso()),
        )
        conn.execute("DELETE FROM deadlines WHERE email_id=?", (email_id,))
        for d in a.get("deadlines", []):
            conn.execute(
                "INSERT INTO deadlines (email_id, task, due_date, confidence) VALUES (?,?,?,?)",
                (email_id, d.get("task"), d.get("due_date"), d.get("confidence", "medium")),
            )


# ───────────────────────── deadlines ─────────────────────────
def list_deadlines(include_done: bool = False) -> list[dict]:
    sql = """SELECT d.id, d.email_id, d.task, d.due_date, d.confidence, d.done,
                    e.subject, e.sender_name, a.priority
             FROM deadlines d JOIN emails e ON e.id = d.email_id
             LEFT JOIN analyses a ON a.email_id = e.id"""
    if not include_done:
        sql += " WHERE d.done = 0"
    sql += " ORDER BY (d.due_date IS NULL), d.due_date, d.id"
    with get_conn() as conn:
        return _rows(conn.execute(sql))


def set_deadline_done(deadline_id: int, done: bool = True) -> bool:
    with get_conn() as conn:
        cur = conn.execute("UPDATE deadlines SET done=? WHERE id=?", (1 if done else 0, deadline_id))
        return cur.rowcount > 0


# ───────────────────────── alerts ─────────────────────────
def pending_alert_candidates(deadline_cutoff: str, today: str) -> list[dict]:
    """High-priority emails or emails with a deadline in [today, cutoff] that were not alerted yet."""
    sql = """SELECT e.id, e.sender_name, e.subject, e.received_at, a.priority, a.priority_reason, a.summary,
                    (SELECT group_concat(d.task || ' (' || d.due_date || ')', '; ')
                       FROM deadlines d WHERE d.email_id = e.id AND d.done = 0 AND d.due_date IS NOT NULL
                        AND d.due_date >= ? AND d.due_date <= ?) AS soon_deadlines
             FROM emails e JOIN analyses a ON a.email_id = e.id
             WHERE a.alerted = 0
               AND (a.priority = 'High' OR EXISTS (
                     SELECT 1 FROM deadlines d WHERE d.email_id = e.id AND d.done = 0
                       AND d.due_date IS NOT NULL AND d.due_date >= ? AND d.due_date <= ?))
             ORDER BY CASE a.priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END, e.received_at DESC"""
    with get_conn() as conn:
        return _rows(conn.execute(sql, (today, deadline_cutoff, today, deadline_cutoff)))


def mark_alerted(email_ids: list[int]) -> None:
    if not email_ids:
        return
    with get_conn() as conn:
        conn.execute(f"UPDATE analyses SET alerted=1 WHERE email_id IN ({','.join('?' * len(email_ids))})", email_ids)


def add_alert(email_id: Optional[int], kind: str, message: str, channel: str) -> None:
    with get_conn() as conn:
        conn.execute("INSERT INTO alerts (email_id, kind, message, channel, created_at) VALUES (?,?,?,?,?)",
                     (email_id, kind, message, channel, now_iso()))


def list_alerts(limit: int = 100) -> list[dict]:
    with get_conn() as conn:
        return _rows(conn.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT ?", (limit,)))


# ───────────────────────── meta / stats / reset ─────────────────────────
def get_meta(key: str, default: Any = None) -> Any:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default


def set_meta(key: str, value: Any) -> None:
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, json.dumps(value)))


def stats() -> dict:
    with get_conn() as conn:
        total = conn.execute("SELECT COUNT(*) c FROM emails").fetchone()["c"]
        analyzed = conn.execute("SELECT COUNT(*) c FROM analyses").fetchone()["c"]
        indexed = conn.execute("SELECT COUNT(*) c FROM emails WHERE indexed=1").fetchone()["c"]
        by_priority = {r["priority"]: r["c"] for r in conn.execute(
            "SELECT priority, COUNT(*) c FROM analyses GROUP BY priority")}
        by_category = {r["category"]: r["c"] for r in conn.execute(
            "SELECT category, COUNT(*) c FROM analyses GROUP BY category ORDER BY c DESC")}
        open_deadlines = conn.execute("SELECT COUNT(*) c FROM deadlines WHERE done=0").fetchone()["c"]
        return {
            "total": total, "analyzed": analyzed, "pending_analysis": total - analyzed, "indexed": indexed,
            "by_priority": by_priority, "by_category": by_category, "open_deadlines": open_deadlines,
        }


def reset_all() -> None:
    with get_conn() as conn:
        for table in ("alerts", "deadlines", "analyses", "emails", "meta"):
            conn.execute(f"DELETE FROM {table}")
