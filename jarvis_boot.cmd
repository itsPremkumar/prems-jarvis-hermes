@echo off
REM Jarvis reboot-survival trigger. Registered via: schtasks /create /tn "JarvisBoot" /tr "C:\c\one\prems-jarvis-hermes\jarvis_boot.cmd" /sc onlogon
cd /d C:\c\one\prems-jarvis-hermes
python -m jarvis.cli run >> jarvis_boot.log 2>&1
