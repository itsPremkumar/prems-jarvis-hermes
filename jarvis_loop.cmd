@echo off
REM Jarvis independent orchestrator loop. Runs OUTSIDE Hermes (via Windows Task
REM Scheduler) so the cycle survives the Hermes desktop app being closed/crashed.
REM Pure-Python cycle only (no worker spawning here); the Hermes cron resumes
REM worker dispatch when Hermes is back. Defense-in-depth alongside the cron.
cd /d C:\c\one\prems-jarvis-hermes
"C:\Users\PREM KUMAR\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" -m jarvis.cli run >> jarvis_loop.log 2>&1
