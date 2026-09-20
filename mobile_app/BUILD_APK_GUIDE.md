# 📱 Step-by-Step Guide: Building APK for Coop Kiosk Mobile App

This guide provides clear, step-by-step instructions to build a standalone APK file that can be installed on any Android device.

---

## ✅ Prerequisites Checklist

Before starting, ensure you have:

- [ ] **Node.js** (v14 or higher) - [Download here](https://nodejs.org/)
- [ ] **Expo Account** (free) - [Sign up at expo.dev](https://expo.dev)
- [ ] **Internet connection** (for cloud build)
- [ ] **Django server URL** ready (for API configuration)

---

## 🚀 Method 1: EAS Build (Recommended - Cloud Build)

This is the easiest method. Expo builds your APK in the cloud - no Android Studio needed!

### **STEP 1: Install EAS CLI**

Open your terminal/command prompt and run:

```bash
npm install -g eas-cli
```

**Wait for installation to complete.** You should see a success message.

---

### **STEP 2: Navigate to Mobile App Directory**

```bash
cd mobile_app
```

Make sure you're in the `mobile_app` folder.

---

### **STEP 3: Login to Expo**

```bash
eas login
```

**What happens:**
- If you have an Expo account: Enter your email and password
- If you don't have an account: 
  1. Press `Enter` to create one
  2. Follow the prompts to sign up (it's free!)
  3. Check your email for verification if needed

**Expected output:** `✓ Logged in as your-email@example.com`

---

### **STEP 4: Update API Configuration**

**⚠️ IMPORTANT:** Before building, you must set your production API URL.

1. Open `mobile_app/config.js` in a text editor
2. Find this line (around line 34):
   ```javascript
   const PRODUCTION_URL = 'http://172.16.37.58:8000';
   ```
3. Replace it with your production server URL:
   ```javascript
   const PRODUCTION_URL = 'https://your-production-server.com'; // Your server URL
   ```
   
   **Examples:**
   - Local network: `'http://192.168.1.100:8000'` (your computer's IP)
   - Production server: `'https://api.yourdomain.com'`
   - Cloud hosting: `'https://your-app.herokuapp.com'`

4. **Save the file**

---

### **STEP 5: Build the APK**

Run this command:

```bash
eas build --platform android --profile preview
```

**What happens:**
1. EAS will ask if you want to create an Android keystore (for signing)
   - Type `y` and press Enter (first time only)
   - It will be saved securely in Expo's cloud
2. The build will start in the cloud
3. You'll see a URL like: `https://expo.dev/accounts/your-account/builds/...`
4. **Build time:** 10-20 minutes (be patient!)

**Build Profiles Explained:**
- `preview` - ✅ **Recommended** - APK for testing/standalone installation
- `production` - For Play Store release (requires more setup)
- `development` - For development only

---

### **STEP 6: Monitor Build Progress**

You have two options:

**Option A: Watch in Terminal**
- The terminal will show build progress
- Wait until you see: `✓ Build finished`

**Option B: Check Online Dashboard**
1. Open the URL shown in terminal (or go to [expo.dev](https://expo.dev))
2. Click on "Builds" in the dashboard
3. Watch the progress bar

---

### **STEP 7: Download Your APK**

Once the build is complete:

**Method 1: From Terminal**
```bash
eas build:list
```
This shows your recent builds. Find the download URL.

**Method 2: From Expo Dashboard**
1. Go to [expo.dev](https://expo.dev)
2. Click on "Builds"
3. Find your completed build
4. Click "Download" button

**The APK file will be named something like:** `coop-kiosk-mobile-1.0.0.apk`

---

### **STEP 8: Install APK on Android Device**

1. **Transfer APK to your Android device:**
   - Email it to yourself
   - Use USB file transfer
   - Upload to Google Drive/Dropbox
   - Use ADB: `adb install app.apk`

2. **Enable Unknown Sources:**
   - Go to **Settings** > **Security** (or **Apps** > **Special Access**)
   - Enable **"Install from Unknown Sources"** or **"Install Unknown Apps"**
   - Select your file manager app (Files, Chrome, etc.)

3. **Install:**
   - Open the APK file on your device
   - Tap **"Install"**
   - Wait for installation
   - Tap **"Open"** to launch the app

**🎉 Done! Your app is now installed!**

---

## 🛠️ Method 2: Local Build (Advanced - Optional)

**⚠️ Only use this if you need to build locally without internet or have specific requirements.**

### Prerequisites for Local Build

- [ ] **Android Studio** - [Download here](https://developer.android.com/studio) (~1GB)
- [ ] **Java Development Kit (JDK)** - Version 11 or higher
- [ ] **Android SDK** - Installed via Android Studio
- [ ] **Environment Variables** - Set `ANDROID_HOME` and `JAVA_HOME`

### Local Build Steps

1. **Install EAS CLI** (if not already installed):
   ```bash
   npm install -g eas-cli
   ```

2. **Navigate to mobile_app directory:**
   ```bash
   cd mobile_app
   ```

3. **Prebuild native code:**
   ```bash
   npx expo prebuild --platform android
   ```
   This generates the native Android project files.

4. **Build locally:**
   ```bash
   eas build --platform android --profile preview --local
   ```

**Note:** Local builds require significant setup (Android Studio, JDK, SDK) and may take 30-60 minutes. **Cloud builds (Method 1) are strongly recommended for most users.**

---

## 🔧 Troubleshooting

### ❌ Build Fails with "No credentials found"

**Solution:**
```bash
eas credentials
```
Follow the prompts to set up Android credentials. EAS will guide you through the process.

---

### ⏳ Build Takes Too Long

**Normal:** Cloud builds take 10-20 minutes. This is expected!
- First build: ~20 minutes
- Subsequent builds: ~10-15 minutes

**If it's been over 30 minutes:**
- Check the Expo dashboard for error messages
- Try canceling and restarting the build

---

### 📱 APK Won't Install on Device

**Checklist:**
- [ ] "Install from Unknown Sources" is enabled in Android settings
- [ ] APK file is not corrupted (try downloading again)
- [ ] Device has enough storage space
- [ ] Android version is compatible (Android 5.0+)

**Still not working?**
- Try installing via ADB: `adb install app.apk`
- Check device logs: `adb logcat`

---

### 🌐 API Connection Issues After Installation

**Problem:** App can't connect to your server

**Solutions:**
1. **Verify PRODUCTION_URL in config.js:**
   - Make sure it's correct before building
   - Rebuild APK if you changed it

2. **Check server accessibility:**
   - Server must be running
   - Server must be accessible from mobile device's network
   - Firewall must allow connections on port 8000 (or your port)

3. **Test connection:**
   - Open the URL in mobile browser: `http://your-server-ip:8000/api/mobile/health/`
   - Should return JSON response

---

### 🔐 Build Fails with Authentication Error

**Solution:**
```bash
eas logout
eas login
```
Re-authenticate with your Expo account.

---

### 📦 "npm install" Errors

**Solution:**
```bash
cd mobile_app
npm install
```
Make sure all dependencies are installed before building.

---

## 📋 Pre-Build Checklist

Before building your APK, make sure:

- [ ] **API URL configured:** Updated `PRODUCTION_URL` in `config.js`
- [ ] **Version number:** Check `app.json` version (e.g., "1.0.0")
- [ ] **App name:** Verify app name in `app.json`
- [ ] **Dependencies installed:** Run `npm install` in `mobile_app` folder
- [ ] **Expo account:** Logged in with `eas login`
- [ ] **Internet connection:** Stable connection for cloud build

---

## 🎯 Quick Reference (TL;DR)

**Fastest way to build APK:**

```bash
# 1. Install EAS CLI
npm install -g eas-cli

# 2. Login to Expo
eas login

# 3. Navigate to mobile app
cd mobile_app

# 4. Update config.js with your PRODUCTION_URL

# 5. Build APK
eas build --platform android --profile preview

# 6. Download from Expo dashboard when done
# 7. Install on Android device
```

**Total time:** ~20-30 minutes (mostly waiting for build)

---

## 📝 Production Release Checklist

Before releasing your APK to users:

- [ ] ✅ **API URL:** Set `PRODUCTION_URL` in `config.js` to production server
- [ ] ✅ **Version:** Update version in `app.json` (e.g., "1.0.1")
- [ ] ✅ **Testing:** Test APK on multiple devices and Android versions
- [ ] ✅ **Features:** Verify all features work correctly
- [ ] ✅ **Permissions:** Review Android permissions in `app.json`
- [ ] ✅ **App Signing:** Credentials set up via `eas credentials`
- [ ] ✅ **Server:** Production server is running and accessible
- [ ] ✅ **Backup:** Keep a copy of the APK file

---

## 📚 Additional Resources

- [EAS Build Documentation](https://docs.expo.dev/build/introduction/)
- [Expo Account Dashboard](https://expo.dev)
- [Android APK Installation Guide](https://support.google.com/android/answer/9064445)
- [Expo Community Forums](https://forums.expo.dev/)

---

## 💡 Tips & Best Practices

1. **Version Management:** Increment version in `app.json` for each release
2. **Build Profiles:** Use `preview` for testing, `production` for final release
3. **API Testing:** Test API connection before building APK
4. **Multiple Builds:** Keep old APK files for rollback if needed
5. **Network:** Ensure stable internet during cloud build
6. **Credentials:** EAS manages signing keys automatically (first build only)

---

**Need Help?** Check the troubleshooting section above or visit [Expo Forums](https://forums.expo.dev/)

## Additional Resources

- [EAS Build Documentation](https://docs.expo.dev/build/introduction/)
- [Expo Account Dashboard](https://expo.dev)
- [Android APK Installation Guide](https://support.google.com/android/answer/9064445)

