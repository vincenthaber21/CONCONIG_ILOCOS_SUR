# Mobile App Setup Guide

This guide explains how to set up and use the mobile app for viewing account balance and transaction information.

## Overview

The mobile app consists of two main components:
1. **Django REST API** (`mobile_api` app) - Backend API endpoints
2. **React Native Mobile App** (`mobile_app` directory) - Frontend mobile application

## Backend Setup

### 1. Install Dependencies

Install the new dependency for CORS support:

```bash
# Using uv (recommended)
uv pip install django-cors-headers

# Or using pip
pip install django-cors-headers
```

### 2. Run Migrations

The `mobile_api` app doesn't require any migrations as it uses existing models from `members` and `transactions` apps.

### 3. Start Django Server

**⚠️ IMPORTANT for Mobile App Access:**

For mobile devices to connect, you MUST bind the server to `0.0.0.0` instead of the default `127.0.0.1`:

```bash
# ✅ CORRECT - Allows mobile devices to connect
python manage.py runserver 0.0.0.0:8000

# ❌ WRONG - Only accessible from same computer
python manage.py runserver
```

**Quick Start Scripts:**
- **Windows**: Double-click `runserver_mobile.bat` or run it from command prompt
- **Mac/Linux**: Run `chmod +x runserver_mobile.sh && ./runserver_mobile.sh`

**Why `0.0.0.0`?**
- `127.0.0.1` (default) = Only accessible from the same computer
- `0.0.0.0` = Accessible from any device on the same network

**Network Requirements:**
- Your computer and mobile device must be on the **same Wi-Fi network**
- Find your computer's IP address:
  - Windows: `ipconfig` (look for IPv4 Address)
  - Mac/Linux: `ifconfig` or `ip addr`
- Update `mobile_app/config.js` with your computer's IP address

The API endpoints will be available at:
- `http://YOUR_IP:8000/api/mobile/login/`
- `http://YOUR_IP:8000/api/mobile/account/`
- `http://YOUR_IP:8000/api/mobile/account/summary/`
- `http://YOUR_IP:8000/api/mobile/transactions/`
- `http://YOUR_IP:8000/api/mobile/balance-transactions/`

### 4. Configure CORS (Already Done)

CORS is already configured in `settings.py` to allow requests from mobile apps. In development, all origins are allowed. For production, update `CORS_ALLOWED_ORIGINS` with specific domains.

## Mobile App Setup

### Prerequisites

- Node.js (v14 or higher)
- npm or yarn
- Expo CLI: `npm install -g expo-cli`
- Expo Go app on your mobile device (for testing)

### Installation Steps

1. Navigate to the mobile app directory:
   ```bash
   cd mobile_app
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Configure API endpoint:
   - Open `mobile_app/config.js`
   - Update `API_BASE_URL` with your Django server address:
     - **For iOS Simulator**: `http://localhost:8000`
     - **For Android Emulator**: `http://10.0.2.2:8000`
     - **For Physical Device**: `http://YOUR_COMPUTER_IP:8000` (e.g., `http://192.168.1.100:8000`)
   
   To find your computer's IP address:
   - Windows: `ipconfig` (look for IPv4 Address)
   - Mac/Linux: `ifconfig` or `ip addr`

4. Start the Expo development server:
   ```bash
   npm start
   ```

5. Run on your device:
   - Press `i` for iOS Simulator
   - Press `a` for Android Emulator
   - Scan the QR code with Expo Go app on your physical device

## API Endpoints

### Authentication

**POST** `/api/mobile/login/`
- **Body**: `{ "rfid": "1001", "pin": "1234" }`
- **Response**: `{ "success": true, "member": {...}, "message": "..." }`
- Authenticates member using RFID card number and 4-digit PIN

### Account Information

**GET** `/api/mobile/account/`
- **Auth**: Required (Session)
- **Response**: `{ "success": true, "member": {...} }`
- Returns current member's account information

**GET** `/api/mobile/account/summary/`
- **Auth**: Required (Session)
- **Response**: `{ "success": true, "summary": {...} }`
- Returns comprehensive account summary including:
  - Member information
  - Recent transactions (last 10)
  - Recent balance transactions (last 10)
  - Monthly spending and patronage totals

### Transaction History

**GET** `/api/mobile/transactions/`
- **Auth**: Required (Session)
- **Query Params**: `?page=1&limit=20`
- **Response**: `{ "success": true, "transactions": [...], "pagination": {...} }`
- Returns paginated list of completed transactions

**GET** `/api/mobile/balance-transactions/`
- **Auth**: Required (Session)
- **Query Params**: `?page=1&limit=20`
- **Response**: `{ "success": true, "balance_transactions": [...], "pagination": {...} }`
- Returns paginated list of balance transactions (deposits, deductions)

## Mobile App Features

### Home Screen
- Account balance display
- Monthly spending summary
- Total patronage earned
- Quick access to transaction history
- Recent transactions preview

### Transactions Screen
- Complete transaction history
- Transaction details (items, payment method, patronage)
- Pull-to-refresh
- Infinite scroll pagination

### Balance Transactions Screen
- Deposit history
- Deduction history
- Balance changes over time
- Pull-to-refresh
- Infinite scroll pagination

## Authentication Flow

1. User enters RFID card number and 4-digit PIN
2. App sends login request to `/api/mobile/login/`
3. Backend validates RFID and PIN
4. If valid, backend creates session and returns member data
5. App stores member data locally
6. Subsequent API requests use session cookies automatically

## Troubleshooting

### Connection Issues

**Problem**: App can't connect to Django server

**Solutions**:
- Verify Django server is running on the correct port
- Check `API_BASE_URL` in `config.js` matches your server address
- For physical devices, ensure both device and computer are on the same Wi-Fi network
- Check firewall settings aren't blocking connections
- Verify CORS settings in Django `settings.py`

### Authentication Issues

**Problem**: Login fails or "Member account not found"

**Solutions**:
- Verify the member has a linked user account in Django admin
- Check that the member account is active
- Ensure RFID card number and PIN are correct
- Verify the member has a PIN set (use Django admin to set PIN if needed)

### CORS Errors

**Problem**: CORS policy errors in browser console

**Solutions**:
- Ensure `django-cors-headers` is installed
- Verify `corsheaders` is in `INSTALLED_APPS`
- Check `CorsMiddleware` is in `MIDDLEWARE` (should be near the top)
- In development, `CORS_ALLOW_ALL_ORIGINS = True` should be set when `DEBUG = True`

## Security Notes

- In production, update `CORS_ALLOW_ALL_ORIGINS = False` and specify allowed origins
- Consider implementing token-based authentication instead of session-based for better mobile app security
- Ensure HTTPS is used in production
- PINs are hashed in the database (not stored in plaintext)

## Next Steps

- Build standalone apps using `expo build:ios` or `expo build:android`
- Add push notifications for transaction alerts
- Implement biometric authentication (fingerprint/face ID)
- Add transaction filtering and search functionality
- Create charts and graphs for spending analysis

