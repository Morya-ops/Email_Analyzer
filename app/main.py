"""FastAPI backend.   Run:  uvicorn app.main:app --port 8000   (interactive API docs at /docs)

No authentication on purpose: this is a single-user local demo tied to the one mailbox configured in .env.
"""
import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import alerts, db, email_client, pipeline, rag, replies
from .config import settings
from .llm import LLMError, embedding_backend

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")

# ───────────────────────── background job (one at a time) ─────────────────────────
JOB: dict = {"state": "idle", "kind": None, "step": "", "log": [], "result": None, "error": None,
             "started": None, "finished": None}
_job_lock = threading.Lock()


def start_job(kind: str, fn) -> bool:
    """Run fn(progress) in a thread. Returns False if another job is already running."""
    with _job_lock:
        if JOB["state"] == "running":
            return False
        JOB.update(state="running", kind=kind, step="Starting…", log=[], result=None, error=None,
                   started=time.time(), finished=None)

    def progress(msg: str) -> None:
        JOB["step"] = msg
        JOB["log"] = (JOB["log"] + [msg])[-40:]

    def runner() -> None:
        try:
            result = fn(progress)
            JOB.update(state="done", result=result, finished=time.time())
        except Exception as exc:  # surfaced to the UI instead of crashing the thread silently
            log.exception("Job %s failed", kind)
            JOB.update(state="error", error=str(exc), finished=time.time())

    threading.Thread(target=runner, daemon=True, name=f"job-{kind}").start()
    return True


def _auto_sync_loop() -> None:
    while True:
        time.sleep(settings.AUTO_SYNC_MINUTES * 60)
        start_job("auto-sync", lambda p: pipeline.process(sync=True, send_alerts=True, progress=p))


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    if settings.AUTO_SYNC_MINUTES > 0 and settings.imap_configured:
        threading.Thread(target=_auto_sync_loop, daemon=True, name="auto-sync").start()
        log.info("Auto-sync every %s min", settings.AUTO_SYNC_MINUTES)
    yield


app = FastAPI(title="Email Analyser API", version="1.0", lifespan=lifespan)


@app.exception_handler(LLMError)
async def _llm_error(_, exc: LLMError):
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(email_client.MailboxError)
async def _mail_error(_, exc: email_client.MailboxError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# ───────────────────────── schemas ─────────────────────────
class ChatRequest(BaseModel):
    question: str


class ReplyRequest(BaseModel):
    instructions: Optional[str] = None


class DoneRequest(BaseModel):
    done: bool = True


class DemoRequest(BaseModel):
    use_gemini: bool = False      # False = instant precomputed analysis, True = analyse the demo emails with Gemini
    send_alerts: bool = True
    reset: bool = True


# ───────────────────────── status ─────────────────────────
@app.get("/health")
def health():
    return {
        "status": "ok",
        "llm_configured": settings.llm_configured,
        "gemini_model": settings.GEMINI_MODEL,
        "embedding_backend": embedding_backend(),
        "imap_configured": settings.imap_configured,
        "imap_user": settings.IMAP_USER or None,
        "telegram_configured": settings.telegram_configured,
    }


@app.get("/stats")
def stats():
    return db.stats()


@app.get("/job")
def job_status():
    return JOB


# ───────────────────────── emails ─────────────────────────
@app.get("/emails")
def list_emails(priority: Optional[list[str]] = Query(None), category: Optional[str] = None,
                search: Optional[str] = None, sort: str = "priority", limit: int = 500, offset: int = 0):
    return db.list_emails(priority=priority, category=category, search=search, sort=sort, limit=limit, offset=offset)


@app.get("/emails/{email_id}")
def get_email(email_id: int):
    email = db.get_email(email_id)
    if not email:
        raise HTTPException(404, "Email not found")
    return email


@app.post("/emails/{email_id}/replies")
def make_replies(email_id: int, req: ReplyRequest):
    try:
        return replies.generate_replies(email_id, req.instructions)
    except KeyError:
        raise HTTPException(404, "Email not found")


# ───────────────────────── chat (RAG) ─────────────────────────
@app.post("/chat")
def chat(req: ChatRequest):
    if not req.question.strip():
        raise HTTPException(400, "Question is empty")
    if db.stats()["total"] == 0:
        return {"answer": "The inbox is empty. Load the demo inbox or sync your mailbox first.", "sources": [], "mode": "none", "filters": {}}
    return rag.answer_question(req.question.strip())


# ───────────────────────── deadlines ─────────────────────────
@app.get("/deadlines")
def deadlines(include_done: bool = False):
    return db.list_deadlines(include_done=include_done)


@app.post("/deadlines/{deadline_id}/done")
def mark_done(deadline_id: int, req: DoneRequest):
    if not db.set_deadline_done(deadline_id, req.done):
        raise HTTPException(404, "Deadline not found")
    return {"ok": True}


# ───────────────────────── alerts ─────────────────────────
@app.get("/alerts")
def get_alerts():
    return db.list_alerts()


@app.post("/alerts/test")
def test_alert():
    return alerts.send_test_alert()


# ───────────────────────── actions (run as background jobs) ─────────────────────────
@app.post("/imap/test")
def imap_test():
    return email_client.check_connection()


@app.post("/sync")
def sync():
    if not settings.imap_configured:
        raise HTTPException(400, "Mailbox not configured. Set IMAP_USER and IMAP_PASSWORD in .env (see README), or load the demo inbox.")
    if not start_job("sync", lambda p: pipeline.process(sync=True, send_alerts=True, progress=p)):
        raise HTTPException(409, "Another job is already running")
    return {"started": True}


@app.post("/analyze")
def analyze():
    if not start_job("analyze", lambda p: pipeline.process(sync=False, send_alerts=True, progress=p)):
        raise HTTPException(409, "Another job is already running")
    return {"started": True}


@app.post("/demo/load")
def demo_load(req: DemoRequest):
    if not start_job("demo", lambda p: pipeline.load_demo(req.use_gemini, req.send_alerts, req.reset, p)):
        raise HTTPException(409, "Another job is already running")
    return {"started": True}


@app.post("/reset")
def reset():
    if JOB["state"] == "running":
        raise HTTPException(409, "A job is running")
    db.reset_all()
    rag.reset()
    return {"ok": True}
