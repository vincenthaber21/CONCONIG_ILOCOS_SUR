# OTA Update Guide — Deploy New App Versions Without Rebuilding

## Genglo Printing Services — Self-Checkout Mobile App

---

## Overview

**EAS Update** lets you push JavaScript/asset changes to already-installed APKs over-the-air (OTA) — no new build required. Users get the update silently on their next app launch.

> **What can be updated OTA:** All JavaScript code, screens, logic, styles, assets (images, fonts).  
> **What requires a full rebuild:** Native code changes, new native packages, changes to `app.json` permissions or SDK version.

---

## Table of Contents

1. [One-Time Setup (do this once, then rebuild once)](#1-one-time-setup)
2. [Publishing an OTA Update](#2-publishing-an-ota-update)
3. [Verifying the Update](#3-verifying-the-update)
4. [Branch Strategy](#4-branch-strategy)
5. [Rolling Back an Update](#5-rolling-back-an-update)
6. [Troubleshooting](#6-troubleshooting)

---

## 1. One-Time Setup

This setup is required **once**. After completing it you will rebuild the APK a single time, and all future JS changes can be deployed via `eas update` without rebuilding.

### Step 1 — Install expo-updates

```bash
cd "d:\self_checkout _gen_glow\mobile_app"
npx expo install expo-updates
```

### Step 2 — Configure app.json

Add the `updates` and `runtimeVersion` keys inside the `"expo"` object in `app.json`:

```json
{
  "expo": {
    "name": "Genglo Printing Services",
    "slug": "coop-kiosk-mobile",
    "version": "1.0.1",
    "runtimeVersion": {
      "policy": "appVersion"
    },
    "updates": {
      "url": "https://u.expo.dev/4a9bc73a-f026-4cbd-a850-2a6dccbc0222",
      "enabled": true,
      "checkAutomatically": "ON_LOAD",
      "fallbackToCacheTimeout": 0
    },
    ...
  }
}
```

> **Project ID:** `4a9bc73a-f026-4cbd-a850-2a6dccbc0222`  
> The `url` must always be `https://u.expo.dev/<your-project-id>`.

### Step 3 — Add channels to eas.json

Add a `channel` field to each build profile in `eas.json`:

```json
{
  "cli": {
    "version": ">= 5.2.0",
    "appVersionSource": "remote"
  },
  "build": {
    "development": {
      "developmentClient": true,
      "distribution": "internal",
      "android": { "buildType": "apk" },
      "channel": "development"
    },
    "preview": {
      "distribution": "internal",
      "android": { "buildType": "apk" },
      "channel": "preview"
    },
    "production": {
      "android": { "buildType": "apk" },
      "channel": "production"
    }
  },
  "submit": {
    "production": {}
  }
}
```

### Step 4 — Rebuild the APK once

This final rebuild embeds the `expo-updates` runtime and the channel configuration into the APK. After this, no further rebuilds are needed for JS-only changes.

```bash
eas build --platform android --profile preview
```

Install this new APK on all devices. From this point forward, use `eas update` to deploy changes.

---

## 2. Publishing an OTA Update

Use this workflow whenever you make JavaScript/asset changes and want to deploy them without building a new APK.

### Step 1 — Make your code changes

Edit any screens, components, services, or assets inside `mobile_app/`.

### Step 2 — Log in (if not already)

```bash
eas whoami
```

If not logged in:

```bash
eas login
```

Use account: `vhaber@dmmmsu.edu.ph`

### Step 3 — Publish the update

```bash
eas update --branch preview --message "Describe what changed"
```

**Examples:**

```bash
# Bug fix
eas update --branch preview --message "Fix cart total calculation on checkout screen"

# New feature
eas update --branch preview --message "Add member balance display on home screen"

# Config change
eas update --branch preview --message "Update server URL to new tunnel"
```

EAS will:
1. Bundle your JavaScript locally
2. Upload the bundle to Expo's CDN
3. Associate it with the `preview` channel
4. All installed APKs on the `preview` channel will receive the update on next launch

### Step 4 — Notify testers / staff

Users do not need to do anything. The update is applied automatically the next time the app is opened.

> If the app is already open, the update will apply on the **next cold launch** (full close and reopen).

---

## 3. Verifying the Update

### Check update status on expo.dev

```
https://expo.dev/accounts/vhaber/projects/coop-kiosk-mobile/updates
```

### Check from the terminal

```bash
eas update:list
```

### View details of a specific branch

```bash
eas update:list --branch preview
```

---

## 4. Branch Strategy

| EAS Branch | EAS Build Profile | Purpose |
|------------|------------------|---------|
| `preview` | `preview` | Testing on real devices before going live |
| `production` | `production` | Stable version deployed to all users |
| `development` | `development` | Active development / debugging |

To publish to production instead of preview:

```bash
eas update --branch production --message "Release v1.1 — improved checkout flow"
```

---

## 5. Rolling Back an Update

If a published update causes issues, re-publish the previous working code.

### Option A — Republish a previous update by ID

```bash
# List updates to find the good update's ID
eas update:list --branch preview

# Re-publish a specific update to the same branch
eas update --branch preview --republish --group <update-group-id>
```

### Option B — Revert your code and re-publish

```bash
# Undo changes in your code (git or manual)
git revert HEAD

# Re-publish
eas update --branch preview --message "Revert: fix regression from last update"
```

---

## 6. Troubleshooting

### Update published but app is not receiving it

- Fully close and reopen the app (background is not enough — force-quit it).
- Confirm the installed APK was built with the matching channel (`preview`).
- APKs built before Step 4 of the one-time setup do NOT support OTA updates.

### "No compatible update found"

The `runtimeVersion` of the published update must match the installed APK. If you changed `app.json` `version` or native dependencies since the last build, you must rebuild the APK.

### "expo-updates not found" error on publish

Run the install step again:

```bash
npx expo install expo-updates
```

### Need to change the server URL without rebuilding?

Update `config.js`:

```js
const LOCAL_IP = 'https://<new-tunnel>.asse.devtunnels.ms';
const PRODUCTION_URL = 'https://<new-tunnel>.asse.devtunnels.ms';
```

Then publish via `eas update`. Since `config.js` is JavaScript, it is included in the OTA bundle — no rebuild needed.

---

## Quick Reference

| Action | Command |
|--------|---------|
| Publish update to preview testers | `eas update --branch preview --message "..."` |
| Publish update to all users | `eas update --branch production --message "..."` |
| List published updates | `eas update:list` |
| Roll back to a previous update | `eas update --branch preview --republish --group <id>` |
| Check logged-in account | `eas whoami` |

---

*Last updated: April 18, 2026*
