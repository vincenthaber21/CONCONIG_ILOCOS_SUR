# APK Build Documentation
## Genglo Printing Services — Self-Checkout Mobile App

---

## Table of Contents
1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Project Information](#project-information)
4. [Step 1 — Set Up Your Environment](#step-1--set-up-your-environment)
5. [Step 2 — Configure the Server URL](#step-2--configure-the-server-url)
6. [Step 3 — Install Dependencies](#step-3--install-dependencies)
7. [Step 4 — Log In to Expo / EAS](#step-4--log-in-to-expo--eas)
8. [Step 5 — Build the APK](#step-5--build-the-apk)
9. [Build Profiles Explained](#build-profiles-explained)
10. [Step 6 — Download the APK](#step-6--download-the-apk)
11. [Step 7 — Install the APK on Android](#step-7--install-the-apk-on-android)
12. [Switching EAS Accounts](#switching-eas-accounts)
13. [Troubleshooting](#troubleshooting)

---

## Overview

This app is a React Native / Expo mobile self-checkout client for the **Genglo Printing Services Cooperative Kiosk** system. The APK is built using **EAS Build** (Expo Application Services), which compiles the app in the cloud — no Android Studio or local Android SDK required.

---

## Prerequisites

Before you start, make sure the following are installed on your computer:

| Tool | Version | Download |
|------|---------|----------|
| Node.js | 18 or later | https://nodejs.org |
| npm | included with Node.js | — |
| Expo CLI | latest | `npm install -g expo-cli` |
| EAS CLI | latest | `npm install -g eas-cli` |
| Expo Account | free | https://expo.dev/signup |

> **Current Account:** `vhaber@dmmmsu.edu.ph`

> **Note:** You do NOT need Android Studio, Java, or the Android SDK. EAS Build handles everything in the cloud.

---

## Project Information

| Field | Value |
|-------|-------|
| App Name | Genglo Printing Services |
| Package Name | `com.coopkiosk.mobile` |
| Expo Slug | `coop-kiosk-mobile` |
| EAS Project ID | `d2cbe22c-3a59-4d9f-9c09-b7c0f672a671` |
| Entry Point | `node_modules/expo/AppEntry.js` |
| Expo SDK | ~54.0.0 |
| React Native | 0.81.5 |

---

## Step 1 — Set Up Your Environment

Open a terminal and navigate to the mobile app folder:

```bash
cd "d:\self_checkout _gen_glow\mobile_app"
```

---

## Step 2 — Configure the Server URL

Before building, make sure the app points to the correct Django backend server.

Open `mobile_app/config.js` and verify these two lines:

```js
const LOCAL_IP = 'https://7m700w9b-8000.asse.devtunnels.ms';
const PRODUCTION_URL = 'https://7m700w9b-8000.asse.devtunnels.ms';
```

> **Important:** The server URL must be accessible from the internet (not `localhost` or a local IP) when building with EAS, because the APK will run on a physical device that connects remotely. The dev tunnel URL above satisfies this requirement.
>
> If the dev tunnel URL changes (tunnels are session-based), update both values before rebuilding the APK.

---

## Step 3 — Install Dependencies

Inside the `mobile_app` folder, install all Node packages:

```bash
npm install
```

If you encounter memory errors during install, use:

```bash
cross-env NODE_OPTIONS=--max-old-space-size=4096 npm install
```

---

## Step 4 — Log In to Expo / EAS

Log in to your Expo account (required to use EAS Build):

```bash
eas login
```

Enter your Expo account email and password when prompted.

> **Active account:** `vhaber@dmmmsu.edu.ph`

To verify you are logged in:

```bash
eas whoami
```

---

## Step 5 — Build the APK

EAS Build provides three build profiles. Choose the one that fits your purpose:

### Opti on A — Preview Build (Recommended for testing)
Produces a standalone `.apk` file for internal distribution and testing on real devices.

```bash
eas build --platform android --profile preview
```

### Option B — Production Build
Produces a production-ready `.apk` for distribution.

```bash
eas build --platform android --profile production
```

### Option C — Development Build
Produces a development client `.apk` that connects to Expo Dev Tools for live debugging.

```bash
eas build --platform android --profile development
```

---

After running the command, EAS will:
1. Upload your project source code to Expo's build servers
2. Compile the Android APK in the cloud
3. Provide a URL to download the finished `.apk`

The build typically takes **5–15 minutes**. You can monitor progress at:
```
https://expo.dev/accounts/vhaber/projects/coop-kiosk-mobile/builds
```

---

## Build Profiles Explained

Defined in `eas.json`:

| Profile | Distribution | Build Type | Use Case |
|---------|-------------|-----------|---------|
| `development` | internal | APK | Live debugging with Expo Dev Client |
| `preview` | internal | APK | Internal testing on real devices |
| `production` | — | APK | Final release to users |

All three profiles output an `.apk` file (not an `.aab`), so they can all be sideloaded directly onto Android devices without going through the Play Store.

---

## Step 6 — Download the APK

When the build finishes, EAS CLI will print a download URL in the terminal, for example:

```
✔ Build finished.
Download it from: https://expo.dev/artifacts/eas/xxxxxxxx.apk
```

You can also find it at:
```
https://expo.dev/accounts/vhaber/projects/coop-kiosk-mobile/builds
```

Click the build entry and download the `.apk` file.

---

## Step 7 — Install the APK on Android

### Method 1 — Direct download on the Android device
1. Open the download URL directly in the device's browser.
2. Tap the downloaded `.apk` file.
3. If prompted, enable **Install from unknown sources** in Settings → Security.
4. Tap **Install**.

### Method 2 — Transfer via USB
1. Connect the Android device to your computer via USB.
2. Copy the `.apk` file to the device's storage (e.g., Downloads folder).
3. Use a file manager app on the device to locate and tap the `.apk`.
4. Follow the on-screen prompts to install.

### Method 3 — ADB (Android Debug Bridge)
If ADB is installed on your computer and USB debugging is enabled on the device:

```bash
adb install path\to\GengloPrintingServices.apk
```

---

## Switching EAS Accounts

If you need to switch to a different Expo/EAS account before building:

### Step 1 — Log out of the current account

```bash
eas logout
```

### Step 2 — Log in with the new account

```bash
eas login
```

Enter the new account's email/username and password when prompted.

### Step 3 — Verify the active account

```bash
eas whoami
```

### Step 4 — Proceed with the build

```bash
eas build --platform android --profile preview
```

> **Note:** The EAS project (`d2cbe22c-3a59-4d9f-9c09-b7c0f672a671`) is linked to the account that originally created it. If you switch to an account that does not have access to this project, the build will fail with a "project not found" error. Make sure the account you log in with has been granted access to the project at [expo.dev](https://expo.dev).

### Account Change History

| Date | Account | Action |
|------|---------|--------|
| April 18, 2026 | `vhaber@dmmmsu.edu.ph` | Switched to this account; build owner |

---

## Troubleshooting

### Build fails with "not logged in"
```bash
eas login
```

### Build fails with "project not found"
Make sure `eas.json` and `app.json` are present in the `mobile_app` folder and that `app.json` contains the correct EAS project ID:
```json
"extra": {
  "eas": {
    "projectId": "d2cbe22c-3a59-4d9f-9c09-b7c0f672a671"
  }
}
```

### App installs but cannot connect to the server
- Verify the Django backend is running and the dev tunnel is active.
- Open `config.js` and confirm `PRODUCTION_URL` is the current tunnel URL.
- Rebuild the APK after any URL change — the URL is bundled at build time.

### "Install blocked" on Android device
Go to **Settings → Security → Install unknown apps**, select your browser or file manager, and enable **Allow from this source**.

### npm install fails with memory error
```bash
cross-env NODE_OPTIONS=--max-old-space-size=4096 npm install
```

### Clear Expo cache before building
```bash
npm run clean
```
or
```bash
npm run clean:all
```

---

*Last updated: April 18, 2026 — Account switched to `vhaber@dmmmsu.edu.ph`*
