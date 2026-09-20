# Fix APK Connection Issues

## Problem
Mobile browser can access `http://172.16.37.58:8000/admin/` but APK app cannot connect.

## Root Causes

### 1. Android Blocks HTTP Traffic by Default
Android 9+ blocks cleartext (HTTP) traffic in production builds by default. Since your server uses HTTP (`http://172.16.37.58:8000`), Android blocks it.

### 2. APK Built with Old Config
If the APK was built before updating `config.js`, it might have the wrong URL.

## Solutions Applied

### ✅ Solution 1: Allow HTTP Traffic in Android
Updated `app.json` and created `app.config.js` to:
- Set `usesCleartextTraffic: true`
- Configure network security to allow HTTP connections

### ✅ Solution 2: Force Production URL in Config
Updated `config.js` to:
- Better detect standalone builds (APK)
- Force use of `PRODUCTION_URL` in APK builds
- Add debugging logs

## Next Steps: Rebuild APK

**You MUST rebuild the APK** for these changes to take effect:

### Step 1: Verify Config is Correct
Open `mobile_app/config.js` and verify:
```javascript
const PRODUCTION_URL = 'http://172.16.37.58:8000';
```

### Step 2: Rebuild APK
```bash
cd mobile_app
eas build --platform android --profile preview
```

### Step 3: Install New APK
1. Download the new APK from Expo dashboard
2. Uninstall old APK from your device
3. Install the new APK
4. Test connection

## Quick Test Before Rebuilding

If you want to test the config changes without rebuilding:

### Option 1: Test with Expo Go (Development)
```bash
cd mobile_app
npm start
```
Then scan QR code with Expo Go app. This uses `LOCAL_IP` which should work.

### Option 2: Check Current APK URL
The current APK might be using a different URL. Check the login screen - it should show the server URL at the top.

## Verification

After rebuilding and installing new APK:

1. **Open the app** - Check login screen shows: `Server: http://172.16.37.58:8000`
2. **Check connection status** - Should show "Connected" or "Good Connection"
3. **Try login** - Should connect automatically

## If Still Not Working

### Check 1: Verify Server is Running
```bash
python manage.py runserver 0.0.0.0:8000
```

### Check 2: Test from Mobile Browser
Open `http://172.16.37.58:8000/admin/` in mobile browser
- ✅ Works → Server is accessible
- ❌ Doesn't work → Network/firewall issue

### Check 3: Check App Logs
If you have access to device logs, check what URL the app is trying to use.

### Check 4: Network Security
Some networks block device-to-device communication. Try:
- Different Wi-Fi network
- Mobile hotspot
- Ensure both devices on same network

## Summary

**The fix is applied to the code**, but you need to **rebuild the APK** for it to work.

The changes ensure:
- ✅ Android allows HTTP traffic
- ✅ APK uses correct production URL
- ✅ Better connection detection
- ✅ Automatic retry logic

**Rebuild the APK now and it should work!**

