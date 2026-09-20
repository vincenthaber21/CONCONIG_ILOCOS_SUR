@echo off
REM ============================================
REM Mobile App Connection Test Script
REM ============================================
echo.
echo ============================================
echo Mobile App Connection Diagnostic Tool
echo ============================================
echo.

echo [1/6] Checking if Django server is running on port 8000...
netstat -an | findstr :8000 >nul
if %errorlevel% equ 0 (
    echo    [OK] Port 8000 is in use (server might be running)
) else (
    echo    [WARNING] Port 8000 is not in use - server might not be running
)
echo.

echo [2/6] Your current IP addresses:
echo    Checking network configuration...
ipconfig | findstr /C:"IPv4 Address"
echo.

echo [3/6] Checking if server is bound to 0.0.0.0...
netstat -an | findstr "0.0.0.0:8000" >nul
if %errorlevel% equ 0 (
    echo    [OK] Server is bound to 0.0.0.0:8000 (accessible from network)
) else (
    echo    [WARNING] Server might be bound to 127.0.0.1 (only local access)
    echo    [FIX] Use: python manage.py runserver 0.0.0.0:8000
)
echo.

echo [4/6] Checking VPN status...
ipconfig | findstr "ProtonVPN" >nul
if %errorlevel% equ 0 (
    echo    [WARNING] ProtonVPN adapter detected!
    echo    [FIX] Disconnect VPN for local network access
) else (
    echo    [OK] No VPN detected
)
echo.

echo [5/6] Testing server accessibility...
echo    Testing localhost first...
powershell -Command "try { $response = Invoke-WebRequest -Uri 'http://localhost:8000/admin/' -Method Head -TimeoutSec 10 -ErrorAction Stop; Write-Host '    [OK] Local server accessible! Status:' $response.StatusCode } catch { Write-Host '    [ERROR] Local server error:' $_.Exception.Message }"
echo    Testing network IP...
powershell -Command "try { $response = Invoke-WebRequest -Uri 'http://172.16.37.58:8000/admin/' -Method Head -TimeoutSec 10 -ErrorAction Stop; Write-Host '    [OK] Network server accessible! Status:' $response.StatusCode } catch { Write-Host '    [WARNING] Network test failed:' $_.Exception.Message }"
echo    Note: Network test may fail even if server works due to Windows firewall or routing.
echo    If localhost works but network fails, check firewall settings.
echo.

echo [6/6] Checking config.js...
if exist "mobile_app\config.js" (
    findstr /C:"172.16.37.58" "mobile_app\config.js" >nul
    if %errorlevel% equ 0 (
        echo    [OK] Config.js contains correct IP address
    ) else (
        echo    [WARNING] Config.js might not have correct IP
    )
) else (
    echo    [ERROR] Config.js not found!
)
echo.

echo ============================================
echo Diagnostic Complete!
echo ============================================
echo.
echo Next Steps:
echo 1. If server is not running, start it with: python manage.py runserver 0.0.0.0:8000
echo 2. If VPN is active, disconnect it
echo 3. Test from mobile browser: http://172.16.37.58:8000/admin/
echo 4. If firewall blocks, allow Python through Windows Firewall
echo.
pause

