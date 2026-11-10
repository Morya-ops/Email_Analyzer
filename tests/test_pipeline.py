"""Offline tests: Gemini is replaced by fakes, so no API key or network is needed."""
import json
from datetime import date, datetime, timedelta

import pytest

from app import alerts, analyzer, db, demo_data, email_client, llm, pipeline, rag, replies
from app.config import settings


# ───────────────────────── demo data ─────────────────────────
def test_demo_dataset_is_large_and_valid():
    data = demo_data.build_dataset()
    assert len(data) >= 100
    assert len({d["email"]["message_id"] for d in data}) == len(data)
    now = datetime.now().astimezone()
    for d in data:
        a = d["analysis"]
        assert a["priority"] in analyzer.PRIORITIES
        assert a["category"] in analyzer.CATEGORIES
        assert datetime.fromisoformat(d["email"]["received_at"]) <= now
        for dl in a["deadlines"]:
            date.fromisoformat(dl["due_date"])
    assert sum(len(d["analysis"]["deadlines"]) for d in data) >= 30


def test_load_demo_precomputed_runs_whole_pipeline():
    result = pipeline.load_demo(use_gemini=False, send_alerts=True)
    s = db.stats()
    assert result["loaded"] == s["total"] >= 100
    assert s["analyzed"] == s["total"] and s["indexed"] == s["total"]
    assert s["by_priority"]["High"] > 0 and s["open_deadlines"] > 0
    assert len(db.list_alerts()) > 0
    # alerts are sent once only
    assert alerts.run_alerts()["candidates"] == 0


# ───────────────────────── parsing & cleaning ─────────────────────────
RAW = b"""From: "Prof. Sharma" <Anita.Sharma@Campus.edu>
To: me@example.com
Subject: Re: Re: Assignment 3
Date: Tue, 03 Nov 2026 10:15:00 +0530
Message-ID: <abc123@campus.edu>
MIME-Version: 1.0
Content-Type: multipart/alternative; boundary="B"

--B
Content-Type: text/html; charset=utf-8

<html><body><p>Please submit by <b>Friday</b>.</p><style>p{color:red}</style></body></html>
--B--
"""


def test_parse_message_html_and_threading():
    e = email_client.parse_message(RAW)
    assert e["sender_email"] == "anita.sharma@campus.edu"
    assert e["thread_key"] == "assignment 3"
    assert "Please submit by Friday." in e["body"] and "color:red" not in e["body"]
    assert e["received_at"].startswith("2026-11-03T04:45:00")  # converted to UTC
    assert e["message_id"] == "<abc123@campus.edu>"


def test_clean_body_drops_quotes_and_signature():
    text = "Hi,\nPlease send the file.\nThanks\n\nOn Mon, 2 Nov 2026 at 9:00, Bob <b@x.com> wrote:\n> old text\n> more"
    assert email_client.clean_body(text) == "Hi,\nPlease send the file.\nThanks"
    assert "iPhone" not in email_client.clean_body("Line1\nLine2\nLine3\nSent from my iPhone")


# ───────────────────────── LLM helpers ─────────────────────────
def test_parse_json_loose():
    assert llm.parse_json_loose('```json\n[{"a": 1}]\n```') == [{"a": 1}]
    assert llm.parse_json_loose('Sure! {"x": 2} hope that helps') == {"x": 2}
    with pytest.raises(llm.LLMError):
        llm.parse_json_loose("no json here")


