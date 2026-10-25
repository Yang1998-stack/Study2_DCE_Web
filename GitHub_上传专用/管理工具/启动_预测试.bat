@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if exist "quickform.env.cmd" call "%~dp0..\quickform.env.cmd"
set DCE_MODE=pilot
echo 预测试入口 http://127.0.0.1:8000  后台 /admin
python server.py
pause
