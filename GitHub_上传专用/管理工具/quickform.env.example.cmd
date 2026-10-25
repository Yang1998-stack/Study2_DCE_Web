@echo off
rem 复制到项目根目录并命名为 quickform.env.cmd 再填写；该私有文件不进入源码包。
set DCE_MODE=demo
set DCE_HOST=127.0.0.1
set DCE_PORT=8000
set QUICKFORM_API_URL=https://quickform.cn/api/kajm9wjasx
set QUICKFORM_FORMAL_ENABLED=NO
set QUICKFORM_PILOT_API_URL=
set QUICKFORM_PILOT_ENABLED=NO
set DCE_ALLOW_FORMAL=NO
set DCE_SECURE_COOKIE=0
rem 正式调查需先配置HTTPS和config/study_config.json，再有意将相关开关改为YES/1。
rem 不要把pilot地址设为正式任务；QUICKFORM_ALLOW_LOCAL_TEST仅供自动测试。
