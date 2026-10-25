@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if exist "quickform.env.cmd" call "%~dp0..\quickform.env.cmd"
python server.py quickform-status
pause
