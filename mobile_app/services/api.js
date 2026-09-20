import axios from 'axios';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { API_BASE_URL, API_ENDPOINTS } from '../config';
import { getEffectiveApiBase } from '../utils/apiBase';

// Connection state management - start optimistic
let connectionState = {
  isOnline: true, // Start as online (optimistic)
  lastCheck: null,
  quality: 'good', // Start with 'good' instead of 'unknown'
  latency: null,
  consecutiveFailures: 0, // Track consecutive failures
  lastSuccess: Date.now(), // Start with current time as last success
};

// Request queue for offline scenarios
const requestQueue = [];
let isProcessingQueue = false;

// Separate connection monitoring tunnel
let connectionMonitorInterval = null;
let isMonitoring = false;
const MONITOR_INTERVAL = 10000; // Check every 10 seconds
const MAX_CONSECUTIVE_FAILURES = 3; // Only mark offline after 3 consecutive failures

// Create axios instance with default config
// Use dynamic baseURL to handle connection issues better
const getBaseURL = () => {
  // Always use the configured API_BASE_URL
  return API_BASE_URL;
};

// Enhanced timeout based on connection quality
const getTimeout = () => {
  switch (connectionState.quality) {
    case 'excellent':
      return 15000;
    case 'good':
      return 20000;
    case 'poor':
      return 30000;
    default:
      return 25000;
  }
};

const api = axios.create({
  baseURL: getBaseURL(),
  timeout: getTimeout(),
  withCredentials: true, // Important for session cookies
  headers: {
    'Content-Type': 'application/json',
    'Accept': 'application/json',
    'Connection': 'keep-alive',
  },
  // Add retry configuration
  validateStatus: function (status) {
    return status < 500; // Don't throw for 4xx errors, only 5xx
  },
  // Enable HTTP keep-alive
  httpAgent: false,
  httpsAgent: false,
});

// Update connection quality based on latency and success
function updateConnectionQuality(latency, success) {
  if (success) {
    // Reset failure counter on success
    connectionState.consecutiveFailures = 0;
    connectionState.lastSuccess = Date.now();
    connectionState.isOnline = true;
    
    if (latency !== null) {
      connectionState.latency = latency;
      
      if (latency < 500) {
        connectionState.quality = 'excellent';
      } else if (latency < 1500) {
        connectionState.quality = 'good';
      } else if (latency < 5000) {
        connectionState.quality = 'poor';
      } else {
        connectionState.quality = 'poor';
      }
    } else {
      // If we got success but no latency, assume good connection
      connectionState.quality = connectionState.quality === 'offline' ? 'good' : connectionState.quality;
    }
  } else {
    // Increment failure counter
    connectionState.consecutiveFailures++;
    
    // Only mark as offline after multiple consecutive failures
    if (connectionState.consecutiveFailures >= MAX_CONSECUTIVE_FAILURES) {
      connectionState.quality = 'offline';
      connectionState.isOnline = false;
      connectionState.latency = null;
    } else {
      // Keep previous quality if we haven't failed enough times
      // This prevents false offline status from temporary network hiccups
      if (connectionState.quality === 'offline') {
        connectionState.quality = 'poor'; // Upgrade from offline to poor
      }
    }
  }
  
  connectionState.lastCheck = Date.now();
}

