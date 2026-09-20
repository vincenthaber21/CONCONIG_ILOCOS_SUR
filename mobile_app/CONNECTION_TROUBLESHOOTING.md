# Connection Troubleshooting Guide

## Enhanced Connection Features

The mobile app now includes improved connection handling with:

1. **Automatic Retry Logic** - Retries failed requests up to 3 times with exponential backoff
2. **Connection Testing** - Test server connectivity before login
3. **Better Error Messages** - Clear, actionable error messages
4. **Increased Timeouts** - 20 second timeout for slower mobile networks
5. **Multiple Connection Attempts** - Tests multiple endpoints to verify server reachability

## Common Connection Issues

### Issue: "Cannot connect to server"

**Possible Causes:**
1. Django server is not running
2. Wrong server URL in `config.js`
3. Devices are on different networks
4. Firewall blocking connections
5. IP address changed

**Solutions:**

1. **Verify Django Server is Running:**
   ```bash
   # ✅ CORRECT - Use this for mobile app access
   python manage.py runserver 0.0.0.0:8000
   
   # ❌ WRONG - This won't work for mobile devices
   python manage.py runserver
   ```
   
   **Why?** 
   - Default `runserver` binds to `127.0.0.1` (localhost only)
   - Mobile devices need `0.0.0.0` to access from network
   - Use the provided script: `runserver_mobile.bat` (Windows) or `runserver_mobile.sh` (Mac/Linux)
   
   **Quick Check:**
   - If server shows "Starting development server at http://127.0.0.1:8000/" → ❌ Won't work for mobile
   - If server shows "Starting development server at http://0.0.0.0:8000/" → ✅ Will work for mobile

2. **Check Server URL in config.js:**
   - Open `mobile_app/config.js`
   - Verify `PRODUCTION_URL` matches your server IP/domain
   - For local testing: Use your computer's IP address (e.g., `http://192.168.1.100:8000`)
   - Find your IP: Windows `ipconfig`, Mac/Linux `ifconfig`

3. **Ensure Same Network:**
   - Both your computer (Django server) and mobile device must be on the same Wi-Fi network
   - Mobile data won't work with local IP addresses

4. **Check Firewall:**
   - Windows: Allow Python/Django through Windows Firewall
   - Mac: System Preferences > Security & Privacy > Firewall
   - Linux: Check iptables/ufw settings

5. **Verify IP Address:**
   - IP addresses can change when reconnecting to Wi-Fi
   - Update `PRODUCTION_URL` in `config.js` if IP changed
   - Consider using a static IP or domain name

### Issue: "Request timeout"

**Solutions:**
- Check internet connection speed
- Verify server is not overloaded
- Try the "Test Connection" button in the app
- Increase timeout in `services/api.js` if needed (currently 20 seconds)

### Issue: "Network error"

**Solutions:**
- Check mobile device internet connection
- Verify server is accessible from device (try opening server URL in mobile browser)
- Check CORS settings in Django `settings.py`
- Ensure `CORS_ALLOW_ALL_ORIGINS = True` when `DEBUG = True`

## Testing Connection

The app includes a "Test Connection" button on the login screen that:
- Tests server connectivity
- Shows current server URL
- Provides detailed error messages
- Attempts multiple connection methods

## Configuration for Different Scenarios

### Local Development (Same Network)
```javascript
const PRODUCTION_URL = 'http://YOUR_COMPUTER_IP:8000';
// Example: 'http://192.168.1.100:8000'
```

### Production Server (Domain)
```javascript
const PRODUCTION_URL = 'https://api.yourdomain.com';
```

### Production Server (IP Address)
```javascript
const PRODUCTION_URL = 'http://123.456.789.0:8000';
```

### Cloud Deployment (Heroku, AWS, etc.)
```javascript
const PRODUCTION_URL = 'https://your-app.herokuapp.com';
```

## Important Notes

1. **Rebuild APK After Config Changes:**
   - After changing `PRODUCTION_URL` in `config.js`, you must rebuild the APK:
   ```bash
   cd mobile_app
   eas build --platform android --profile preview
   ```

2. **HTTP vs HTTPS:**
   - Use `http://` for local development
   - Use `https://` for production (required for secure connections)
   - Some networks block HTTP, so HTTPS is recommended

3. **Port Numbers:**
   - Default Django port is 8000
   - If using a different port, include it in the URL: `http://ip:PORT`

4. **Network Requirements:**
   - For local IP addresses, both devices must be on the same network
   - For domain names, any network connection works
   - Mobile data works with domain names, not local IPs

## Debugging Steps

1. **Test Server Accessibility:**
   - Open server URL in mobile browser: `http://YOUR_IP:8000/admin/`
   - If it loads, server is accessible
   - If not, check network/firewall settings

2. **Check Django Logs:**
   - Look at Django server console for incoming requests
   - If no requests appear, connection is blocked before reaching server

3. **Use Test Connection Button:**
   - Tap "Test Connection" in the app
   - Review the detailed error message
   - Follow the troubleshooting steps provided

4. **Verify CORS Settings:**
   - Ensure `CORS_ALLOW_ALL_ORIGINS = True` in development
   - Check `CORS_ALLOW_CREDENTIALS = True`
   - Verify `CorsMiddleware` is in `MIDDLEWARE` (should be near top)

## After Making Changes

1. Update `config.js` with correct `PRODUCTION_URL`
2. Rebuild APK: `eas build --platform android --profile preview`
3. Install new APK on device
4. Test connection using "Test Connection" button
5. Try logging in

## Still Having Issues?

1. Check Django server console for errors
2. Verify mobile device can access server URL in browser
3. Test with "Test Connection" button for detailed diagnostics
4. Ensure both devices are on the same network (for local IPs)
5. Check firewall and network security settings

