@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在启动 深海小女仆 2.0 ...
python pet\main.py
pause