// Add request interceptor to include session cookie and update timeout
api.interceptors.request.use(
  async (config) => {
    // Update timeout based on connection quality
    config.timeout = getTimeout();
    
    // Add timestamp for latency measurement
    config.metadata = { startTime: Date.now() };
    
    // Session cookies are handled automatically by axios with withCredentials
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Add response interceptor for error handling and connection quality tracking
api.interceptors.response.use(
  (response) => {
    // Calculate latency
    if (response.config.metadata?.startTime) {
      const latency = Date.now() - response.config.metadata.startTime;
      updateConnectionQuality(latency, true);
    } else {
      // Even without latency, mark as success
      updateConnectionQuality(null, true);
    }
    
    // Update connection state - any response means we're online
    connectionState.isOnline = true;
    connectionState.lastCheck = Date.now();
    connectionState.lastSuccess = Date.now();
    connectionState.consecutiveFailures = 0; // Reset failures
    
    // If quality was offline, upgrade it
    if (connectionState.quality === 'offline') {
      connectionState.quality = 'good';
    }
    
    return response;
  },
  async (error) => {
    // Update connection state on error - but be more lenient
    if (error.code === 'ERR_NETWORK' || !error.response) {
      // Only mark as offline if we've had multiple failures
      // Don't immediately mark offline on single network error
      updateConnectionQuality(null, false);
      // Don't immediately set isOnline to false - let the failure counter handle it
    } else if (error.config?.metadata?.startTime) {
      // If we got a response (even error), server is reachable
      if (error.response) {
        const latency = Date.now() - error.config.metadata.startTime;
        updateConnectionQuality(latency, true);
      } else {
        const latency = Date.now() - error.config.metadata.startTime;
        updateConnectionQuality(latency, false);
      }
    }
    
    if (error.response?.status === 401) {
      // Unauthorized – clear ALL session/credential storage and auto-logout
      await triggerAutoLogout();
    }
    
    // Improve error messages
    if (error.code === 'ECONNABORTED') {
      error.message = 'Request timeout. Please check your connection and try again.';
    } else if (error.code === 'ERR_NETWORK' || !error.response) {
      error.message = 'Network error. Please check your internet connection and server URL.';
    } else if (error.response?.status >= 500) {
      error.message = 'Server error. Please try again later.';
    }
    
    return Promise.reject(error);
  }
);

// Enhanced retry function with exponential backoff
async function retryRequest(requestFn, maxRetries = 3, baseDelay = 1000) {
  let lastError;
  
  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await requestFn();
    } catch (error) {
      lastError = error;
      
      // Don't retry on client errors (4xx) except 408 (timeout)
      if (error.response?.status >= 400 && error.response?.status < 500 && error.response?.status !== 408) {
        throw error;
      }
      
      // Don't retry if we've exhausted attempts
      if (attempt >= maxRetries) {
        throw error;
      }
      
      // Calculate exponential backoff delay
      const delay = baseDelay * Math.pow(2, attempt) + Math.random() * 1000; // Add jitter
      await new Promise(resolve => setTimeout(resolve, delay));
    }
  }
  
  throw lastError;
}

// Lightweight connection test - just checks if server responds
const quickConnectionTest = async (timeout = 5000) => {
  const baseURL = getBaseURL();
  const startTime = Date.now();
  
  try {
    // Try health endpoint first (lightweight)
    const healthUrl = baseURL.replace(/\/$/, '') + '/api/mobile/health/';
    
    const response = await axios.get(healthUrl, {
      timeout: timeout,
      validateStatus: () => true, // Accept ANY status code
    });
    
    // If we got ANY response, server is online
    const latency = Date.now() - startTime;
    updateConnectionQuality(latency, true);
    return { connected: true, latency: latency };
  } catch (error) {
    // If we got a response object (even error), server is reachable
    if (error.response) {
      const latency = Date.now() - startTime;
      updateConnectionQuality(latency, true);
      return { connected: true, latency: latency };
    }
    
    // Try alternative lightweight check
    try {
      const testUrl = baseURL.replace(/\/$/, '') + '/admin/';
      await axios.get(testUrl, {
        timeout: timeout,
        validateStatus: () => true,
      });
      const latency = Date.now() - startTime;
      updateConnectionQuality(latency, true);
      return { connected: true, latency: latency };
    } catch (altError) {
      // If we got a response, server is online
      if (altError.response) {
        const latency = Date.now() - startTime;
        updateConnectionQuality(latency, true);
        return { connected: true, latency: latency };
      }
      
      // Only mark as failed if we truly got no response
      updateConnectionQuality(null, false);
      return { connected: false };
    }
  }
};

