"""Load the synthetic demo inbox from the command line (same thing as the sidebar button).

    python scripts/seed_demo.py                 # instant: precomputed analysis, no Gemini calls
    python scripts/seed_demo.py --gemini        # let Gemini analyse all demo emails for real
    python scripts/seed_demo.py --no-alerts     # do not fire alerts
"""
import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, pipeline  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--gemini", action="store_true", help="analyse demo emails with Gemini instead of precomputed labels")
    ap.add_argument("--no-alerts", action="store_true")
    ap.add_argument("--keep", action="store_true", help="do not wipe existing data first")
    args = ap.parse_args()
    db.init_db()
    result = pipeline.load_demo(use_gemini=args.gemini, send_alerts=not args.no_alerts, reset=not args.keep)
    print(result)
