@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "quickform.env.cmd" call "%~dp0quickform.env.cmd"
set DCE_MODE=demo
set QUICKFORM_FORMAL_ENABLED=NO
set QUICKFORM_PILOT_ENABLED=NO
set DCE_REQUIRE_INVITE=0
echo 演示入口 http://127.0.0.1:8000  后台 /admin
python server.py
pause
