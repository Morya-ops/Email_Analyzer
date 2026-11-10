"""Streamlit front-end.   Run:  streamlit run ui/app.py     (the FastAPI backend must be running)"""
import os
from typing import Optional
import time
from datetime import date, datetime

import pandas as pd
import requests
import streamlit as st

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
PRIORITY_ICON = {"High": "🔴", "Medium": "🟠", "Low": "🟢", None: "⚪"}

st.set_page_config(page_title="Email Analyser", page_icon="📬", layout="wide")


# ───────────────────────── API helpers ─────────────────────────
def api(method: str, path: str, quiet: bool = False, **kwargs):
    """Call the backend. Returns parsed JSON, or None after showing an error."""
    try:
        r = requests.request(method, f"{BACKEND}{path}", timeout=kwargs.pop("timeout", 120), **kwargs)
    except requests.RequestException:
        if not quiet:
            st.error(f"Cannot reach the backend at {BACKEND}. Start it with:  `uvicorn app.main:app --port 8000`")
        return None
    if r.status_code >= 400:
        if not quiet:
            try:
                detail = r.json().get("detail", r.text)
            except ValueError:
                detail = r.text
            st.error(detail)
        return None
    return r.json()


def fmt_dt(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d %b, %H:%M")
    except (TypeError, ValueError):
        return iso or ""


def due_label(due: Optional[str]) -> str:
    if not due:
        return "no date"
    try:
        delta = (date.fromisoformat(due) - date.today()).days
    except ValueError:
        return due
    if delta < 0:
        return f"⛔ overdue by {-delta}d"
    return "🔥 today" if delta == 0 else "⏰ tomorrow" if delta == 1 else f"in {delta} days"


# ───────────────────────── global state ─────────────────────────
health = api("GET", "/health", quiet=True)
if health is None:
    st.title("📬 Email Analyser")
    st.error(f"Backend not reachable at **{BACKEND}**.")
    st.code("uvicorn app.main:app --port 8000", language="bash")
    st.stop()

stats = api("GET", "/stats", quiet=True) or {}
job = api("GET", "/job", quiet=True) or {}

# ───────────────────────── sidebar ─────────────────────────
with st.sidebar:
    st.title("📬 Email Analyser")
    st.caption("Priority · Summaries · Replies · Ask-your-inbox · Deadlines")

    st.subheader("System")
    st.markdown(
        f"{'🟢' if health['llm_configured'] else '🔴'} Gemini `{health['gemini_model']}`  \n"
        f"{'🟢' if health['imap_configured'] else '⚪'} Mailbox (IMAP) {('· ' + health['imap_user']) if health['imap_user'] else '· not configured'}  \n"
        f"{'🟢' if health['telegram_configured'] else '⚪'} Telegram alerts  \n"
        f"🧠 Embeddings: `{health['embedding_backend']}`"
    )
    if not health["llm_configured"]:
        st.warning("No `GEMINI_API_KEY` – inbox demo works, but replies and chat answers need Gemini.")

    st.subheader("Load emails")
    busy = job.get("state") == "running"
    use_gemini = st.checkbox("Let Gemini analyse the demo emails", value=False, disabled=not health["llm_configured"],
                             help="Off = instant precomputed analysis (no API calls). On = real Gemini analysis (~2-4 min for 112 emails).")
    if st.button("📥 Load demo inbox (112 emails)", width="stretch", disabled=busy):
        if api("POST", "/demo/load", json={"use_gemini": use_gemini, "send_alerts": True}):
            st.rerun()
    if st.button("🔄 Sync my mailbox (IMAP)", width="stretch", disabled=busy or not health["imap_configured"],
                 help="Fetches your newest emails, analyses and indexes them."):
        if api("POST", "/sync"):
            st.rerun()
    if stats.get("pending_analysis"):
        if st.button(f"🧠 Analyse {stats['pending_analysis']} pending emails", width="stretch", disabled=busy):
            if api("POST", "/analyze"):
                st.rerun()

    if job.get("state") == "running":
        st.info(f"⏳ {job.get('step', 'Working…')}")
    elif job.get("state") == "done" and job.get("kind"):
        st.success(f"✅ {job['kind']} finished")
    elif job.get("state") == "error":
        st.error(f"Job failed: {job.get('error')}")

    if stats.get("total"):
        st.subheader("Inbox at a glance")
        bp = stats.get("by_priority", {})
        c1, c2, c3 = st.columns(3)
        c1.metric("🔴 High", bp.get("High", 0))
        c2.metric("🟠 Med", bp.get("Medium", 0))
        c3.metric("🟢 Low", bp.get("Low", 0))
        st.caption(f"{stats['total']} emails · {stats['open_deadlines']} open deadlines · {stats['indexed']} indexed")
        if st.button("🗑️ Clear all data", width="stretch", disabled=busy):
            if api("POST", "/reset"):
                st.session_state.clear()
                st.rerun()

# ───────────────────────── empty state ─────────────────────────
if not stats.get("total"):
    st.title("📬 Email Analyser")
    st.info("The inbox is empty. Click **Load demo inbox** in the sidebar to try everything instantly, "
            "or configure your mailbox in `.env` and click **Sync my mailbox**.")
    if job.get("state") == "running":
        time.sleep(2)
        st.rerun()
    st.stop()

tab_inbox, tab_chat, tab_deadlines, tab_alerts = st.tabs(["📥 Inbox", "💬 Ask your inbox", "⏰ Deadlines", "🔔 Alerts"])

# ───────────────────────── Inbox ─────────────────────────
with tab_inbox:
    f1, f2, f3, f4 = st.columns([2, 2, 3, 2])
    prios = f1.multiselect("Priority", ["High", "Medium", "Low"], default=["High", "Medium", "Low"])
    cats = ["All"] + list(stats.get("by_category", {}).keys())
    category = f2.selectbox("Category", cats)
    search = f3.text_input("Search", placeholder="sender, subject or summary…")
    sort = f4.selectbox("Sort by", ["priority", "date"], format_func=lambda s: "Priority, then newest" if s == "priority" else "Newest first")

    emails = api("GET", "/emails", params={"priority": prios, "category": category, "search": search, "sort": sort}) or []
    if not emails:
        st.warning("No emails match these filters.")
    else:
        rows = []
        for e in emails:
            dls = e.get("deadlines") or []
            rows.append({
                "ID": e["id"],
                "Priority": f"{PRIORITY_ICON.get(e['priority'])} {e['priority'] or 'Pending'}",
                "Category": e["category"] or "-",
                "From": e["sender_name"],
                "Subject": e["subject"],
                "Received": fmt_dt(e["received_at"]),
                "Next deadline": f"{dls[0]['due_date']} ({due_label(dls[0]['due_date'])})" if dls and dls[0]["due_date"] else "",
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", height=300)

        st.divider()
        options = {e["id"]: f"{PRIORITY_ICON.get(e['priority'])} #{e['id']} · {e['subject']} — {e['sender_name']}" for e in emails}
        selected = st.selectbox("Open an email", list(options), format_func=lambda i: options[i])
        detail = api("GET", f"/emails/{selected}")
        if detail:
            left, right = st.columns([3, 2], gap="large")
            with left:
                st.subheader(detail["subject"])
                st.caption(f"From **{detail['sender_name']}** <{detail['sender_email']}> · {fmt_dt(detail['received_at'])}")
                st.markdown(f"**Summary**  \n{detail.get('summary') or '_not analysed yet_'}")
                with st.expander("Original email"):
                    st.text(detail["body"])
            with right:
                p = detail.get("priority")
                st.markdown(f"### {PRIORITY_ICON.get(p)} {p or 'Pending'} priority")
                st.markdown(f"**Why:** {detail.get('priority_reason') or '-'}")
                st.markdown(f"**Category:** {detail.get('category') or '-'}  \n"
                            f"**Action required:** {'Yes' if detail.get('action_required') else 'No'}")
                st.caption(f"Analysis method: {detail.get('method') or '-'}")
                if detail["deadlines"]:
                    st.markdown("**Deadlines found**")
                    for d in detail["deadlines"]:
                        st.markdown(f"- {'~~' if d['done'] else ''}{d['task']}{'~~' if d['done'] else ''} — "
                                    f"`{d['due_date'] or 'no date'}` · {due_label(d['due_date'])}")

            st.markdown("#### ✍️ Reply drafts")
            instr = st.text_input("Anything the reply should say? (optional)", key=f"instr_{selected}",
                                  placeholder="e.g. say I will submit by Friday and ask for a one-day extension")
            if st.button("Generate 3 reply options", key=f"gen_{selected}", type="primary"):
                with st.spinner("Reading earlier emails and drafting…"):
                    res = api("POST", f"/emails/{selected}/replies", json={"instructions": instr or None})
                if res:
                    st.session_state[f"replies_{selected}"] = res
            res = st.session_state.get(f"replies_{selected}")
            if res:
                tabs = st.tabs([o["tone"] for o in res["options"]])
                for tab, o in zip(tabs, res["options"]):
                    with tab:
                        st.text_input("Subject", o["subject"], key=f"s_{selected}_{o['tone']}")
                        st.text_area("Body (editable)", o["body"], height=220, key=f"b_{selected}_{o['tone']}")
                if res["context_used"]:
                    with st.expander(f"Context used ({len(res['context_used'])} earlier emails)"):
                        for c in res["context_used"]:
                            st.markdown(f"- #{c['id']} · {c['subject']} ({fmt_dt(c['received_at'])})")
                else:
                    st.caption("No earlier emails with this sender were found, so the draft has no extra context.")

# ───────────────────────── Chat ─────────────────────────
with tab_chat:
    st.subheader("Ask your inbox")
    st.caption("Examples: “What did the recruiter say about the interview?” · “Which invoices are pending?” · "
               "“What is due this week?” · “Any suspicious emails?”")
    history = st.session_state.setdefault("chat", [])
    for turn in history:
        with st.chat_message(turn["role"]):
            st.markdown(turn["content"])
            if turn.get("sources"):
                with st.expander(f"Sources ({len(turn['sources'])})"):
                    for s in turn["sources"]:
                        st.markdown(f"- **[E{s['id']}]** {s['subject']} — {s['sender']} ({fmt_dt(s['received_at'])})")
    question = st.chat_input("Ask something about your emails…")
    if question:
        history.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Searching your inbox…"):
                res = api("POST", "/chat", json={"question": question})
            if res:
                st.markdown(res["answer"])
                if res["sources"]:
                    with st.expander(f"Sources ({len(res['sources'])})"):
                        for s in res["sources"]:
                            st.markdown(f"- **[E{s['id']}]** {s['subject']} — {s['sender']} ({fmt_dt(s['received_at'])})")
                history.append({"role": "assistant", "content": res["answer"], "sources": res["sources"]})
        if len(history) > 40:
            del history[:-40]

# ───────────────────────── Deadlines ─────────────────────────
with tab_deadlines:
    st.subheader("Upcoming deadlines")
    show_done = st.checkbox("Show completed", value=False)
    dls = api("GET", "/deadlines", params={"include_done": show_done}) or []
    if not dls:
        st.info("No deadlines extracted yet.")
    else:
        head = st.columns([4, 2, 2, 2, 1])
        for col, title in zip(head, ["Task", "Due", "When", "From", ""]):
            col.markdown(f"**{title}**")
        for d in dls[:80]:
            cols = st.columns([4, 2, 2, 2, 1])
            label = f"{PRIORITY_ICON.get(d['priority'])} {d['task']}"
            cols[0].markdown(f"~~{label}~~" if d["done"] else label)
            cols[1].write(d["due_date"] or "—")
            cols[2].write(due_label(d["due_date"]))
            cols[3].write(d["sender_name"])
            if cols[4].button("✅" if not d["done"] else "↩️", key=f"dl_{d['id']}", help="Toggle done"):
                api("POST", f"/deadlines/{d['id']}/done", json={"done": not d["done"]})
                st.rerun()

# ───────────────────────── Alerts ─────────────────────────
with tab_alerts:
    st.subheader("Alert log")
    st.caption("An alert fires once per email when it is High priority or has a deadline within 48 hours. "
               "Delivered to Telegram when configured, and always logged here.")
    if st.button("Send a test alert"):
        res = api("POST", "/alerts/test")
        if res:
            st.success(f"Sent via {res['channel']}")
    log = api("GET", "/alerts") or []
    if log:
        st.dataframe(pd.DataFrame([{"Time": fmt_dt(a["created_at"]), "Type": a["kind"], "Channel": a["channel"],
                                    "Message": a["message"].replace("\n", "  ·  ")} for a in log]),
                     hide_index=True, width="stretch")
    else:
        st.info("No alerts yet.")

# ───────────────────────── auto-refresh while a job runs ─────────────────────────
if job.get("state") == "running":
    time.sleep(2)
    st.rerun()
