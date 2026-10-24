@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 goto python_fallback
py -3 -m pip install -r requirements.txt
goto finished
:python_fallback
python -m pip install -r requirements.txt
:finished
pause
