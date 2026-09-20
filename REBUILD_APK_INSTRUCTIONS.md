# 🔧 Rebuild APK - Connection Fix Instructions

## ✅ Changes Made

I've fixed the APK connection issues:

1. **Android HTTP Traffic** - Enabled cleartext traffic for HTTP connections
2. **Production URL Detection** - Improved detection of standalone builds
3. **Config Updates** - Ensured APK uses `PRODUCTION_URL` correctly
4. **Debug Display** - Added URL display in login screen

## 🚀 Rebuild APK Now

**You MUST rebuild the APK** for these fixes to work!

### Quick Rebuild Steps:

```bash
# 1. Navigate to mobile app directory
cd mobile_app

# 2. Verify config is correct (should show http://172.16.37.58:8000)
# Open config.js and check PRODUCTION_URL

# 3. Rebuild APK
eas build --platform android --profile preview
```

### Detailed Steps:

#### Step 1: Verify Configuration
Open `mobile_app/config.js` and verify:
```javascript
const PRODUCTION_URL = 'http://172.16.37.58:8000';
```

#### Step 2: Login to Expo (if needed)
```bash
cd mobile_app
eas login
```

#### Step 3: Build APK
```bash
eas build --platform android --profile preview
```

**Build time:** 10-20 minutes

#### Step 4: Download and Install
1. Wait for build to complete
2. Download APK from Expo dashboard or use:
   ```bash
   eas build:list
   ```
3. **Uninstall old APK** from your device
4. Install the new APK
5. Test connection

## ✅ What Was Fixed

### 1. Android Network Security
- Added `usesCleartextTraffic: true` to allow HTTP connections
- Configured network security to permit cleartext traffic
- This fixes Android blocking HTTP traffic in production builds

### 2. Production URL Detection
- Improved detection of standalone builds (APK)
- Forces use of `PRODUCTION_URL` in APK builds
- Better handling of `__DEV__` flag

### 3. Debug Information
- Login screen now shows which URL is being used
- Helps verify correct configuration

## 🧪 Testing After Rebuild

1. **Open the app** - Check login screen shows:
   ```
   Server URL: http://172.16.37.58:8000
   ```

2. **Check connection status** - Should show:
   - "✓ Connected" (green indicator)
   - Or "⚠ Offline - Will try to connect" (but will auto-connect)

3. **Try login** - Enter credentials and tap Login
   - App will automatically connect
   - Should login successfully

## 🔍 Verification Checklist

- [ ] Config.js has correct `PRODUCTION_URL`: `http://172.16.37.58:8000`
- [ ] APK rebuilt with new configuration
- [ ] Old APK uninstalled from device
- [ ] New APK installed
- [ ] Server is running: `python manage.py runserver 0.0.0.0:8000`
- [ ] Mobile browser can access: `http://172.16.37.58:8000/admin/`
- [ ] App shows correct server URL on login screen
- [ ] Connection status shows "Connected" or auto-connects

## ⚠️ Important Notes

1. **Must Rebuild**: Old APK won't work - you MUST rebuild
2. **Uninstall Old APK**: Remove old version before installing new one
3. **Server Must Be Running**: Django server must be on `0.0.0.0:8000`
4. **Same Network**: Both devices must be on same Wi-Fi network

## 🐛 If Still Not Working

### Check 1: Verify Server URL in App
Open app and check login screen - it should show:
```
Server URL: http://172.16.37.58:8000
```

If it shows a different URL, the APK wasn't rebuilt with new config.

### Check 2: Test Mobile Browser
Open `http://172.16.37.58:8000/admin/` in mobile browser
- ✅ Works → Server is accessible, APK should work
- ❌ Doesn't work → Network/firewall issue

### Check 3: Check Server Logs
When you try to login from app, check Django server console:
- If you see requests → Connection works!
- If no requests → Connection blocked

### Check 4: Network Settings
- Ensure both devices on same Wi-Fi
- Check firewall allows port 8000
- Try different Wi-Fi network

## 📝 Summary

**The code is fixed!** Now rebuild the APK:

```bash
cd mobile_app
eas build --platform android --profile preview
```

After rebuilding and installing, your APK should connect automatically! 🎉

