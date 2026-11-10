"""RAG over the mailbox: index emails in Chroma, retrieve relevant ones, answer questions with citations.

Embeddings come from Gemini (free) or a local hashing fallback. If indexing/retrieval is impossible the
chat degrades to plain keyword search over SQLite, so it never hard-fails.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import db
from .config import settings
from .llm import LLMError, embed_texts, embedding_backend, generate_text, llm_available

log = logging.getLogger("rag")

_chroma_client = None


def _collection():
    global _chroma_client
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    if _chroma_client is None:
        settings.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=str(settings.CHROMA_DIR), settings=ChromaSettings(anonymized_telemetry=False))
    # one collection per embedding backend so vectors of different sizes never mix
    return _chroma_client.get_or_create_collection(
        name=f"emails_{embedding_backend()}", metadata={"hnsw:space": "cosine"})


def reset() -> None:
    global _chroma_client
    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        settings.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(settings.CHROMA_DIR), settings=ChromaSettings(anonymized_telemetry=False))
        for c in client.list_collections():
            client.delete_collection(c.name if hasattr(c, "name") else c)
        _chroma_client = client
    except Exception as exc:  # pragma: no cover
        log.warning("Could not reset Chroma: %s", exc)


# ───────────────────────── indexing ─────────────────────────
def chunk_text(text: str, size: int = 1200, overlap: int = 150) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start + size])
        start += size - overlap
    return chunks


def _to_ts(iso: str) -> int:
    try:
        return int(datetime.fromisoformat(iso).timestamp())
    except ValueError:
        return 0


def index_pending() -> int:
    """Embed all emails that are not in the vector store yet. Returns how many emails were indexed."""
    pending = db.get_unindexed()
    if not pending:
        return 0
    ids, docs, metas, email_ids = [], [], [], []
    for e in pending:
        header = f"From: {e['sender_name']} <{e['sender_email']}>\nDate: {e['received_at']}\nSubject: {e['subject']}\n\n"
        for i, chunk in enumerate(chunk_text(e["body"] or "")):
            ids.append(f"{e['id']}:{i}")
            docs.append(header + chunk)
            metas.append({"email_id": e["id"], "sender_email": e["sender_email"] or "",
                          "category": e.get("category") or "Other", "received_ts": _to_ts(e["received_at"]),
                          "subject": e["subject"] or ""})
        email_ids.append(e["id"])
    try:
        vectors = embed_texts(docs, task_type="RETRIEVAL_DOCUMENT")
    except LLMError as exc:
        log.warning("Embedding failed (%s). Chat will use keyword search until indexing succeeds.", exc)
        return 0
    col = _collection()
    for i in range(0, len(ids), 200):
        col.upsert(ids=ids[i:i + 200], documents=docs[i:i + 200], embeddings=vectors[i:i + 200], metadatas=metas[i:i + 200])
    db.mark_indexed(email_ids)
    return len(email_ids)


# ───────────────────────── query understanding (rule based, no extra LLM call) ─────────────────────────
_CATEGORY_WORDS = {
    "Academic": ["assignment", "exam", "professor", "lecture", "lab", "viva", "attendance", "syllabus", "marks"],
    "Recruitment": ["recruiter", "interview", "placement", "job offer", "hiring", "assessment", "internship offer"],
    "Finance": ["invoice", "payment", "bank", "credit card", "statement", "bill", "transaction", "scholarship"],
    "Security": ["password", "login", "phishing", "security alert", "suspicious"],
    "Promotions": ["promotion", "newsletter", "discount", "sale"],
}


def parse_filters(question: str) -> dict:
    q = question.lower()
    filters: dict = {}
    now = datetime.now(timezone.utc)
    if "yesterday" in q:
        filters["since"] = int((now - timedelta(days=2)).timestamp())
    elif "today" in q:
        filters["since"] = int((now - timedelta(days=1)).timestamp())
    elif "this week" in q or "last week" in q:
        filters["since"] = int((now - timedelta(days=7 if "this" in q else 14)).timestamp())
    elif "this month" in q or "last month" in q:
        filters["since"] = int((now - timedelta(days=31)).timestamp())
    else:
        m = re.search(r"(?:last|past)\s+(\d{1,3})\s+days?", q)
        if m:
            filters["since"] = int((now - timedelta(days=int(m.group(1)))).timestamp())
    for cat, words in _CATEGORY_WORDS.items():
        if any(w in q for w in words):
            filters["category_hint"] = cat  # used only as a soft boost, not a hard filter
            break
    # sender filter: a known sender's full name (or distinctive first+last) appears in the question
    names = {(e["sender_name"] or "").lower(): e["sender_email"] for e in db.all_emails_basic()}
    for name, addr in names.items():
        if len(name) > 4 and name in q:
            filters["sender_email"] = addr
            break
    return filters


# ───────────────────────── retrieval ─────────────────────────
def _where(filters: dict) -> Optional[dict]:
    conds = []
    if filters.get("since"):
        conds.append({"received_ts": {"$gte": filters["since"]}})
    if filters.get("sender_email"):
        conds.append({"sender_email": filters["sender_email"]})
    if not conds:
        return None
    return conds[0] if len(conds) == 1 else {"$and": conds}


def retrieve(question: str, k: int = 6, filters: Optional[dict] = None) -> list[dict]:
    """Vector search. Returns [{email_id, score, text}] with one best chunk per email."""
    filters = filters or {}
    vec = embed_texts([question], task_type="RETRIEVAL_QUERY")[0]
    col = _collection()
    if col.count() == 0:
        return []
    kwargs = {"query_embeddings": [vec], "n_results": min(k * 3, col.count()), "include": ["documents", "metadatas", "distances"]}
    where = _where(filters)
    if where:
        kwargs["where"] = where
    res = col.query(**kwargs)
    best: dict[int, dict] = {}
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        eid = int(meta["email_id"])
        score = 1 - float(dist)
        if filters.get("category_hint") and meta.get("category") == filters["category_hint"]:
            score += 0.05
        if eid not in best or score > best[eid]["score"]:
            best[eid] = {"email_id": eid, "score": score, "text": doc}
    return sorted(best.values(), key=lambda h: h["score"], reverse=True)[:k]


def keyword_retrieve(question: str, k: int = 6, filters: Optional[dict] = None) -> list[dict]:
    """Fallback when vectors are unavailable: simple token-overlap scoring."""
    filters = filters or {}
    toks = {t for t in re.findall(r"[a-z0-9]+", question.lower()) if len(t) > 2}
    scored = []
    for e in db.all_emails_basic():
        if filters.get("since") and _to_ts(e["received_at"]) < filters["since"]:
            continue
        if filters.get("sender_email") and e["sender_email"] != filters["sender_email"]:
            continue
        hay = f"{e['subject']} {e['sender_name']} {e['body']}".lower()
        score = sum(1 for t in toks if t in hay) / (len(toks) or 1)
        if score > 0:
            scored.append({"email_id": e["id"], "score": score,
                           "text": f"From: {e['sender_name']}\nDate: {e['received_at']}\nSubject: {e['subject']}\n\n{e['body']}"})
    return sorted(scored, key=lambda h: h["score"], reverse=True)[:k]


def similar_to(text: str, exclude_id: int, k: int = 2) -> list[dict]:
    try:
        hits = retrieve(text, k=k + 1)
    except Exception as exc:
        log.info("similar_to unavailable: %s", exc)
        return []
    return [h for h in hits if h["email_id"] != exclude_id][:k]


# ───────────────────────── answering ─────────────────────────
ANSWER_SYSTEM = """You answer questions about the user's mailbox using ONLY the emails provided.
- Cite every fact with the email id in square brackets, like [E12]. Cite several like [E3][E7].
- If the emails do not contain the answer, say you could not find it. Never guess.
- Dates: today is {today}. Be concise and direct; use short bullet lists for multi-item answers."""


def answer_question(question: str, k: int = 6) -> dict:
    filters = parse_filters(question)
    mode = "vector"
    try:
        hits = retrieve(question, k=k, filters=filters)
        if not hits and filters:  # filters may have been too strict; retry without them
            hits = retrieve(question, k=k)
    except Exception as exc:
        log.warning("Vector retrieval failed (%s); falling back to keyword search.", exc)
        hits, mode = [], "keyword"
    if not hits:
        hits, mode = keyword_retrieve(question, k=k, filters=filters) or keyword_retrieve(question, k=k), "keyword"
    if not hits:
        return {"answer": "I couldn't find any emails related to that question.", "sources": [], "mode": mode, "filters": filters}

    meta = {e["id"]: e for e in db.get_emails_by_ids([h["email_id"] for h in hits])}
    sources = [{"id": h["email_id"], "subject": meta[h["email_id"]]["subject"], "sender": meta[h["email_id"]]["sender_name"],
                "received_at": meta[h["email_id"]]["received_at"], "score": round(h["score"], 3)}
               for h in hits if h["email_id"] in meta]

    if not llm_available():
        return {"answer": "Gemini key not configured, so I can't write an answer. These are the most relevant emails:",
                "sources": sources, "mode": mode, "filters": filters}

    context = "\n\n".join(f"[E{h['email_id']}]\n{h['text'][:1800]}" for h in hits)
    prompt = f"EMAILS:\n{context}\n\nQUESTION: {question}"
    system = ANSWER_SYSTEM.format(today=datetime.now(timezone.utc).strftime("%A %Y-%m-%d"))
    answer = generate_text(prompt, system=system, temperature=0.2, throttle=False)
    cited = {int(x) for x in re.findall(r"\[E(\d+)\]", answer)}
    used = [s for s in sources if s["id"] in cited] or sources
    return {"answer": answer, "sources": used, "mode": mode, "filters": {k_: v for k_, v in filters.items() if k_ != "category_hint"}}
