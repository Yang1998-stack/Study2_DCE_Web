@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if exist "quickform.env.cmd" call "%~dp0..\quickform.env.cmd"
echo 服务运行时请使用/admin中的同步管理；本地命令需先停止服务。
python server.py quickform-retry
pause
