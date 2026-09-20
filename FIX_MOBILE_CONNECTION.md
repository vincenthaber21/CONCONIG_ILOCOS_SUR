# Fix Mobile App Connection Issues

## Your Current Setup
- **Wi-Fi IP**: `172.16.37.58` ✅ (This is correct)
- **VPN IP**: `10.2.0.2` ⚠️ (This might interfere)
- **Config.js**: Already set to `http://172.16.37.58:8000` ✅

## Common Issues & Solutions

### Issue 1: VPN Interference ⚠️ CRITICAL
**Problem**: ProtonVPN is active and routing traffic through VPN, which prevents local network access.

**Solution**:
1. **Disconnect ProtonVPN** before testing mobile app connection
2. Or configure VPN to allow local network traffic (split tunneling)
3. After disconnecting VPN, verify your IP:
   ```cmd
   ipconfig
   ```
   Make sure Wi-Fi IP is still `172.16.37.58`

### Issue 2: Server Not Running on 0.0.0.0
**Problem**: Server might be running on `127.0.0.1` which only allows local connections.

**Solution**:
1. **Stop current server** (Ctrl+C if running)
2. **Use the correct command**:
   ```cmd
   python manage.py runserver 0.0.0.0:8000
   ```
   Or use the provided script:
   ```cmd
   runserver_mobile.bat
   ```
3. **Verify** the server shows:
   ```
   Starting development server at http://0.0.0.0:8000/
   ```
   NOT:
   ```
   Starting development server at http://127.0.0.1:8000/
   ```

### Issue 3: Windows Firewall Blocking
**Problem**: Windows Firewall might be blocking port 8000.

**Solution**:
1. Open **Windows Defender Firewall**
2. Click **Allow an app or feature through Windows Defender Firewall**
3. Find **Python** in the list and check both **Private** and **Public**
4. If Python is not listed, click **Allow another app** and add Python
5. Or temporarily disable firewall for testing (not recommended for production)

**Quick PowerShell Fix**:
```powershell
# Run as Administrator
New-NetFirewallRule -DisplayName "Django Dev Server" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
```

### Issue 4: APK Built with Old Config
**Problem**: If you built the APK before updating `config.js`, it has the old URL.

**Solution**:
1. Rebuild the APK after ensuring `config.js` is correct:
   ```cmd
   cd mobile_app
   eas build --platform android --profile preview
   ```
2. Or update `PRODUCTION_URL` in `config.js` and rebuild

## Step-by-Step Fix Process

### Step 1: Disconnect VPN
1. Disconnect ProtonVPN completely
2. Verify Wi-Fi connection is active
3. Run `ipconfig` to confirm IP is `172.16.37.58`

### Step 2: Verify Config.js
Open `mobile_app/config.js` and ensure:
```javascript
const PRODUCTION_URL = 'http://172.16.37.58:8000';
```

### Step 3: Start Server Correctly
```cmd
cd C:\Users\PC\Desktop\self_checkout _gen_glow
python manage.py runserver 0.0.0.0:8000
```

**Verify output shows**: `Starting development server at http://0.0.0.0:8000/`

### Step 4: Test Server Accessibility
On your mobile device:
1. Open mobile browser
2. Go to: `http://172.16.37.58:8000/admin/`
3. If you see Django admin login → ✅ Server is accessible
4. If connection fails → Check firewall/VPN

### Step 5: Check Firewall
If Step 4 fails:
1. Open Windows Defender Firewall
2. Allow Python through firewall
3. Or run the PowerShell command above (as Administrator)

### Step 6: Test Mobile App
1. Open your APK
2. Try to login
3. If it fails, check the error message

## Quick Test Script

Run this to verify everything is set up correctly:

```cmd
@echo off
echo Checking Django Server Configuration...
echo.

echo 1. Checking if server is running...
netstat -an | findstr :8000
echo.

echo 2. Your current IP addresses:
ipconfig | findstr IPv4
echo.

echo 3. Testing server accessibility...
curl http://172.16.37.58:8000/admin/ -I
echo.

echo If you see HTTP/1.1 200 or 302, server is accessible!
pause
```

## Network Troubleshooting

### Verify Same Network
1. On mobile device, check Wi-Fi settings
2. Ensure it's connected to the same network as your computer
3. Mobile data won't work with local IP addresses

### Test Connection from Mobile Browser
1. Open mobile browser
2. Navigate to: `http://172.16.37.58:8000/api/mobile/health/`
3. Should see: `{"status":"ok","server_time":"..."}`
4. If this works, mobile app should work too

## Still Not Working?

### Check Django Logs
When you try to login from mobile app, check the Django server console:
- If you see requests coming in → Connection works, check credentials
- If no requests appear → Connection blocked (firewall/VPN/network)

### Verify Credentials
1. Test login from Django admin: `http://172.16.37.58:8000/admin/`
2. Verify member exists and has correct RFID/PIN
3. Check member is linked to a User account

### Common Error Messages

**"Cannot connect to server"**
- Server not running on 0.0.0.0:8000
- VPN interfering
- Firewall blocking
- Wrong IP in config.js

**"Network error"**
- Check internet connection
- Verify server is running
- Check CORS settings (should be OK)

**"Invalid credentials"**
- Check RFID and PIN are correct
- Verify member exists in database
- Check member is active

## Summary Checklist

- [ ] VPN disconnected
- [ ] Server running on `0.0.0.0:8000` (not `127.0.0.1:8000`)
- [ ] Config.js has correct IP: `http://172.16.37.58:8000`
- [ ] Firewall allows Python/port 8000
- [ ] Mobile device on same Wi-Fi network
- [ ] Can access `http://172.16.37.58:8000/admin/` from mobile browser
- [ ] APK rebuilt after config changes (if needed)
- [ ] Credentials are correct

## Need More Help?

1. Check Django server console for error messages
2. Test connection from mobile browser first
3. Verify network connectivity
4. Check firewall logs

