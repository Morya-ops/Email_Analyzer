@echo off
REM Starts the FastAPI backend and the Streamlit UI (Windows).
cd /d "%~dp0"
if not exist .env copy .env.example .env
start "Email Analyser API" cmd /k uvicorn app.main:app --port 8000
timeout /t 3 >nul
streamlit run ui/app.py