def test_retry_on_rate_limit(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("429 RESOURCE_EXHAUSTED. Please retry in 2.5s")
        return "ok"

    assert llm._with_retries(flaky, throttle=False) == "ok" and calls["n"] == 3

    def always_429():
        raise RuntimeError("429 RESOURCE_EXHAUSTED quota")

    with pytest.raises(llm.LLMError, match="quota"):
        llm._with_retries(always_429, throttle=False, max_tries=2)


def test_local_embedder_is_deterministic_and_normalised():
    a, b = llm.embed_texts(["interview schedule"], backend="local")[0], llm.embed_texts(["interview schedule"], backend="local")[0]
    assert a == b and abs(sum(x * x for x in a) - 1) < 1e-6


# ───────────────────────── analysis with a fake Gemini ─────────────────────────
def _insert_demo_without_analysis(n=12):
    ids = []
    for item in demo_data.build_dataset()[:n]:
        ids.append(db.insert_email(item["email"]))
    return ids


def test_normalize_analysis_repairs_bad_output():
    out = analyzer.normalize_analysis({"priority": "urgent!!", "category": "academic", "deadlines": [
        {"task": "Do X", "due_date": "2026-13-45"}, {"task": "Do Y", "due_date": "2026-11-09T10:00"}, {"nope": 1}]})
    assert out["priority"] == "Medium" and out["category"] == "Academic"
    assert [d["due_date"] for d in out["deadlines"]] == [None, "2026-11-09"]


def test_analyze_pending_with_fake_gemini_batches_and_fallbacks(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "fake")
    ids = _insert_demo_without_analysis(12)
    calls = []

    def fake_generate_json(prompt, system=None, temperature=0.1, throttle=False):
        calls.append(prompt)
        found = [int(x) for x in __import__("re").findall(r"### EMAIL id=(\d+)", prompt)]
        if len(calls) == 2:  # second batch: model "forgets" the last email -> must be retried individually
            found = found[:-1]
        if len(found) == 2:  # the last batch (2 emails) fails completely -> heuristic fallback
            raise llm.LLMError("boom")
        return [{"id": i, "priority": "High", "priority_reason": "fake reason", "category": "Academic",
                 "summary": "fake summary", "action_required": True,
                 "deadlines": [{"task": "T", "due_date": "2026-11-10", "confidence": "high"}]} for i in found]

    monkeypatch.setattr(analyzer, "generate_json", fake_generate_json)
    res = pipeline.analyze_pending()
    assert res == {"analyzed": 12, "gemini": 10, "heuristic": 2}
    assert db.stats()["pending_analysis"] == 0
    methods = {db.get_email(i)["method"] for i in ids}
    assert methods == {"gemini", "heuristic"}
    assert any(d["due_date"] == "2026-11-10" for e in db.list_emails() for d in e["deadlines"])


def test_heuristics_cover_basic_cases():
    assert analyzer.heuristic_analysis({"subject": "Flat 40% off sale", "body": "unsubscribe"})["priority"] == "Low"
    assert analyzer.heuristic_analysis({"subject": "URGENT: deadline tomorrow", "body": "x"})["priority"] == "High"


# ───────────────────────── RAG / chat ─────────────────────────
def test_chat_with_fake_gemini_cites_sources(monkeypatch):
    pipeline.load_demo(use_gemini=False, send_alerts=False)
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "fake")
    seen = {}

    def fake_generate_text(prompt, system=None, temperature=0.2, throttle=False, json_mode=False):
        seen["prompt"] = prompt
        first = __import__("re").search(r"\[E(\d+)\]", prompt).group(1)
        return f"The recruiter confirmed the interview [E{first}]."

    monkeypatch.setattr(rag, "generate_text", fake_generate_text)
    res = rag.answer_question("When is the interview with the recruiter at Nimbus Labs?")
    assert "[E" in res["answer"] and len(res["sources"]) == 1
    assert "nimbus" in seen["prompt"].lower()


def test_chat_without_gemini_still_returns_relevant_emails():
    pipeline.load_demo(use_gemini=False, send_alerts=False)
    res = rag.answer_question("overdue invoice PrintWorks")
    assert any("PW-2291" in s["subject"] for s in res["sources"])


def test_filters_are_parsed():
    pipeline.load_demo(use_gemini=False, send_alerts=False)
    f = rag.parse_filters("What did Vikram Singh send in the last 3 days?")
    assert f["sender_email"] == "vikram.singh@kestrel-demo.com" and f["since"] > 0
    assert rag.parse_filters("any invoices?")["category_hint"] == "Finance"


def test_keyword_fallback():
    pipeline.load_demo(use_gemini=False, send_alerts=False)
    hits = rag.keyword_retrieve("attendance shortage HoD")
    assert hits and "attendance" in hits[0]["text"].lower()


