"""Central configuration. Everything comes from environment variables / the .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value is None:
        return default
    # allow inline comments in .env.example style:  KEY=value   # comment
    return value.split("  #")[0].strip()


class Settings:
    def __init__(self) -> None:
        # Gemini
        self.GEMINI_API_KEY = _str("GEMINI_API_KEY")
        self.GEMINI_MODEL = _str("GEMINI_MODEL", "gemini-3.5-flash-lite")
        self.EMBED_MODEL = _str("EMBED_MODEL", "gemini-embedding-001")
        self.EMBED_BACKEND = _str("EMBED_BACKEND", "auto").lower()  # auto | gemini | local
        self.LLM_MIN_INTERVAL_SEC = _float("LLM_MIN_INTERVAL_SEC", 6.0)
        self.ANALYSIS_BATCH_SIZE = max(1, _int("ANALYSIS_BATCH_SIZE", 5))
        self.ANALYSIS_BODY_CHARS = _int("ANALYSIS_BODY_CHARS", 1500)

        # IMAP
        self.IMAP_HOST = _str("IMAP_HOST", "imap.gmail.com")
        self.IMAP_PORT = _int("IMAP_PORT", 993)
        self.IMAP_USER = _str("IMAP_USER")
        self.IMAP_PASSWORD = _str("IMAP_PASSWORD").replace(" ", "")  # app passwords are shown with spaces
        self.IMAP_FOLDER = _str("IMAP_FOLDER", "INBOX")
        self.FETCH_LIMIT = _int("FETCH_LIMIT", 100)
        self.MAX_BODY_CHARS = _int("MAX_BODY_CHARS", 4000)

        # Alerts
        self.TELEGRAM_BOT_TOKEN = _str("TELEGRAM_BOT_TOKEN")
        self.TELEGRAM_CHAT_ID = _str("TELEGRAM_CHAT_ID")
        self.ALERT_DEADLINE_HOURS = _int("ALERT_DEADLINE_HOURS", 48)
        self.MAX_ALERTS_PER_RUN = _int("MAX_ALERTS_PER_RUN", 10)
        self.AUTO_SYNC_MINUTES = _int("AUTO_SYNC_MINUTES", 0)  # 0 = manual sync only

        # Personalisation
        self.USER_CONTEXT = _str(
            "USER_CONTEXT",
            "I am a final-year engineering student. Emails from professors, the exam cell, the placement "
            "cell, recruiters, my internship manager, banks and security alerts matter. "
            "Promotions and newsletters do not.",
        )
        self.VIP_SENDERS = [s.strip().lower() for s in _str("VIP_SENDERS").split(",") if s.strip()]

        # Storage
        self.DB_PATH = Path(_str("DB_PATH", str(BASE_DIR / "data" / "emails.db")))
        self.CHROMA_DIR = Path(_str("CHROMA_DIR", str(BASE_DIR / "data" / "chroma")))

    # convenience flags -------------------------------------------------
    @property
    def llm_configured(self) -> bool:
        return bool(self.GEMINI_API_KEY)

    @property
    def imap_configured(self) -> bool:
        return bool(self.IMAP_USER and self.IMAP_PASSWORD)

    @property
    def telegram_configured(self) -> bool:
        return bool(self.TELEGRAM_BOT_TOKEN and self.TELEGRAM_CHAT_ID)


settings = Settings()
