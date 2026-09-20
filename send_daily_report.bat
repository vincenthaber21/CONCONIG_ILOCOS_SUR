@echo off
REM Daily Report Sender Batch File
REM This batch file runs the daily report command

cd /d "%~dp0"
call venv\Scripts\activate.bat
python manage.py send_daily_report

REM Optional: Uncomment the line below to pause and see any errors
REM pause

