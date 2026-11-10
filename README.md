# 📬 Email Analyser

An AI email assistant built on **Gemini + FastAPI + Streamlit**. It reads an inbox and:

| Feature | How it works |
|---|---|
| **Priority + explanation** | One Gemini call per batch of emails returns `High / Medium / Low` **and the reason** (sender, deadline, tone, action needed) |
| **Summaries** | 1-2 sentence summary per email, generated in the same call |
| **Deadline extraction** | Tasks + dates ("by Friday" → a real `YYYY-MM-DD`), shown in a sorted deadlines board |
| **Context-aware replies** | 3 drafts (Formal / Friendly / Brief) written with earlier emails from the same sender/thread plus RAG-similar emails as context |
| **Ask your inbox (RAG)** | Embeddings in ChromaDB → retrieval (with sender / date filters) → Gemini answers with `[E12]` citations |
| **Alerts** | Telegram message (free) + in-app alert log when an email is High priority or has a deadline within 48 h |

**No authentication.** It is a single-user local app tied to one mailbox configured in `.env`
(IMAP + app password: no OAuth, no Google Cloud project). You can also run it on a built-in
**demo inbox of 112 synthetic emails** with zero mailbox setup.

```
 IMAP mailbox ─┐                       ┌───────────── Telegram alert
 (or demo)     ▼                       │
          ┌──────────┐   ┌──────────┐  │   ┌─────────────────────────────┐
          │ FastAPI  │──▶│ Gemini   │──┘   │ Streamlit UI                │
          │ pipeline │   │ analysis │      │  Inbox · Chat · Deadlines   │
          └────┬─────┘   └──────────┘      │  · Alerts                   │
               ▼                           └──────────────▲──────────────┘
      SQLite (emails, analyses,                           │ REST
      deadlines, alerts)  +  ChromaDB (vectors) ◀─────────┘
```

---

## 1. Quick start (demo inbox, ~5 minutes)

Requires **Python 3.10+**.

```bash
cd email-analyser
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                 # Windows: copy .env.example .env
```

