@echo off
REM ============================================
REM Windows Firewall Fix for Django Server
REM ============================================
echo.
echo This script will add a firewall rule to allow Django server on port 8000
echo.
echo NOTE: This requires Administrator privileges!
echo.
pause

REM Check if running as administrator
net session >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] This script must be run as Administrator!
    echo.
    echo Right-click and select "Run as administrator"
    echo.
    pause
    exit /b 1
)

echo.
echo Adding firewall rule for Django development server...
echo.

REM Add firewall rule for port 8000
netsh advfirewall firewall add rule name="Django Dev Server Port 8000" dir=in action=allow protocol=TCP localport=8000

if %errorlevel% equ 0 (
    echo [OK] Firewall rule added successfully!
    echo.
    echo Django server on port 8000 is now allowed through Windows Firewall.
) else (
    echo [ERROR] Failed to add firewall rule.
    echo.
    echo Please manually add the rule:
    echo 1. Open Windows Defender Firewall
    echo 2. Click "Advanced settings"
    echo 3. Click "Inbound Rules" -> "New Rule"
    echo 4. Select "Port" -> TCP -> Specific local ports: 8000
    echo 5. Allow the connection
    echo 6. Apply to all profiles
)

echo.
pause

