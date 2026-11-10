"""Thin wrapper around the Gemini API (google-genai SDK).

Gives the rest of the app four simple things:
    generate_text(), generate_json(), embed_texts(), llm_available()
and hides throttling, retries on rate limits (HTTP 429) and JSON clean-up.
"""
import json
import logging
import math
import re
import threading
import time
import zlib
from typing import Any, Optional

from .config import settings

log = logging.getLogger("llm")


class LLMError(Exception):
    """Raised when Gemini cannot be used (no key, quota exhausted, bad output...)."""


_client = None
_client_lock = threading.Lock()
_throttle_lock = threading.Lock()
_last_call = 0.0


def llm_available() -> bool:
    return settings.llm_configured


def _get_client():
    global _client
    if not settings.llm_configured:
        raise LLMError("GEMINI_API_KEY is not set. Add it to your .env file (free key: https://aistudio.google.com/apikey).")
    with _client_lock:
        if _client is None:
            from google import genai  # imported lazily so the app still starts without the SDK configured
            _client = genai.Client(api_key=settings.GEMINI_API_KEY)
        return _client


def _throttle(min_interval: float) -> None:
    """Keep bulk calls under the free-tier requests-per-minute limit."""
    global _last_call
    with _throttle_lock:
        wait = _last_call + min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.monotonic()


def _retry_delay_from(msg: str, default: float) -> float:
    m = re.search(r"retry in ([\d.]+)s", msg, re.I) or re.search(r"retryDelay['\"]?:\s*['\"]?(\d+)", msg)
    if m:
        try:
            return min(float(m.group(1)) + 1.0, 90.0)
        except ValueError:
            pass
    return default


def _is_retryable(msg: str) -> bool:
    msg = msg.lower()
    return any(t in msg for t in ("429", "resource_exhausted", "quota", "503", "unavailable", "overloaded", "500", "deadline"))


def _with_retries(fn, *, throttle: bool, max_tries: int = 4):
    delay = 8.0
    last_err: Optional[Exception] = None
    for attempt in range(1, max_tries + 1):
        if throttle:
            _throttle(settings.LLM_MIN_INTERVAL_SEC)
        try:
            return fn()
        except LLMError:
            raise
        except Exception as exc:  # SDK raises several exception types; classify by message
            last_err = exc
            msg = str(exc)
            if attempt < max_tries and _is_retryable(msg):
                wait = _retry_delay_from(msg, delay)
                log.warning("Gemini rate-limited/unavailable (attempt %s/%s). Waiting %.0fs", attempt, max_tries, wait)
                time.sleep(wait)
                delay *= 2
                continue
            break
    short = str(last_err)[:300]
    if last_err is not None and any(t in str(last_err).lower() for t in ("429", "quota", "resource_exhausted")):
        raise LLMError(f"Gemini free-tier quota/rate limit reached. Wait a minute (or switch to gemini-3.5-flash-lite). Details: {short}")
    raise LLMError(f"Gemini call failed: {short}")


# ───────────────────────── generation ─────────────────────────
def generate_text(prompt: str, system: Optional[str] = None, temperature: float = 0.3,
                  throttle: bool = False, json_mode: bool = False) -> str:
    client = _get_client()
    from google.genai import types

    def _call():
        cfg = types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            response_mime_type="application/json" if json_mode else None,
        )
        resp = client.models.generate_content(model=settings.GEMINI_MODEL, contents=prompt, config=cfg)
        text = (resp.text or "").strip()
        if not text:
            raise LLMError("Gemini returned an empty response (it may have been blocked by safety filters).")
        return text

    return _with_retries(_call, throttle=throttle)


def parse_json_loose(text: str) -> Any:
    """Parse JSON that may be wrapped in markdown fences or have chatter around it."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_c, close_c in (("[", "]"), ("{", "}")):
        start, end = text.find(open_c), text.rfind(close_c)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise LLMError("Gemini did not return valid JSON.")


def generate_json(prompt: str, system: Optional[str] = None, temperature: float = 0.1, throttle: bool = False) -> Any:
    text = generate_text(prompt, system=system, temperature=temperature, throttle=throttle, json_mode=True)
    return parse_json_loose(text)


# ───────────────────────── embeddings ─────────────────────────
LOCAL_DIM = 512
_STOP = set("a an the and or of to in on for with at by from is are was were be been it this that as your you i we our "
            "please dear hi hello thanks thank regards sir madam will would can could has have had not no".split())


def embedding_backend() -> str:
    """'gemini' or 'local' (a free offline hashing embedder used when no API key is set)."""
    if settings.EMBED_BACKEND == "gemini":
        return "gemini"
    if settings.EMBED_BACKEND == "local":
        return "local"
    return "gemini" if settings.llm_configured else "local"


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


def local_embed(text: str) -> list[float]:
    """Bag-of-words hashing embedder. Not semantic, but deterministic, offline and good enough as a fallback."""
    vec = [0.0] * LOCAL_DIM
    tokens = [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in _STOP and len(t) > 1]
    grams = tokens + [f"{a}_{b}" for a, b in zip(tokens, tokens[1:])]
    for g in grams:
        h = zlib.crc32(g.encode())
        vec[h % LOCAL_DIM] += 1.0 if (h >> 16) & 1 else -1.0  # signed hashing trick
    return _normalize(vec)


def embed_texts(texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT", backend: Optional[str] = None) -> list[list[float]]:
    backend = backend or embedding_backend()
    if backend == "local":
        return [local_embed(t) for t in texts]

    client = _get_client()
    from google.genai import types
    out: list[list[float]] = []
    for i in range(0, len(texts), 50):
        batch = texts[i:i + 50]

        def _call(batch=batch):
            resp = client.models.embed_content(
                model=settings.EMBED_MODEL, contents=batch,
                config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=768),
            )
            return [list(e.values) for e in resp.embeddings]

        out.extend(_normalize(v) for v in _with_retries(_call, throttle=len(texts) > 50))
    return out
