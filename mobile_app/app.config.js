// Dynamic app configuration
// This ensures Android allows HTTP traffic for local development
//
// Branding — Django admin:
//   Store profile (/admin/admin_panel/storeprofile/) → Logo → assets/icon.png (+ favicon, splash) via npm run sync:icon
//   Kiosk config → System name → assets/generated-brand-meta.json → expo.name below
//   Launcher + Android adaptive foreground both use ./assets/icon.png (same store logo).
//   EAS Build runs sync via eas-build-post-install (non-fatal if the API is unreachable).

const fs = require('fs');
const path = require('path');

function readGeneratedBrandName() {
  try {
    const metaPath = path.join(__dirname, 'assets', 'generated-brand-meta.json');
    if (fs.existsSync(metaPath)) {
      const j = JSON.parse(fs.readFileSync(metaPath, 'utf8'));
      const n = (j.system_name || '').trim();
      if (n) return n.slice(0, 48);
    }
  } catch (_) {
    /* keep fallback */
  }
  return 'Self Checkout';
}

module.exports = {
  expo: {
    name: readGeneratedBrandName(),
    slug: "coop-kiosk-mobile",
    version: "1.0.2",
    orientation: "portrait",
    icon: "./assets/icon.png",
    userInterfaceStyle: "light",
    splash: {
      image: "./assets/splash.png",
      resizeMode: "contain",
      backgroundColor: "#ffffff"
    },
    assetBundlePatterns: [
      "**/*"
    ],
    ios: {
      supportsTablet: true,
      bundleIdentifier: "com.coopkiosk.mobile",
      infoPlist: {
        NSCameraUsageDescription:
          "Camera access is required to scan member QR codes for fund transfers.",
        NSPhotoLibraryUsageDescription:
          "Photo library access lets you pick an image of a QR code to select a transfer recipient.",
      },
    },
    android: {
      adaptiveIcon: {
        foregroundImage: "./assets/icon.png",
        backgroundColor: "#ED1C24"
      },
      package: "com.coopkiosk.mobile",
      // CRITICAL: Allow HTTP (cleartext) traffic for local network connections
      usesCleartextTraffic: true,
      // Network security config to allow HTTP connections
      networkSecurityConfig: {
        cleartextTrafficPermitted: true
      },
      permissions: ["CAMERA"],
    },
    web: {
      favicon: "./assets/favicon.png"
    },
    updates: {
      url: "https://u.expo.dev/4a9bc73a-f026-4cbd-a850-2a6dccbc0222"
    },
    runtimeVersion: {
      policy: "appVersion"
    },
    extra: {
      eas: {
        projectId: "4a9bc73a-f026-4cbd-a850-2a6dccbc0222"
      }
    }
  }
};