// Helper function to test API connectivity with health check endpoint
const testConnection = async (maxAttempts = 2) => {
  const baseURL = getBaseURL();
  const startTime = Date.now();
  
  // Use quick test first (faster)
  const quickResult = await quickConnectionTest(8000);
  if (quickResult.connected) {
    return {
      connected: true,
      url: baseURL,
      latency: quickResult.latency,
      quality: connectionState.quality
    };
  }
  
  // If quick test failed, try with more attempts
  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    try {
      // Try health check endpoint first (most reliable)
      const healthUrl = baseURL.replace(/\/$/, '') + '/api/mobile/health/';
      
      try {
        const response = await axios.get(healthUrl, {
          timeout: 10000,
          validateStatus: () => true, // Accept any status code
        });
        
        const latency = Date.now() - startTime;
        
        // ANY response means server is online
        updateConnectionQuality(latency, true);
        return { 
          connected: true, 
          url: baseURL,
          latency: latency,
          quality: connectionState.quality,
          serverTime: response.data?.server_time
        };
      } catch (healthError) {
        // If we got a response, server is online
        if (healthError.response) {
          const latency = Date.now() - startTime;
          updateConnectionQuality(latency, true);
          return { connected: true, url: baseURL, latency: latency };
        }
        
        // Try alternative endpoints
        const testUrl = baseURL.replace(/\/$/, '') + '/api/mobile/';
        
        try {
          const response = await axios.get(testUrl, {
            timeout: 8000,
            validateStatus: () => true,
          });
          
          const latency = Date.now() - startTime;
          updateConnectionQuality(latency, true);
          return { connected: true, url: baseURL, latency: latency };
        } catch (testError) {
          // If we got a response, server is online
          if (testError.response) {
            const latency = Date.now() - startTime;
            updateConnectionQuality(latency, true);
            return { connected: true, url: baseURL, latency: latency };
          }
          
          // Try Django admin as last resort
          const adminUrl = baseURL.replace(/\/$/, '') + '/admin/';
          try {
            await axios.get(adminUrl, {
              timeout: 8000,
              validateStatus: () => true,
            });
            const latency = Date.now() - startTime;
            updateConnectionQuality(latency, true);
            return { connected: true, url: baseURL, latency: latency };
          } catch (adminError) {
            // If we got ANY response, server is online
            if (adminError.response) {
              const latency = Date.now() - startTime;
              updateConnectionQuality(latency, true);
              return { connected: true, url: baseURL, latency: latency };
            }
            
            // Only mark as failed if truly no response
            if (attempt < maxAttempts) {
              await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
              continue;
            }
            updateConnectionQuality(null, false);
            return { 
              connected: false, 
              url: baseURL,
              error: 'Cannot reach server. Check:\n• Internet connection\n• Server is running\n• Server URL is correct'
            };
          }
        }
      }
    } catch (error) {
      // If we get ANY response (even 404/405/500), server is reachable
      if (error.response) {
        const latency = Date.now() - startTime;
        updateConnectionQuality(latency, true);
        return { connected: true, url: baseURL, latency: latency };
      }
      
      // Network error - server unreachable
      if (error.code === 'ERR_NETWORK' || error.code === 'ECONNABORTED' || !error.response) {
        if (attempt < maxAttempts) {
          await new Promise(resolve => setTimeout(resolve, 1000 * attempt));
          continue;
        }
        updateConnectionQuality(null, false);
        return { 
          connected: false, 
          url: baseURL,
          error: error.message || 'Network error. Please check your connection.'
        };
      }
      
      // Other errors - assume server is reachable
      const latency = Date.now() - startTime;
      updateConnectionQuality(latency, true);
      return { connected: true, url: baseURL, latency: latency };
    }
  }
  
  // Only mark as failed if all attempts truly failed
  updateConnectionQuality(null, false);
  return { 
    connected: false, 
    url: baseURL,
    error: 'Connection failed after multiple attempts'
  };
};

