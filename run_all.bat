@echo off
setlocal
cd /d "%~dp0"
python run.py --setup
if errorlevel 1 pause
