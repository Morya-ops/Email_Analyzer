"""Fetch -> analyse -> index -> alert for your real mailbox, from the command line (same as the Sync button).

    python scripts/sync_mailbox.py              # newest FETCH_LIMIT emails
    python scripts/sync_mailbox.py --limit 30
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, pipeline  # noqa: E402
from app.config import settings  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--no-alerts", action="store_true")
    args = ap.parse_args()
    if not settings.imap_configured:
        sys.exit("Set IMAP_USER and IMAP_PASSWORD in .env first (see README).")
    db.init_db()
    if args.limit:
        settings.FETCH_LIMIT = args.limit
    print(pipeline.process(sync=True, send_alerts=not args.no_alerts))