# ───────────────────────── replies ─────────────────────────
def test_replies_use_sender_and_thread_context(monkeypatch):
    pipeline.load_demo(use_gemini=False, send_alerts=False)
    thread = [e for e in db.list_emails(search="Sponsorship proposal") if e["subject"].startswith("Re:")]
    target = sorted(thread, key=lambda e: e["received_at"])[-1]
    captured = {}

    def fake_generate_json(prompt, system=None, temperature=0.5, throttle=False):
        captured["prompt"] = prompt
        return {"options": [{"tone": t, "subject": "Re: x", "body": f"{t} reply"} for t in ("Formal", "Friendly", "Brief")]}

    monkeypatch.setattr(replies, "generate_json", fake_generate_json)
    out = replies.generate_replies(target["id"], "mention the invoice goes out tomorrow")
    assert [o["tone"] for o in out["options"]] == ["Formal", "Friendly", "Brief"]
    assert len(out["context_used"]) >= 2
    assert "invoice goes out tomorrow" in captured["prompt"] and "Gold tier" in captured["prompt"]


# ───────────────────────── alerts ─────────────────────────
def test_alert_rules_and_cap(monkeypatch):
    monkeypatch.setattr(settings, "MAX_ALERTS_PER_RUN", 3)
    pipeline.load_demo(use_gemini=False, send_alerts=False)
    res = alerts.run_alerts()
    assert res["sent"] == 3 and res["suppressed"] == res["candidates"] - 3
    kinds = [a["kind"] for a in db.list_alerts()]
    assert "summary" in kinds and kinds.count("high_priority") + kinds.count("deadline_soon") == 3
    assert alerts.run_alerts()["candidates"] == 0


# ───────────────────────── IMAP (fake server) ─────────────────────────
class FakeIMAP:
    """Minimal stand-in for imaplib.IMAP4_SSL holding 3 messages with UIDs 1..3."""
    messages = {
        1: b"From: A <a@x.com>\nSubject: Hello\nDate: Mon, 02 Nov 2026 09:00:00 +0000\nMessage-ID: <m1@x>\n\nFirst",
        2: b"From: B <b@x.com>\nSubject: Re: Hello\nDate: Mon, 02 Nov 2026 10:00:00 +0000\nMessage-ID: <m2@x>\n\nSecond",
        3: b"From: C <c@x.com>\nSubject: Invoice due tomorrow\nDate: Tue, 03 Nov 2026 10:00:00 +0000\nMessage-ID: <m3@x>\n\nPay it",
    }

    def __init__(self, host, port): pass
    def login(self, user, pw): return "OK", [b"ok"]
    def select(self, folder, readonly=False): return "OK", [str(len(self.messages)).encode()]
    def logout(self): return "BYE", []

    def uid(self, cmd, *args):
        if cmd == "search":
            return "OK", [b" ".join(str(u).encode() for u in self.messages)]
        uid = int(args[0])
        return "OK", [(b"1 (BODY[] {0})", self.messages[uid]), b")"]


def test_sync_imap_is_incremental_and_deduplicated(monkeypatch):
    monkeypatch.setattr(email_client.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(settings, "IMAP_USER", "me@example.com")
    monkeypatch.setattr(settings, "IMAP_PASSWORD", "app-password")
    first = pipeline.sync_imap()
    assert first == {"fetched": 3, "new": 3}
    assert pipeline.sync_imap() == {"fetched": 0, "new": 0}  # nothing new since UID 3
    FakeIMAP.messages[4] = b"From: D <d@x.com>\nSubject: New one\nDate: Wed, 04 Nov 2026 08:00:00 +0000\nMessage-ID: <m4@x>\n\nNew"
    try:
        assert pipeline.sync_imap() == {"fetched": 1, "new": 1}
    finally:
        del FakeIMAP.messages[4]
    # full process() without Gemini falls back to heuristics and still indexes + alerts
    out = pipeline.process(sync=False, send_alerts=False, use_llm=False)
    assert out["analysis"]["analyzed"] == 4 and out["indexed"] == 4
    assert db.get_email(db.list_emails(search="Invoice")[0]["id"])["priority"] == "High"