// Separate connection monitoring tunnel - runs in background
// ENHANCED: More aggressive monitoring with automatic reconnection
const startConnectionMonitor = () => {
  if (isMonitoring) return; // Already monitoring
  
  isMonitoring = true;
  
  // Initial check - more aggressive
  quickConnectionTest(5000).catch(() => {
    // Silent fail for background monitoring
  });
  
  // Set up interval for continuous monitoring with automatic reconnection
  connectionMonitorInterval = setInterval(async () => {
    try {
      const result = await quickConnectionTest(5000);
      // If connection is good, update state optimistically
      if (result && result.connected) {
        connectionState.isOnline = true;
        connectionState.quality = result.quality || 'good';
      }
    } catch (error) {
      // If monitoring fails, try a more thorough connection test
      if (connectionState.quality === 'offline' || !connectionState.isOnline) {
        // Try full connection test when offline
        try {
          const fullTest = await testConnection(1);
          if (fullTest.connected) {
            connectionState.isOnline = true;
            connectionState.quality = fullTest.quality || 'good';
            connectionState.consecutiveFailures = 0;
          }
        } catch (fullTestError) {
          // Still offline, but that's okay - will retry next interval
        }
      }
    }
  }, MONITOR_INTERVAL);
};

// Stop connection monitoring
const stopConnectionMonitor = () => {
  if (connectionMonitorInterval) {
    clearInterval(connectionMonitorInterval);
    connectionMonitorInterval = null;
  }
  isMonitoring = false;
};

// Get connection state
export const getConnectionState = () => ({ ...connectionState });

// ── Auto-logout callback ──────────────────────────────────────────────────────
// App.js registers a handler here; the 401 interceptor calls it so the UI
// can navigate back to the Login screen without the service layer needing a
// navigation reference.
let _logoutCallback = null;

export const setLogoutCallback = (cb) => {
  _logoutCallback = cb;
};

// ── In-memory session marker ──────────────────────────────────────────────────
// This variable lives in JS heap. It is automatically cleared (set to null)
// whenever the process is killed — including when the user swipes the app
// away from the Android/iOS recent-apps screen.
// App.js uses it in checkAuth() to detect a cold start after a kill and force
// re-authentication, making swipe-from-recents behave like a proper logout.
let _inMemorySession = null;

export const setInMemorySession = (marker) => { _inMemorySession = marker; };
export const getInMemorySession = () => _inMemorySession;
export const clearInMemorySession = () => { _inMemorySession = null; };

export const triggerAutoLogout = async () => {
  // Clear all local session data
  clearInMemorySession();
  await AsyncStorage.multiRemove(['memberData', 'sessionId', 'storedUsername', 'storedPin']);
  await AsyncStorage.setItem('explicitLogout', 'true');
  if (_logoutCallback) {
    _logoutCallback();
  }
};

// Check connection state - be optimistic
export const isConnected = () => {
  // If we had a recent success, consider online even if current check failed
  if (connectionState.lastSuccess && (Date.now() - connectionState.lastSuccess) < 30000) {
    return true; // Consider online if we had success in last 30 seconds
  }
  return connectionState.isOnline;
};

// Start connection monitoring tunnel
export const startMonitoring = () => {
  startConnectionMonitor();
};

// Stop connection monitoring
export const stopMonitoring = () => {
  stopConnectionMonitor();
};