Edit `.env` and paste a free Gemini key (https://aistudio.google.com/apikey):

```
GEMINI_API_KEY=your_key_here
```

Start both services:

```bash
./start.sh                           # Windows: start.bat
```

…or manually in two terminals:

```bash
uvicorn app.main:app --port 8000     # terminal 1  (API docs: http://localhost:8000/docs)
streamlit run ui/app.py              # terminal 2  (UI: http://localhost:8501)
```

In the UI sidebar click **📥 Load demo inbox**. You get 112 emails with priorities, reasons,
summaries, ~50 deadlines, a populated alert log and a searchable chatbot.

> Without a Gemini key the inbox, deadlines, alerts and search still work (demo analyses are
> precomputed). **Reply drafts and chat answers need Gemini.**

Check your setup at any time:

```bash
python scripts/check_setup.py
```

### Demo options

| Want | Do |
|---|---|
| Instant demo, zero API usage | Load demo inbox (default) |
| Prove the AI really works | Tick **"Let Gemini analyse the demo emails"** before loading (a few minutes on the free tier; emails are analysed 5 per request) |
| Same from the terminal | `python scripts/seed_demo.py` or `python scripts/seed_demo.py --gemini` |

Demo dates are generated relative to *today* each time you load it, so deadlines are never stale.

---

## 2. Test with a real email account

Use a **test / secondary account**: email text is sent to Gemini (free-tier prompts may be used
by Google to improve its products).

### Gmail
1. Gmail → Settings → *Forwarding and POP/IMAP* → **Enable IMAP**.
2. Turn on **2-Step Verification** for the Google account.
3. Create an **App Password**: https://myaccount.google.com/apppasswords (16 characters).
4. Put it in `.env`:
   ```
   IMAP_HOST=imap.gmail.com
   IMAP_USER=you@gmail.com
   IMAP_PASSWORD=abcd efgh ijkl mnop
   ```
5. Restart the backend, then click **🔄 Sync my mailbox**
   (or `python scripts/sync_mailbox.py --limit 30`).

Other providers work too: set `IMAP_HOST` (Outlook: `outlook.office365.com`, Yahoo: `imap.mail.yahoo.com`).

The connection is **read-only** and uses `BODY.PEEK`, so emails are never marked as read, moved or
deleted. Re-syncing fetches only emails newer than the last sync, and each email is analysed and
indexed exactly once. Set `AUTO_SYNC_MINUTES=5` to poll automatically.

> **Tip:** send yourself 10-15 varied emails first (a deadline, an invoice, a "please reply by
> Friday") to watch the full flow on live data.

### Telegram alerts (optional, free)
1. Telegram → **@BotFather** → `/newbot` → copy the token.
2. Send any message to your new bot.
3. Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy the `chat` → `id` value.
4. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in `.env`, restart the backend, and press
   **Send a test alert** in the Alerts tab.

Without Telegram, alerts are still logged in the **🔔 Alerts** tab.

---

## 3. Project structure

```
email-analyser/
├── app/                      # FastAPI backend
│   ├── main.py               # REST endpoints + background job runner
│   ├── pipeline.py           # fetch → analyse → store → index → alert
│   ├── email_client.py       # IMAP reader, MIME parsing, quote/signature cleaning
│   ├── analyzer.py           # Gemini prompt (priority+reason, summary, deadlines) + heuristic fallback
│   ├── llm.py                # Gemini wrapper: throttling, 429 retries, JSON parsing, embeddings
│   ├── rag.py                # ChromaDB indexing, filtered retrieval, cited answers
│   ├── replies.py            # context-aware reply generation
│   ├── alerts.py             # Telegram + in-app alert log, de-duplication
│   ├── db.py                 # SQLite schema and queries
│   ├── demo_data.py          # 112 synthetic emails + ground-truth analyses
│   └── config.py             # settings from .env
├── ui/app.py                 # Streamlit dashboard
├── scripts/
│   ├── seed_demo.py          # load the demo inbox from the CLI
│   ├── sync_mailbox.py       # sync a real mailbox from the CLI
│   └── check_setup.py        # verifies Gemini / IMAP / Telegram
├── tests/                    # offline pytest suite (Gemini + IMAP are faked)
├── data/                     # SQLite + Chroma are created here (git-ignored)
└── .env.example  requirements.txt  start.sh  start.bat
```

## 4. How the pipeline works

1. **Fetch**: IMAP → parse MIME → strip HTML, quoted replies and signatures → normalise the subject into a `thread_key`.
2. **Analyse**: emails go to Gemini **5 per request** as a JSON array (`ANALYSIS_BATCH_SIZE`), with each email's received date included so relative dates resolve correctly. Output is validated (bad priorities, impossible dates and missing ids are repaired or retried). If Gemini is unavailable or out of quota, keyword heuristics fill in so nothing crashes; the UI shows which method produced each analysis.
3. **Store**: SQLite holds emails, analyses, deadlines and alerts. Results are saved after every batch, so an interrupted run loses nothing.
4. **Index**: each email (chunked if long) is embedded (Gemini embeddings, or an offline hashing fallback) into Chroma with sender / date / category metadata.
5. **Alert**: High-priority emails or deadlines within 48 h trigger one alert each (capped by `MAX_ALERTS_PER_RUN`; extras are summarised in one message).
6. **Ask / reply**: questions are parsed for simple filters ("last 3 days", a known sender's name), retrieved from Chroma and answered by Gemini with citations. Replies gather the thread, sender history and similar emails first.

## 5. Configuration (`.env`)

| Variable | Default | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | none | Free key from Google AI Studio |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Try `gemini-2.5-flash-lite` for higher free-tier limits |
| `EMBED_BACKEND` | `auto` | `gemini`, `local` (offline) or `auto` |
| `LLM_MIN_INTERVAL_SEC` | `6` | Pause between bulk Gemini calls (about 10 requests/min) |
| `ANALYSIS_BATCH_SIZE` | `5` | Emails per analysis request |
| `IMAP_*` | none | Mailbox credentials (app password) |
| `FETCH_LIMIT` | `100` | Newest N emails on the first sync |
| `TELEGRAM_*` | none | Optional alert channel |
| `ALERT_DEADLINE_HOURS` | `48` | "Deadline soon" window |
| `USER_CONTEXT`, `VIP_SENDERS` | none | Free text that personalises priority decisions |
| `AUTO_SYNC_MINUTES` | `0` | Poll the mailbox automatically |

Free-tier quotas change over time, so check your limits in Google AI Studio. On quota errors,
wait a minute or switch to `gemini-2.5-flash-lite`.

## 6. REST API (http://localhost:8000, docs at `/docs`)

`GET /health` · `GET /stats` · `GET /emails?priority=High&category=Finance&search=…` ·
`GET /emails/{id}` · `POST /emails/{id}/replies` · `POST /chat` · `GET /deadlines` ·
`POST /deadlines/{id}/done` · `GET /alerts` · `POST /alerts/test` · `POST /sync` · `POST /analyze` ·
`POST /demo/load` · `GET /job` · `POST /imap/test` · `POST /reset`

Long actions (`/sync`, `/analyze`, `/demo/load`) run as one background job; poll `GET /job` for progress.

## 7. Tests

```bash
pytest -q          # 17 tests, fully offline (Gemini and IMAP are faked)
```

## 8. Troubleshooting

| Symptom | Fix |
|---|---|
| UI says *backend not reachable* | Start `uvicorn app.main:app --port 8000` |
| IMAP `Login failed` | Use a Gmail **App Password**, enable IMAP, check 2-Step Verification |
| `quota / rate limit reached` | Free-tier limit: wait a minute, use `gemini-2.5-flash-lite`, or raise `LLM_MIN_INTERVAL_SEC` |
| Chat says "Gemini key not configured" | Set `GEMINI_API_KEY` and restart the backend |
| Everything marked `heuristic` | Gemini failed during analysis: run `python scripts/check_setup.py`, then clear data and re-sync |
| Switched embedding backend | Re-load / re-sync; each backend keeps its own Chroma collection |

## 9. Before pushing to GitHub

`.env`, `data/*.db` and `data/chroma/` are already in `.gitignore`. Never commit your key or app
password. If you do, revoke it immediately (deleting the file does not remove it from git history).

## 10. Known limitations

- Single user, single mailbox, no login by design.
- Read-only: it drafts replies but never sends or modifies mail.
- Plain-text extraction only (attachments are ignored).
- Free-tier Gemini limits make the first bulk analysis of ~100 real emails take a few minutes.
