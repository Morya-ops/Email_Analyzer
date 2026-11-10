import os
import sys
import tempfile
from pathlib import Path

# configure an isolated environment BEFORE the app is imported
_tmp = tempfile.mkdtemp(prefix="email-analyser-test-")
os.environ.update({
    "DB_PATH": str(Path(_tmp) / "test.db"),
    "CHROMA_DIR": str(Path(_tmp) / "chroma"),
    "GEMINI_API_KEY": "",
    "EMBED_BACKEND": "local",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_CHAT_ID": "",
    "LLM_MIN_INTERVAL_SEC": "0",
    "ANALYSIS_BATCH_SIZE": "5",
})
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from app import db, rag  # noqa: E402


@pytest.fixture(autouse=True)
def clean_state():
    db.init_db()
    db.reset_all()
    rag.reset()
    yield
