@echo off
REM ============================================
REM Safe Django Server Starter
REM ============================================
REM This script checks if server is running and starts it properly
REM ============================================

echo.
echo ============================================
echo Django Server Safe Starter
echo ============================================
echo.

REM Check if port 8000 is already in use
netstat -an | findstr ":8000" | findstr "LISTENING" >nul
if %errorlevel% equ 0 (
    echo [WARNING] Port 8000 is already in use!
    echo.
    echo Checking if server is bound correctly...
    netstat -an | findstr "0.0.0.0:8000" | findstr "LISTENING" >nul
    if %errorlevel% equ 0 (
        echo [OK] Server is already running on 0.0.0.0:8000
        echo.
        echo Server should be accessible from mobile devices.
        echo If you're having connection issues, try:
        echo   1. Restart the server (close current instance and run this script again)
        echo   2. Check firewall settings
        echo   3. Verify both devices are on same Wi-Fi network
        echo.
        pause
        exit /b 0
    ) else (
        echo [ERROR] Server is running but NOT bound to 0.0.0.0:8000
        echo [ERROR] This means mobile devices CANNOT connect!
        echo.
        echo Please:
        echo   1. Stop the current server (Ctrl+C in the server window)
        echo   2. Run this script again to start it correctly
        echo.
        pause
        exit /b 1
    )
)

echo [INFO] Port 8000 is available, starting server...
echo.
echo Server will be accessible at:
echo   - http://localhost:8000 (on this computer)
echo   - http://172.16.37.58:8000 (on mobile devices)
echo.
echo Press Ctrl+C to stop the server
echo.
echo [INFO] Auto-reload: saving project files restarts the dev server automatically.
echo [INFO] "Broken pipe" means a client disconnected early; safe to ignore.
echo.
echo ============================================
echo.

REM Start the server bound to 0.0.0.0:8000 (auto-reload on by default; omit --noreload)
python manage.py runserver 0.0.0.0:8000