export const authService = {
  async checkConnection() {
    const result = await testConnection();
    return result.connected;
  },
  
  async checkConnectionDetailed() {
    return await testConnection();
  },
  
  getConnectionState() {
    return getConnectionState();
  },
  
  // Start background monitoring
  startMonitoring() {
    startConnectionMonitor();
  },
  
  // Stop background monitoring
  stopMonitoring() {
    stopConnectionMonitor();
  },

  async login(username, pin, retries = 5) {
    let lastError;
    
    // Validate input before making request
    if (!username || !username.trim()) {
      throw 'Username is required';
    }
    
    if (!pin || !pin.trim()) {
      throw 'PIN is required';
    }
    
    if (!/^\d{4}$/.test(pin)) {
      throw 'PIN must be exactly 4 digits';
    }
    
    // AUTOMATIC CONNECTION: Always try to establish connection first
    // This ensures we're connected before attempting login
    let connectionEstablished = false;
    if (connectionState.quality === 'offline' || !connectionState.isOnline) {
      console.log('Connection offline, attempting automatic connection...');
      for (let connAttempt = 0; connAttempt < 3; connAttempt++) {
        try {
          const connResult = await testConnection(2);
          if (connResult.connected) {
            connectionEstablished = true;
            console.log('Automatic connection successful!');
            break;
          }
        } catch (error) {
          console.log(`Connection attempt ${connAttempt + 1} failed, retrying...`);
          // Wait before retry
          await new Promise(resolve => setTimeout(resolve, 1000 * (connAttempt + 1)));
        }
      }
    } else {
      // Connection seems good, but verify it quickly
      try {
        await quickConnectionTest(3000);
        connectionEstablished = true;
      } catch (error) {
        console.log('Quick connection check failed, will retry during login');
      }
    }
    
    // Enhanced retry loop with automatic connection retry
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const response = await api.post(API_ENDPOINTS.LOGIN, {
          username: username.trim(),
          pin: pin.trim(),
        });
        
        // Check if response indicates success
        if (response.data && response.data.success === true) {
          // Store member data
          if (response.data.member) {
            await AsyncStorage.setItem('memberData', JSON.stringify(response.data.member));
          }
          // Store session info if provided
          if (response.data.session_id) {
            await AsyncStorage.setItem('sessionId', response.data.session_id);
          }
          // Store username and PIN for automatic login
          await AsyncStorage.setItem('storedUsername', username.trim());
          await AsyncStorage.setItem('storedPin', pin.trim());
          // Mark session as alive in memory so cold-start detection works
          setInMemorySession(username.trim());
          return response.data;
        }
        
        // If login failed but we got a response, return structured error so the
        // caller can display the correct message (do NOT throw — a plain string
        // thrown here has no .response property and gets misidentified as a
        // network error in the catch block below).
        return {
          success: false,
          error: response.data?.error || response.data?.message || 'Login failed',
          attempts_remaining: response.data?.attempts_remaining,
          locked: response.data?.locked || false,
        };
      } catch (error) {
        lastError = error;
        
        // Handle specific error status codes
        if (error.response?.status === 400) {
          // Bad request - validation error
          throw error.response?.data?.error || 'Invalid input. Please check your username and PIN.';
        }
        
        if (error.response?.status === 401) {
          // Unauthorized - invalid credentials; return full data so caller can read attempts_remaining
          return {
            success: false,
            error: error.response?.data?.error || 'Invalid username or PIN. Please try again.',
            attempts_remaining: error.response?.data?.attempts_remaining,
          };
        }

        if (error.response?.status === 403) {
          // Forbidden - could be locked account or inactive
          const data = error.response?.data || {};
          return {
            success: false,
            error: data.error || 'Your account is inactive. Please contact administrator.',
            locked: data.locked || false,
          };
        }
        
        if (error.response?.status === 404) {
          // Not found - member doesn't exist
          throw error.response?.data?.error || 'User not found. Please check your username.';
        }
        
        if (error.response?.status === 500) {
          // Server error
          throw error.response?.data?.error || 'Server error. Please try again later.';
        }
        
        // Don't retry on client errors (4xx)
        if (error.response?.status >= 400 && error.response?.status < 500) {
          throw error.response?.data?.error || error.message || 'Login failed';
        }
        
        // AUTOMATIC RETRY: Retry on network errors or server errors (5xx)
        if (attempt < retries && (error.code === 'ERR_NETWORK' || error.code === 'ECONNABORTED' || (error.response?.status >= 500))) {
          console.log(`Login attempt ${attempt + 1} failed, automatically retrying...`);
          
          // AUTOMATIC RECONNECTION: Always try to reconnect before retry
          if (error.code === 'ERR_NETWORK' || error.code === 'ECONNABORTED' || !error.response) {
            console.log('Network error detected, attempting automatic reconnection...');
            for (let reconnectAttempt = 0; reconnectAttempt < 2; reconnectAttempt++) {
              try {
                const reconnectResult = await testConnection(2);
                if (reconnectResult.connected) {
                  console.log('Automatic reconnection successful!');
                  connectionEstablished = true;
                  break;
                }
              } catch (reconnectError) {
                console.log(`Reconnection attempt ${reconnectAttempt + 1} failed`);
                // Wait before next reconnection attempt
                await new Promise(resolve => setTimeout(resolve, 1000 * (reconnectAttempt + 1)));
              }
            }
          }
          
          // Exponential backoff with jitter for retry delay
          const backoffDelay = Math.min(1000 * Math.pow(2, attempt) + Math.random() * 500, 5000);
          console.log(`Waiting ${Math.round(backoffDelay)}ms before retry...`);
          await new Promise(resolve => setTimeout(resolve, backoffDelay));
          continue;
        }
        
        // Format error message
        if (error.response?.data?.error) {
          throw error.response.data.error;
        }
        
        if (error.code === 'ERR_NETWORK' || !error.response) {
          // Final attempt to establish connection
          console.log('Final connection attempt before giving up...');
          let finalConnectionAttempt = false;
          for (let finalAttempt = 0; finalAttempt < 2; finalAttempt++) {
            try {
              const connectionTest = await testConnection(2);
              if (connectionTest.connected) {
                finalConnectionAttempt = true;
                // If we got connection, retry login one more time
                console.log('Connection established, retrying login...');
                try {
                  const retryResponse = await api.post(API_ENDPOINTS.LOGIN, {
                    username: username.trim(),
                    pin: pin.trim(),
                  });
                  if (retryResponse.data && retryResponse.data.success === true) {
                    // Store member data
                    if (retryResponse.data.member) {
                      await AsyncStorage.setItem('memberData', JSON.stringify(retryResponse.data.member));
                    }
                    if (retryResponse.data.session_id) {
                      await AsyncStorage.setItem('sessionId', retryResponse.data.session_id);
                    }
                    await AsyncStorage.setItem('storedUsername', username.trim());
                    await AsyncStorage.setItem('storedPin', pin.trim());
                    setInMemorySession(username.trim());
                    return retryResponse.data;
                  }
                } catch (retryError) {
                  // Retry login failed, continue to throw original error
                }
                break;
              }
            } catch (connError) {
              // Continue to next attempt
            }
            await new Promise(resolve => setTimeout(resolve, 1000));
          }
          
          if (!finalConnectionAttempt) {
            throw `Cannot connect to server at ${getBaseURL()}\n\nPlease check:\n• Your internet connection\n• Server is running\n• Server URL is correct\n• Both devices are on same network (if using local IP)`;
          }
          throw 'Network error occurred. Please try again.';
        }
        
        throw error.message || 'Login failed. Please try again.';
      }
    }
    
    throw lastError?.message || 'Login failed after multiple attempts';
  },

  async logout() {
    // Call server logout to invalidate the session cookie
    try {
      await api.post(API_ENDPOINTS.LOGOUT);
    } catch {
      // Ignore network errors — we still want to clear local state
    }

    // Clear in-memory session marker
    clearInMemorySession();

    // Clear local session data
    await AsyncStorage.removeItem('memberData');
    await AsyncStorage.removeItem('sessionId');
    // Keep storedPin and storedUsername so fingerprint login works after logout.
    // Set explicitLogout flag to prevent auto-login on next app open.
    await AsyncStorage.setItem('explicitLogout', 'true');
    // biometricEnabled is intentionally kept so fingerprint stays enabled
    // across logouts — the user should not have to re-enable it every session.
    // storedUsername is intentionally kept so the PIN screen
    // pre-fills the username after logout.
  },

  // Clears only the session (memberData, sessionId) but keeps stored
  // username/PIN so fingerprint login continues to work after expiry.
  async clearSession() {
    await AsyncStorage.removeItem('memberData');
    await AsyncStorage.removeItem('sessionId');
  },

  async getStoredMember() {
    const memberData = await AsyncStorage.getItem('memberData');
    return memberData ? JSON.parse(memberData) : null;
  },

  async getStoredCredentials() {
    const username = await AsyncStorage.getItem('storedUsername');
    const pin = await AsyncStorage.getItem('storedPin');
    if (username && pin) {
      return { username, pin };
    }
    return null;
  },

  async autoLogin() {
    try {
      const credentials = await this.getStoredCredentials();
      if (!credentials) {
        return { success: false, error: 'No stored credentials' };
      }
      
      // AUTOMATIC CONNECTION: Ensure connection before auto-login
      console.log('Auto-login: Checking connection first...');
      if (connectionState.quality === 'offline' || !connectionState.isOnline) {
        console.log('Auto-login: Connection offline, attempting automatic connection...');
        for (let connAttempt = 0; connAttempt < 3; connAttempt++) {
          try {
            const connResult = await testConnection(2);
            if (connResult.connected) {
              console.log('Auto-login: Connection established!');
              break;
            }
          } catch (error) {
            console.log(`Auto-login: Connection attempt ${connAttempt + 1} failed`);
            await new Promise(resolve => setTimeout(resolve, 1000 * (connAttempt + 1)));
          }
        }
      }
      
      // Attempt login with stored credentials (increased retries for auto-login)
      console.log('Auto-login: Attempting login with stored credentials...');
      const result = await this.login(credentials.username, credentials.pin, 4);
      console.log('Auto-login: Success!');
      return result;
    } catch (error) {
      console.log('Auto-login failed:', error);
      return { 
        success: false, 
        error: typeof error === 'string' ? error : (error.message || 'Auto-login failed') 
      };
    }
  },
};

