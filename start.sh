#!/usr/bin/env bash
# Starts the FastAPI backend and the Streamlit UI together (Ctrl+C stops both).
set -e
cd "$(dirname "$0")"
[ -f .env ] || cp .env.example .env
uvicorn app.main:app --port 8000 &
BACK=$!
trap "kill $BACK 2>/dev/null" EXIT
sleep 2
streamlit run ui/app.py
