@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set DCE_MODE=demo
python server.py export
pause
