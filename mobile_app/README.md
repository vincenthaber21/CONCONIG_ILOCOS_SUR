# Coop Kiosk Mobile App

A React Native mobile application for members to view their account balance, transaction history, and other important account information.

## Features

- **Account Overview**: View account balance and total patronage
- **Transaction History**: Browse all completed transactions with details
- **Balance Transactions**: View deposits and deductions
- **Monthly Summary**: See spending and patronage for the current month
- **Secure Login**: Authenticate using RFID card number and 4-digit PIN

## Setup Instructions

### Prerequisites

- Node.js (v14 or higher)
- npm or yarn
- Expo CLI (`npm install -g expo-cli`)
- iOS Simulator (for Mac) or Android Studio (for Android development)

### Installation

1. Navigate to the mobile app directory:
   ```bash
   cd mobile_app
   ```

2. Install dependencies:
   ```bash
   npm install
   ```

3. Configure API endpoint:
   - Open `config.js`
   - Update `API_BASE_URL` with your Django server URL
   - For local development on a physical device, use your computer's IP address (e.g., `http://192.168.1.100:8000`)
   - For iOS Simulator, use `http://localhost:8000`
   - For Android Emulator, use `http://10.0.2.2:8000`

### Running the App

1. Start the Expo development server:
   ```bash
   npm start
   ```

2. Choose your platform:
   - Press `i` for iOS Simulator
   - Press `a` for Android Emulator
   - Scan QR code with Expo Go app on your physical device

### Building for Production

To build standalone apps:

```bash
# For iOS
expo build:ios

# For Android
expo build:android
```

## API Configuration

The mobile app communicates with the Django backend through REST API endpoints:

- `POST /api/mobile/login/` - Member login with RFID and PIN
- `GET /api/mobile/account/` - Get account information
- `GET /api/mobile/account/summary/` - Get comprehensive account summary
- `GET /api/mobile/transactions/` - Get transaction history (paginated)
- `GET /api/mobile/balance-transactions/` - Get balance transactions (paginated)

## Authentication

The app uses session-based authentication. After successful login with RFID and PIN, the session cookie is stored and used for subsequent API requests.

## Troubleshooting

### Connection Issues

- Ensure your Django server is running
- Check that CORS is properly configured in Django settings
- Verify the API_BASE_URL in `config.js` matches your server address
- For physical devices, ensure both device and computer are on the same network

### Authentication Issues

- Make sure the member has a linked user account in Django
- Verify the RFID card number and PIN are correct
- Check that the member account is active

## Development Notes

- The app uses React Navigation for navigation
- AsyncStorage is used for local data persistence
- Axios is used for HTTP requests
- The app follows React Native best practices and uses functional components with hooks

