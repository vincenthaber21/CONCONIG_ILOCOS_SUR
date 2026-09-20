// API Configuration
// ===================
// IMPORTANT: Update this with your Django server URL
//
// ⚠️ CRITICAL: Start Django server with 0.0.0.0:8000 for mobile access!
//   Use: python manage.py runserver 0.0.0.0:8000
//   Or use the provided script: runserver_mobile.bat (Windows) or runserver_mobile.sh (Mac/Linux)
//
// For local development (testing on physical device):
//   1. Start Django server: python manage.py runserver 0.0.0.0:8000
//   2. Find your computer's IP address:
//      - Windows: ipconfig (look for IPv4 Address)
//      - Mac/Linux: ifconfig or ip addr
//   3. Make sure your phone and computer are on the same Wi-Fi network
//   4. Update LOCAL_IP below (e.g., 'http://192.168.1.100:8000')
//
// For Android Emulator:
//   - Change LOCAL_IP to 'http://10.0.2.2:8000'
//
// For iOS Simulator:
//   - Change LOCAL_IP to 'http://localhost:8000'
//
// For production:
//   Option 1: If you have a production server with domain/IP:
//     - Set PRODUCTION_URL to your server URL (e.g., 'https://api.yourdomain.com' or 'http://your-server-ip:8000')
//   Option 2: If testing APK and connecting to local server (same network):
//     - Set PRODUCTION_URL to your computer's IP address (same as LOCAL_IP)
//     - Make sure Django server is running and accessible from mobile device
//   Option 3: If deploying to cloud (Heroku, AWS, etc.):
//     - Set PRODUCTION_URL to your cloud server URL (e.g., 'https://your-app.herokuapp.com')

// Default configuration - UPDATE THIS!
const LOCAL_IP = 'https://7m700w9b-8000.asse.devtunnels.ms'; // ⚠️ Your computer's IP address for development
const PRODUCTION_URL = 'https://7m700w9b-8000.asse.devtunnels.ms'; // ⚠️ For APK: Use your server IP/domain here


// const LOCAL_IP = 'https://*.trycloudflare.com'; // ⚠️ Your computer's IP address for development
// const PRODUCTION_URL = 'https://*.trycloudflare.com'; // ⚠️ For APK: Use your server IP/domain here


// Examples:
//   - Local testing: 'http://172.16.37.58:8000' (your current IP)
//   - Production: 'https://api.yourdomain.com' or 'http://your-server-ip:8000'
//   - Cloud: 'https://your-app.herokuapp.com'

// Validate URL format
const validateUrl = (url) => {
  if (!url) return false;
  try {
    const parsed = new URL(url);
    return ['http:', 'https:'].includes(parsed.protocol);
  } catch {
    return false;
  }
};

// Normalize URL (remove trailing slash, ensure proper format)
const normalizeUrl = (url) => {
  if (!url) return url;
  return url.trim().replace(/\/+$/, '');
};

// Validate and normalize URLs
const normalizedLocal = normalizeUrl(LOCAL_IP);
const normalizedProduction = normalizeUrl(PRODUCTION_URL);

// Validate URLs
if (!validateUrl(normalizedLocal)) {
  console.warn(`Invalid LOCAL_IP: ${LOCAL_IP}`);
}
if (!validateUrl(normalizedProduction)) {
  console.warn(`Invalid PRODUCTION_URL: ${PRODUCTION_URL}`);
}

// Auto-select URL based on environment
// In production APK builds, __DEV__ is false, so PRODUCTION_URL will be used
// For development with Expo Go, __DEV__ is true, so LOCAL_IP will be used
// FORCE PRODUCTION_URL for APK builds - don't rely on __DEV__ alone
// Check if we're in a standalone build (APK) by checking if __DEV__ is explicitly false
// or if we're not in Expo Go (no expo-updates available)
let isStandaloneBuild = false;
try {
  // In standalone builds, __DEV__ is false and we don't have expo-updates
  if (typeof __DEV__ !== 'undefined' && __DEV__ === false) {
    isStandaloneBuild = true;
  }
  // Also check if we're in a production build environment
  if (typeof process !== 'undefined' && process.env && process.env.NODE_ENV === 'production') {
    isStandaloneBuild = true;
  }
} catch (e) {
  // If we can't determine, assume production build for safety
  isStandaloneBuild = !__DEV__;
}

// Use PRODUCTION_URL for standalone builds (APK), LOCAL_IP for development
export const API_BASE_URL = (isStandaloneBuild || !__DEV__) ? normalizedProduction : normalizedLocal;

// Log the URL being used for debugging (only in development)
if (__DEV__) {
  console.log('🔧 API Configuration:', {
    isStandaloneBuild,
    __DEV__,
    usingUrl: API_BASE_URL,
    localUrl: normalizedLocal,
    productionUrl: normalizedProduction
  });
}

// Export both URLs for debugging
export const getApiUrl = () => API_BASE_URL;
export const getLocalUrl = () => normalizedLocal;
export const getProductionUrl = () => normalizedProduction;

// Validate current API base URL
export const isApiUrlValid = () => validateUrl(API_BASE_URL);

export const API_ENDPOINTS = {
  HEALTH: `${API_BASE_URL}/api/mobile/health/`,
  LOGIN: `${API_BASE_URL}/api/mobile/login/`,
  LOGOUT: `${API_BASE_URL}/api/mobile/logout/`,
  ACCOUNT_INFO: `${API_BASE_URL}/api/mobile/account/`,
  ACCOUNT_SUMMARY: `${API_BASE_URL}/api/mobile/account/summary/`,
  TRANSACTIONS: `${API_BASE_URL}/api/mobile/transactions/`,
  BALANCE_TRANSACTIONS: `${API_BASE_URL}/api/mobile/balance-transactions/`,
  SEARCH_MEMBER: `${API_BASE_URL}/api/mobile/search-member/`,
  REQUEST_TRANSFER_OTP: `${API_BASE_URL}/api/mobile/fund-transfer/request-otp/`,
  VERIFY_TRANSFER_OTP: `${API_BASE_URL}/api/mobile/fund-transfer/verify-otp/`,
  REQUEST_BIOMETRIC_OTP: `${API_BASE_URL}/api/mobile/biometric/request-otp/`,
  VERIFY_BIOMETRIC_OTP: `${API_BASE_URL}/api/mobile/biometric/verify-otp/`,
  PRODUCTS: `${API_BASE_URL}/api/mobile/products/`,
  ADMIN_IMPORTANT_DETAILS: `${API_BASE_URL}/api/mobile/admin/important-details/`,
  ADMIN_CHECKOUT_QUEUE_STATUS: `${API_BASE_URL}/api/mobile/admin/checkout-queue-status/`,
  ADMIN_OPERATIONAL_WATCHLIST: `${API_BASE_URL}/api/mobile/admin/operational-watchlist/`,
  // QR Transfer
  QR_MY_CODE: `${API_BASE_URL}/api/mobile/qr/my-code/`,
  QR_SCAN: `${API_BASE_URL}/api/mobile/qr/scan/`,
  QR_REGENERATE: `${API_BASE_URL}/api/mobile/qr/regenerate/`,
  // Refund
  REQUEST_REFUND: `${API_BASE_URL}/api/mobile/transactions/request-refund/`,
};

