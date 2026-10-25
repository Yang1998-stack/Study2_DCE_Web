@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist "quickform.env.cmd" (
  echo 请先把管理工具中的quickform.env.example.cmd复制到项目根目录并命名为quickform.env.cmd并完成正式配置。
  pause
  exit /b 1
)
call "%~dp0..\quickform.env.cmd"
set DCE_MODE=formal
if not "%QUICKFORM_FORMAL_ENABLED%"=="YES" (
  echo 正式QuickForm收集尚未明确启用，请阅读README后配置。
  pause
  exit /b 1
)
python server.py
pause
