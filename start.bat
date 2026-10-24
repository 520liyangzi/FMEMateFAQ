@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto python_fallback
py -3 app.py
goto finished
:python_fallback
python app.py
:finished
if errorlevel 1 pause