export const accountService = {
  async getAccountInfo() {
    return retryRequest(async () => {
      const response = await api.get(API_ENDPOINTS.ACCOUNT_INFO);
      return response.data;
    }).catch(error => {
      throw error.response?.data?.error || error.message || 'Failed to fetch account info';
    });
  },

  async getAccountSummary(year = null, month = null) {
    return retryRequest(async () => {
      const params = {};
      if (year) params.year = year;
      if (month) params.month = month;
      const response = await api.get(API_ENDPOINTS.ACCOUNT_SUMMARY, { params });
      return response.data;
    }).catch(error => {
      throw error.response?.data?.error || error.message || 'Failed to fetch account summary';
    });
  },

  async getTransactionHistory(page = 1, limit = 20) {
    return retryRequest(async () => {
      const response = await api.get(API_ENDPOINTS.TRANSACTIONS, {
        params: { page, limit },
      });
      return response.data;
    }).catch(error => {
      throw error.response?.data?.error || error.message || 'Failed to fetch transactions';
    });
  },

  async getBalanceTransactions(page = 1, limit = 20) {
    return retryRequest(async () => {
      const response = await api.get(API_ENDPOINTS.BALANCE_TRANSACTIONS, {
        params: { page, limit },
      });
      return response.data;
    }).catch(error => {
      throw error.response?.data?.error || error.message || 'Failed to fetch balance transactions';
    });
  },

  async requestRefund(transactionId, reason, itemIds = []) {
    try {
      const body = { transaction_id: transactionId };
      if (reason) body.refund_reason = reason;
      if (itemIds && itemIds.length > 0) body.refund_item_ids = itemIds;
      const response = await api.post(API_ENDPOINTS.REQUEST_REFUND, body);
      return response.data;
    } catch (error) {
      throw error.response?.data?.error || error.message || 'Failed to submit refund request';
    }
  },
};

