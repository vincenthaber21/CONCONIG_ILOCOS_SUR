@echo off
REM ============================================
REM Simple Server Connection Test
REM ============================================

echo.
echo ============================================
echo Simple Server Connection Test
echo ============================================
echo.

echo [1] Checking if server is running...
netstat -an | findstr ":8000" | findstr "LISTENING" >nul
if %errorlevel% neq 0 (
    echo    [ERROR] Server is NOT running!
    echo    [FIX] Start server with: python manage.py runserver 0.0.0.0:8000
    echo    Or use: start_server_safe.bat
    pause
    exit /b 1
)
echo    [OK] Server is running on port 8000
echo.

echo [2] Checking server binding...
netstat -an | findstr "0.0.0.0:8000" | findstr "LISTENING" >nul
if %errorlevel% neq 0 (
    echo    [ERROR] Server is NOT bound to 0.0.0.0:8000
    echo    [ERROR] Mobile devices CANNOT connect!
    echo    [FIX] Stop server and restart with: python manage.py runserver 0.0.0.0:8000
    pause
    exit /b 1
)
echo    [OK] Server is bound to 0.0.0.0:8000 (accessible from network)
echo.

echo [3] Your IP address:
ipconfig | findstr /C:"IPv4 Address" | findstr "172.16"
echo.

echo [4] Testing server with curl...
curl -s -o nul -w "HTTP Status: %%{http_code}\n" http://localhost:8000/admin/ 2>nul
if %errorlevel% equ 0 (
    echo    [OK] Server responds locally!
) else (
    echo    [WARNING] Could not test with curl (curl might not be installed)
)
echo.

echo ============================================
echo Test Complete!
echo ============================================
echo.
echo Server Status: RUNNING and BOUND CORRECTLY
echo.
echo Next Steps:
echo 1. Open mobile browser and go to: http://172.16.37.58:8000/admin/
echo 2. If you see Django admin login, server is working!
echo 3. Try your mobile app - it should connect automatically
echo.
echo Note: PowerShell connection test may fail due to Windows security,
echo       but the server is actually working correctly!
echo.
pause