export const productService = {
  async getProducts({ search = '', category = '' } = {}) {
    return retryRequest(async () => {
      const params = {};
      if (search) params.search = search;
      if (category) params.category = category;
      const response = await api.get(API_ENDPOINTS.PRODUCTS, { params });
      return response.data;
    }).catch(error => {
      throw error.response?.data?.error || error.message || 'Failed to load products';
    });
  },
};

export const fundTransferService = {
  async searchMember(query) {
    return retryRequest(async () => {
      const response = await api.get(API_ENDPOINTS.SEARCH_MEMBER, {
        params: { query: query.trim() },
      });
      return response.data;
    }).catch(error => {
      throw error.response?.data?.error || error.message || 'Failed to search member';
    });
  },

  async scanQRCode(token) {
    return retryRequest(async () => {
      const response = await api.get(API_ENDPOINTS.QR_SCAN, {
        params: { token: token.trim() },
      });
      return response.data;
    }).catch(error => {
      throw error.response?.data?.error || error.message || 'Invalid QR code';
    });
  },

  async getMyQRCode() {
    return retryRequest(async () => {
      const response = await api.get(API_ENDPOINTS.QR_MY_CODE);
      return response.data;
    }).catch(error => {
      throw error.response?.data?.error || error.message || 'Failed to load QR code';
    });
  },

  async regenerateMyQR() {
    try {
      const response = await api.post(API_ENDPOINTS.QR_REGENERATE);
      return response.data;
    } catch (error) {
      throw error.response?.data?.error || error.message || 'Failed to regenerate QR code';
    }
  },

  async requestTransferOTP(recipientRfid, amount, notes = '') {
    return retryRequest(async () => {
      const response = await api.post(API_ENDPOINTS.REQUEST_TRANSFER_OTP, {
        recipient_rfid: recipientRfid.trim(),
        amount: parseFloat(amount),
        notes: notes.trim(),
      });
      return response.data;
    }).catch(error => {
      throw error.response?.data?.error || error.message || 'Failed to request OTP';
    });
  },

  async verifyTransferOTP(otpCode) {
    // No retry — fund transfer must not be retried silently.
    // If the transfer succeeded but the response was lost, a retry would fail
    // with "Invalid OTP" since the OTP is already marked as used.
    try {
      const response = await api.post(API_ENDPOINTS.VERIFY_TRANSFER_OTP, {
        otp_code: otpCode.trim(),
      });
      return response.data;
    } catch (error) {
      throw error.response?.data?.error || error.message || 'Failed to verify OTP';
    }
  },

  async requestBiometricOTP() {
    return retryRequest(async () => {
      const response = await api.post(API_ENDPOINTS.REQUEST_BIOMETRIC_OTP);
      return response.data;
    }).catch(error => {
      throw error.response?.data?.error || error.message || 'Failed to request OTP';
    });
  },

  async verifyBiometricOTP(otpCode) {
    try {
      const response = await api.post(API_ENDPOINTS.VERIFY_BIOMETRIC_OTP, {
        otp_code: otpCode.trim(),
      });
      return response.data;
    } catch (error) {
      throw error.response?.data?.error || error.message || 'Failed to verify OTP';
    }
  },
};

export const connectionService = {
  /** Public endpoint; uses same base URL as Settings → Server URL when set. */
  async fetchStoreInfo() {
    try {
      const base = await getEffectiveApiBase();
      if (!base) return null;
      const response = await api.get(`${base}/api/mobile/store-info/`);
      return response.data;
    } catch {
      return null;
    }
  },
};

export const adminService = {
  async getImportantDetails() {
    try {
      const response = await api.get(API_ENDPOINTS.ADMIN_IMPORTANT_DETAILS);
      return response.data;
    } catch (error) {
      throw error.response?.data?.error || error.message || 'Failed to load important details';
    }
  },
  async getCheckoutQueueStatus() {
    try {
      const response = await api.get(API_ENDPOINTS.ADMIN_CHECKOUT_QUEUE_STATUS);
      return response.data;
    } catch (error) {
      throw error.response?.data?.error || error.message || 'Failed to load checkout queue status';
    }
  },
  async getOperationalWatchlist() {
    try {
      const response = await api.get(API_ENDPOINTS.ADMIN_OPERATIONAL_WATCHLIST);
      return response.data;
    } catch (error) {
      throw error.response?.data?.error || error.message || 'Failed to load operational watchlist';
    }
  },
};

export default api;

