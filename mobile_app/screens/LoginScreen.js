import React, { useState, useEffect, useCallback } from 'react';
import { useFocusEffect } from '@react-navigation/native';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  Modal,
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  ScrollView,
  Platform,
  Image,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as LocalAuthentication from 'expo-local-authentication';
import { authService, accountService, getConnectionState, startMonitoring } from '../services/api';
import { colors } from '../constants/colors';
import { fetchStoreBrandAssets } from '../utils/storeBrand';

export default function LoginScreen({ navigation }) {
  const [stage, setStage] = useState('loading');
  const [username, setUsername] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [pin, setPin] = useState('');
  const [loading, setLoading] = useState(false);
  const [isAutoLoggingIn, _setIsAutoLoggingIn] = useState(false); // kept for unused-var safety; auto-login is disabled
  const [biometricAvailable, setBiometricAvailable] = useState(false);
  const [biometricEnabled, setBiometricEnabled] = useState(false);
  const [isLocked, setIsLocked] = useState(false);
  const [attemptsRemaining, setAttemptsRemaining] = useState(null);
  const [errorModal, setErrorModal] = useState({ visible: false, title: '', message: '', isNetworkError: false });
  const [logoUrl, setLogoUrl] = useState('');

  useEffect(() => {
    startMonitoring();
    checkAuth();
    checkBiometrics();
    (async () => {
      try {
        const { logoUrl: resolved } = await fetchStoreBrandAssets();
        if (resolved) setLogoUrl(resolved);
      } catch {
        // keep login usable without logo
      }
    })();
  }, []);

  const checkBiometrics = async () => {
    try {
      const compatible = await LocalAuthentication.hasHardwareAsync();
      const enrolled = await LocalAuthentication.isEnrolledAsync();
      const hardwareReady = compatible && enrolled;
      setBiometricAvailable(hardwareReady);
      // Respect the user's in-app toggle from Settings
      const stored = await AsyncStorage.getItem('biometricEnabled');
      setBiometricEnabled(hardwareReady && stored === 'true');
    } catch {
      setBiometricAvailable(false);
      setBiometricEnabled(false);
    }
  };

  // Re-read the biometricEnabled flag whenever this screen gains focus
  // so changes made in Settings are reflected immediately.
  useFocusEffect(
    useCallback(() => {
      AsyncStorage.getItem('biometricEnabled').then((v) => {
        setBiometricEnabled(biometricAvailable && v === 'true');
      }).catch(() => {});
    }, [biometricAvailable])
  );

  useFocusEffect(
    useCallback(() => {
      let cancelled = false;
      (async () => {
        try {
          const { logoUrl: resolved } = await fetchStoreBrandAssets();
          if (!cancelled && resolved) setLogoUrl(resolved);
        } catch {
          // keep previous logo if any
        }
      })();
      return () => {
        cancelled = true;
      };
    }, [])
  );

  const performBiometricLogin = useCallback(async (credentials) => {
    try {
      const result = await LocalAuthentication.authenticateAsync({
        promptMessage: 'Verify your identity',
        fallbackLabel: 'Use PIN',
        disableDeviceFallback: false,
      });

      if (result.success) {
        const uname = username || credentials.username;
        if (!uname) {
          Alert.alert('Error', 'No username found. Please log in with your PIN first.', [{ text: 'OK' }]);
          return;
        }
        setLoading(true);
        try {
          const loginResult = await authService.login(uname, credentials.pin, 3);
          if (loginResult && loginResult.success) {
            await AsyncStorage.removeItem('explicitLogout');
            navigation.replace('Main');
          } else {
            const errMsg = loginResult?.error || 'Login failed. Please use your PIN.';
            setPin('');
            Alert.alert('Login Failed', errMsg, [{ text: 'OK' }]);
          }
        } catch (err) {
          setPin('');
          Alert.alert('Login Failed', err.message || 'Please use your PIN instead.', [{ text: 'OK' }]);
        } finally {
          setLoading(false);
        }
      } else if (result.error === 'user_cancel' || result.error === 'system_cancel') {
        // User dismissed — do nothing
      } else {
        Alert.alert('Authentication Failed', 'Fingerprint not recognised. Please use your PIN.', [
          { text: 'OK' },
        ]);
      }
    } catch (err) {
      Alert.alert('Biometric Error', err.message || 'Could not authenticate.', [{ text: 'OK' }]);
    }
  }, [username, navigation]);

  const handleBiometricAuth = useCallback(async () => {
    let compatible = false;
    let enrolled = false;
    try {
      compatible = await LocalAuthentication.hasHardwareAsync();
      enrolled = await LocalAuthentication.isEnrolledAsync();
    } catch {
      // leave both false
    }

    if (!compatible) {
      Alert.alert(
        'Hardware Not Supported',
        'This device does not have fingerprint or face ID hardware.',
        [{ text: 'OK' }]
      );
      return;
    }

    if (!enrolled) {
      Alert.alert(
        'No Biometrics Enrolled',
        'No fingerprint or face ID is enrolled on this device. Please go to your phone Settings → Security → Fingerprint and add one first.',
        [{ text: 'OK' }]
      );
      return;
    }

    // Check whether the user has explicitly enabled fingerprint in Settings
    const storedEnabled = await AsyncStorage.getItem('biometricEnabled');
    if (storedEnabled !== 'true') {
      Alert.alert(
        'Fingerprint Disabled',
        'Fingerprint login is turned off. Go to Settings → Security and enable Fingerprint Login first.',
        [{ text: 'OK' }]
      );
      return;
    }

    // We need a stored PIN to log in after biometric passes
    const credentials = await authService.getStoredCredentials().catch(() => null);
    if (!credentials || !credentials.pin) {
      Alert.alert(
        'PIN Required',
        'Please log in with your PIN first to enable fingerprint login.',
        [{ text: 'OK' }]
      );
      return;
    }

    await performBiometricLogin(credentials);
  }, [biometricAvailable, username, navigation, performBiometricLogin]);

  const checkAuth = async () => {
    try {
      const member = await authService.getStoredMember();
      if (member) {
        try {
          const accountResponse = await accountService.getAccountInfo();
          if (accountResponse && accountResponse.success) {
            navigation.replace('Main');
            return;
          }
        } catch (error) {
          // Session invalid, continue
        }
      }

      const credentials = await authService.getStoredCredentials();
      if (credentials && credentials.username && credentials.pin) {
        if (!(credentials.pin.length === 4 && /^\d{4}$/.test(credentials.pin))) {
          // Stored PIN is malformed — safe to clear everything.
          await authService.logout();
        }
        // Always show the PIN screen — never auto-login silently.
      }

      if (credentials && credentials.username) {
        setUsername(credentials.username);
        setDisplayName(credentials.username);
        setStage('pin');
      } else {
        // No PIN stored (e.g. after logout), but username may still be saved.
        const savedUsername = await AsyncStorage.getItem('storedUsername');
        if (savedUsername) {
          setUsername(savedUsername);
          setDisplayName(savedUsername);
          setStage('pin');
        } else {
          setStage('username');
        }
      }
    } catch (error) {
      setStage('username');
    }
  };

  const handleUsernameSubmit = () => {
    if (!username.trim()) {
      Alert.alert('Missing Information', 'Please enter your username');
      return;
    }
    setDisplayName(username.trim());
    setStage('pin');
  };

  const handleKeyPress = (value) => {
    if (pin.length < 4 && !loading) {
      const newPin = pin + value;
      setPin(newPin);
      if (newPin.length === 4) {
        setTimeout(() => handleLogin(newPin), 200);
      }
    }
  };

  const handleBackspace = () => {
    if (!loading) setPin((prev) => prev.slice(0, -1));
  };

  const handleLogin = async (pinToUse) => {
    const currentPin = pinToUse || pin;
    const currentUsername = username.trim();
    if (!currentUsername || !currentPin || currentPin.length < 4) return;

    setLoading(true);
    try {
      const result = await authService.login(currentUsername, currentPin, 3);
      if (result && result.success) {
        await AsyncStorage.removeItem('explicitLogout');
        setIsLocked(false);
        setAttemptsRemaining(null);
        navigation.replace('Main');
        return;
      } else {
        const errorMsg = result?.error || 'Login failed. Please try again.';
        setPin('');
        // Handle account locked response
        if (result?.locked) {
          setIsLocked(true);
          setAttemptsRemaining(0);
          return;
        }
        // Show remaining attempts if provided
        if (result?.attempts_remaining !== undefined) {
          setAttemptsRemaining(result.attempts_remaining);
        }
        // Show the server's error message directly so the user sees the exact
        // reason (e.g. "Invalid PIN. 3 attempts remaining…") rather than a
        // generic fallback. Only normalise the title for readability.
        const isPinError =
          errorMsg.toLowerCase().includes('invalid pin') ||
          errorMsg.toLowerCase().includes('pin must be') ||
          errorMsg.toLowerCase().includes('incorrect pin');
        setErrorModal({
          visible: true,
          title: isPinError ? 'Incorrect PIN' : 'Login Failed',
          message: errorMsg,
          isNetworkError: false,
        });
      }
    } catch (error) {
      const errorMessage =
        typeof error === 'string' ? error : error.message || 'Network error occurred. Please try again.';
      setPin('');

      // Distinguish network/connection errors from credential/validation errors
      const isNetworkErr =
        (typeof error === 'object' && error !== null &&
          (error.code === 'ERR_NETWORK' || error.code === 'ECONNABORTED')) ||
        errorMessage.toLowerCase().includes('cannot connect') ||
        errorMessage.toLowerCase().includes('network error') ||
        errorMessage.toLowerCase().includes('internet connection') ||
        errorMessage.toLowerCase().includes('server is running') ||
        errorMessage.toLowerCase().includes('server url');

      if (isNetworkErr) {
        setErrorModal({
          visible: true,
          title: 'Connection Error',
          message: errorMessage,
          isNetworkError: true,
        });
      } else {
        setErrorModal({
          visible: true,
          title: 'Invalid Credentials',
          message: errorMessage,
          isNetworkError: false,
        });
      }
    } finally {
      setLoading(false);
    }
  };

  const handleForgotPin = () => {
    Alert.alert('Reset PIN', 'Please contact your administrator to reset your PIN.', [
      { text: 'OK' },
    ]);
  };

  const handleChangeUser = async () => {
    await AsyncStorage.removeItem('storedUsername');
    setPin('');
    setUsername('');
    setDisplayName('');
    setIsLocked(false);
    setAttemptsRemaining(null);
    setStage('username');
  };

  const MAX_ATTEMPTS = 5;
  const failedCount = attemptsRemaining !== null ? MAX_ATTEMPTS - attemptsRemaining : 0;

  const brandLogoSource = logoUrl
    ? { uri: logoUrl }
    : require('../assets/icon.png');

  const brandHeader = (
    <View style={styles.brandSection}>
      <Image
        source={brandLogoSource}
        style={styles.brandLogo}
        resizeMode="contain"
        accessibilityRole="image"
        accessibilityLabel="Store logo"
        onError={() => {
          if (logoUrl) setLogoUrl('');
        }}
      />
    </View>
  );

  // Loading screen
  if (stage === 'loading') {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color={colors.brand} />
      </View>
    );
  }

  // Username entry screen
  if (stage === 'username') {
    return (
      <SafeAreaView style={styles.safeArea}>
        <KeyboardAvoidingView
          style={{ flex: 1 }}
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          keyboardVerticalOffset={Platform.OS === 'ios' ? 0 : 20}
        >
          <ScrollView
            contentContainerStyle={styles.container}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
          >
            {brandHeader}

            <View style={styles.usernameSection}>
              <Ionicons name="person-circle-outline" size={72} color={colors.brand} />
              <Text style={styles.welcomeHeading}>Welcome!</Text>
              <Text style={styles.welcomeSub}>Enter your username to continue</Text>
              <TextInput
                style={styles.usernameInput}
                placeholder="Username"
                value={username}
                onChangeText={setUsername}
                autoCapitalize="none"
                autoCorrect={false}
                autoFocus
                placeholderTextColor={colors.textMuted}
                returnKeyType="next"
                onSubmitEditing={handleUsernameSubmit}
              />
              <TouchableOpacity style={styles.continueBtn} onPress={handleUsernameSubmit}>
                <Text style={styles.continueBtnText}>Continue</Text>
              </TouchableOpacity>
            </View>
          </ScrollView>
        </KeyboardAvoidingView>
      </SafeAreaView>
    );
  }

  // PIN pad screen (GOtyme style)
  const keyRows = [
    ['1', '2', '3'],
    ['4', '5', '6'],
    ['7', '8', '9'],
  ];

  // Account locked screen
  if (stage === 'pin' && isLocked) {
    return (
      <SafeAreaView style={styles.safeArea}>
        <View style={styles.container}>
          {brandHeader}

          <View style={styles.lockedCard}>
            <View style={styles.lockedIconWrap}>
              <Ionicons name="lock-closed" size={40} color="#fff" />
            </View>
            <Text style={styles.lockedTitle}>Account Locked</Text>
            <Text style={styles.lockedName}>{displayName}</Text>
            <View style={styles.lockedDivider} />
            <View style={styles.lockedAttemptsRow}>
              {[...Array(5)].map((_, i) => (
                <View key={i} style={styles.attemptsCircleFailed} />
              ))}
            </View>
            <Text style={styles.lockedAttemptLabel}>5 / 5 failed attempts</Text>
            <Text style={styles.lockedDesc}>
              Too many incorrect PIN entries.{`\n`}Your account has been locked for security.
            </Text>
            <View style={styles.lockedInfoBox}>
              <Ionicons name="information-circle-outline" size={16} color="#92400e" style={{ marginRight: 6 }} />
              <Text style={styles.lockedInfoText}>
                Contact your administrator to unlock your account.
              </Text>
            </View>
          </View>

          <View style={styles.footer}>
            <TouchableOpacity
              style={styles.tryAgainBtn}
              onPress={() => { setIsLocked(false); setPin(''); }}
            >
              <Ionicons name="refresh-outline" size={18} color="#fff" style={{ marginRight: 6 }} />
              <Text style={styles.tryAgainBtnText}>Try Again</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.changeUserBtn} onPress={handleChangeUser}>
              <Text style={styles.changeUserText}>Not you? Change user</Text>
            </TouchableOpacity>
            <Text style={styles.developerText}>Developed by: DMMMSU</Text>
            <Text style={styles.developerText}>COLLEGE INFORMATION SYSTEMS</Text>
          </View>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safeArea}>
      <View style={styles.container}>

        {/* ── Login Error Modal ── */}
        <Modal
          transparent
          animationType="fade"
          visible={errorModal.visible}
          onRequestClose={() => setErrorModal(m => ({ ...m, visible: false }))}
        >
          <View style={styles.modalOverlay}>
            <View style={styles.modalCard}>
              {/* Header */}
              <View style={[styles.modalHeader, errorModal.isNetworkError && styles.modalHeaderNetwork]}>
                <Ionicons
                  name={errorModal.isNetworkError ? 'wifi-outline' : 'lock-closed'}
                  size={22}
                  color="#fff"
                  style={{ marginRight: 8 }}
                />
                <Text style={styles.modalHeaderText}>{errorModal.title}</Text>
              </View>

              {/* Message */}
              <View style={styles.modalBody}>
                <Text style={styles.modalMessage}>{errorModal.message}</Text>

                {/* Attempts indicator — only when there are tracked attempts */}
                {!errorModal.isNetworkError && attemptsRemaining !== null && attemptsRemaining > 0 && (
                  <View style={styles.modalAttemptsWrap}>
                    <Text style={styles.modalAttemptsLabel}>Failed attempts</Text>
                    <View style={styles.modalDotsRow}>
                      {[...Array(MAX_ATTEMPTS)].map((_, i) => (
                        <View
                          key={i}
                          style={[
                            styles.modalDot,
                            i < failedCount ? styles.modalDotFailed : styles.modalDotOk,
                          ]}
                        />
                      ))}
                    </View>
                    <Text style={[
                      styles.modalAttemptsCount,
                      attemptsRemaining === 1 && { color: '#dc2626', fontWeight: '800' },
                    ]}>
                      {attemptsRemaining === 1
                        ? '⚠️  1 attempt left — next failure locks account'
                        : `${attemptsRemaining} of ${MAX_ATTEMPTS} attempts remaining`}
                    </Text>
                  </View>
                )}
              </View>

              {/* Actions */}
              <View style={styles.modalFooter}>
                {errorModal.isNetworkError && (
                  <TouchableOpacity
                    style={[styles.modalBtn, styles.modalBtnRetry]}
                    onPress={() => setErrorModal(m => ({ ...m, visible: false }))}
                  >
                    <Ionicons name="refresh-outline" size={16} color={colors.brand} style={{ marginRight: 4 }} />
                    <Text style={[styles.modalBtnText, { color: colors.brand }]}>Retry</Text>
                  </TouchableOpacity>
                )}
                <TouchableOpacity
                  style={[styles.modalBtn, styles.modalBtnPrimary]}
                  onPress={() => setErrorModal(m => ({ ...m, visible: false }))}
                >
                  <Text style={[styles.modalBtnText, { color: '#fff' }]}>OK</Text>
                </TouchableOpacity>
              </View>
            </View>
          </View>
        </Modal>

        {/* Brand */}
        {brandHeader}

        {/* Lock icon + greeting + dots */}
        <View style={styles.pinSection}>
          {loading ? (
            <ActivityIndicator size="large" color={colors.brand} style={{ marginBottom: 24 }} />
          ) : (
            <Ionicons name="lock-closed" size={52} color="#2d2d2d" style={{ marginBottom: 24 }} />
          )}
          <Text style={styles.greetingText}>
            Ready when you are,{'\n'}
            <Text style={styles.greetingName}>{displayName}!</Text>
          </Text>

          <View style={styles.dotsRow}>
            {[0, 1, 2, 3].map((i) => (
              <View
                key={i}
                style={[
                  styles.dot,
                  i < pin.length
                    ? (attemptsRemaining !== null && attemptsRemaining <= 2 ? styles.dotFilledDanger : styles.dotFilled)
                    : styles.dotEmpty,
                ]}
              />
            ))}
          </View>

          {attemptsRemaining !== null && attemptsRemaining > 0 && (
            <View style={styles.attemptsBox}>
              <View style={styles.attemptsIconRow}>
                {[...Array(5)].map((_, i) => (
                  <View
                    key={i}
                    style={[
                      styles.attemptsCircle,
                      i < (5 - attemptsRemaining) ? styles.attemptsCircleFailed : styles.attemptsCircleOk,
                    ]}
                  />
                ))}
              </View>
              <Text style={[
                styles.attemptsWarning,
                attemptsRemaining === 1 && { color: '#dc2626', fontWeight: '800' },
              ]}>
                {attemptsRemaining === 1
                  ? '⚠️  Last attempt! Account will be locked.'
                  : `${attemptsRemaining} attempt${attemptsRemaining !== 1 ? 's' : ''} remaining before lockout`}
              </Text>
            </View>
          )}
        </View>

        {/* Numeric keypad */}
        <View style={styles.keypad}>
          {keyRows.map((row, ri) => (
            <View key={ri} style={styles.keyRow}>
              {row.map((k) => (
                <TouchableOpacity
                  key={k}
                  style={styles.keyBtn}
                  onPress={() => handleKeyPress(k)}
                  activeOpacity={0.6}
                  disabled={loading}
                >
                  <Text style={styles.keyText}>{k}</Text>
                </TouchableOpacity>
              ))}
            </View>
          ))}
          <View style={styles.keyRow}>
            <TouchableOpacity
              style={styles.keyBtn}
              activeOpacity={biometricAvailable && biometricEnabled ? 0.6 : 1}
              onPress={handleBiometricAuth}
              disabled={loading}
            >
              <Ionicons
                name={biometricEnabled ? 'finger-print' : 'finger-print-outline'}
                size={30}
                color={
                  !biometricAvailable
                    ? '#d1d5db'
                    : biometricEnabled
                    ? colors.brand
                    : '#9ca3af'
                }
              />
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.keyBtn}
              onPress={() => handleKeyPress('0')}
              activeOpacity={0.6}
              disabled={loading}
            >
              <Text style={styles.keyText}>0</Text>
            </TouchableOpacity>
            <TouchableOpacity style={styles.keyBtn} onPress={handleBackspace} activeOpacity={0.6}>
              <Ionicons name="backspace-outline" size={30} color="#2d2d2d" />
            </TouchableOpacity>
          </View>
        </View>

        {/* Footer */}
        <View style={styles.footer}>
          <TouchableOpacity onPress={handleForgotPin}>
            <Text style={styles.footerText}>
              Forgot your PIN?{' '}
              <Text style={styles.footerLink}>Reset Now</Text>
            </Text>
          </TouchableOpacity>
          <TouchableOpacity style={styles.changeUserBtn} onPress={handleChangeUser}>
            <Text style={styles.changeUserText}>Not you? Change user</Text>
          </TouchableOpacity>
          <Text style={styles.developerText}>Developed by: DMMMSU-NLUC</Text>
          <Text style={styles.developerText}>COLLEGE INFORMATION SYSTEMS</Text>
        </View>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safeArea: {
    flex: 1,
    backgroundColor: '#ffffff',
  },
  container: {
    flex: 1,
    backgroundColor: '#ffffff',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 24,
    paddingTop: 24,
    paddingBottom: 20,
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#ffffff',
  },
  autoLoginText: {
    marginTop: 16,
    fontSize: 16,
    color: colors.textSecondary,
    textAlign: 'center',
  },
  brandSection: {
    alignItems: 'center',
    marginTop: 8,
  },
  brandLogo: {
    width: 160,
    height: 96,
    marginBottom: 16,
    alignSelf: 'center',
  },
  usernameSection: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    width: '100%',
  },
  welcomeHeading: {
    fontSize: 26,
    fontWeight: '800',
    color: '#1a1a1a',
    marginTop: 16,
    marginBottom: 6,
  },
  welcomeSub: {
    fontSize: 15,
    color: colors.textSecondary,
    marginBottom: 28,
    textAlign: 'center',
  },
  usernameInput: {
    width: '100%',
    borderWidth: 1.5,
    borderColor: colors.border,
    borderRadius: 12,
    paddingVertical: 14,
    paddingHorizontal: 16,
    fontSize: 17,
    color: colors.textPrimary,
    backgroundColor: '#f9fafb',
    marginBottom: 20,
  },
  continueBtn: {
    width: '100%',
    backgroundColor: colors.brand,
    borderRadius: 12,
    paddingVertical: 15,
    alignItems: 'center',
  },
  continueBtnText: {
    color: '#ffffff',
    fontSize: 17,
    fontWeight: '700',
  },
  pinSection: {
    alignItems: 'center',
    marginTop: 8,
  },
  greetingText: {
    fontSize: 22,
    fontWeight: '700',
    textAlign: 'center',
    color: '#1a1a1a',
    lineHeight: 32,
    marginBottom: 28,
  },
  greetingName: {
    fontWeight: '900',
    color: '#1a1a1a',
  },
  dotsRow: {
    flexDirection: 'row',
    justifyContent: 'center',
    gap: 16,
  },
  dot: {
    width: 16,
    height: 16,
    borderRadius: 8,
  },
  dotEmpty: {
    backgroundColor: '#d1d5db',
  },
  dotFilled: {
    backgroundColor: '#1a1a1a',
  },
  keypad: {
    width: '100%',
    maxWidth: 340,
  },
  keyRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 8,
  },
  keyBtn: {
    flex: 1,
    marginHorizontal: 6,
    paddingVertical: 18,
    alignItems: 'center',
    justifyContent: 'center',
    borderRadius: 50,
  },
  keyText: {
    fontSize: 26,
    fontWeight: '400',
    color: '#1a1a1a',
  },
  footer: {
    alignItems: 'center',
    paddingBottom: 8,
  },
  footerText: {
    fontSize: 14,
    color: colors.textSecondary,
  },
  footerLink: {
    color: colors.brand,
    fontWeight: '700',
  },
  changeUserBtn: {
    marginTop: 10,
    paddingVertical: 6,
    paddingHorizontal: 12,
  },
  changeUserText: {
    fontSize: 13,
    color: colors.textMuted,
    textDecorationLine: 'underline',
  },
  attemptsBox: {
    marginTop: 14,
    alignItems: 'center',
    backgroundColor: '#fff5f5',
    borderWidth: 1,
    borderColor: '#fca5a5',
    borderRadius: 12,
    paddingVertical: 10,
    paddingHorizontal: 18,
    width: '100%',
    maxWidth: 280,
  },
  attemptsIconRow: {
    flexDirection: 'row',
    gap: 6,
    marginBottom: 6,
  },
  attemptsCircle: {
    width: 12,
    height: 12,
    borderRadius: 6,
  },
  attemptsCircleFailed: {
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: '#ef4444',
  },
  attemptsCircleOk: {
    width: 12,
    height: 12,
    borderRadius: 6,
    backgroundColor: '#d1d5db',
  },
  attemptsWarning: {
    marginTop: 2,
    fontSize: 13,
    color: '#ef4444',
    fontWeight: '600',
    textAlign: 'center',
  },
  dotFilledDanger: {
    backgroundColor: '#ef4444',
  },
  // Locked screen card
  lockedCard: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    width: '100%',
    paddingHorizontal: 8,
  },
  lockedIconWrap: {
    width: 80,
    height: 80,
    borderRadius: 40,
    backgroundColor: '#ef4444',
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: 18,
    shadowColor: '#ef4444',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.35,
    shadowRadius: 8,
    elevation: 6,
  },
  lockedTitle: {
    fontSize: 26,
    fontWeight: '800',
    color: '#dc2626',
    letterSpacing: 0.3,
    marginBottom: 4,
  },
  lockedName: {
    fontSize: 16,
    fontWeight: '600',
    color: '#374151',
    marginBottom: 16,
  },
  lockedDivider: {
    width: '60%',
    height: 1,
    backgroundColor: '#fca5a5',
    marginBottom: 14,
  },
  lockedAttemptsRow: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 6,
  },
  lockedAttemptLabel: {
    fontSize: 13,
    fontWeight: '700',
    color: '#ef4444',
    marginBottom: 14,
    letterSpacing: 0.2,
  },
  lockedDesc: {
    fontSize: 15,
    color: '#4b5563',
    textAlign: 'center',
    lineHeight: 22,
    marginBottom: 16,
    paddingHorizontal: 8,
  },
  lockedInfoBox: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#fffbeb',
    borderWidth: 1,
    borderColor: '#fcd34d',
    borderRadius: 10,
    paddingVertical: 10,
    paddingHorizontal: 14,
    width: '100%',
  },
  lockedInfoText: {
    flex: 1,
    fontSize: 13,
    color: '#92400e',
    lineHeight: 18,
  },
  tryAgainBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.brand,
    paddingVertical: 13,
    paddingHorizontal: 32,
    borderRadius: 12,
    marginBottom: 4,
    width: '100%',
    shadowColor: colors.brand,
    shadowOffset: { width: 0, height: 3 },
    shadowOpacity: 0.25,
    shadowRadius: 6,
    elevation: 4,
  },
  tryAgainBtnText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
  },
  // ── Error Modal ──
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.55)',
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 24,
  },
  modalCard: {
    width: '100%',
    backgroundColor: '#fff',
    borderRadius: 16,
    overflow: 'hidden',
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 8 },
    shadowOpacity: 0.18,
    shadowRadius: 16,
    elevation: 12,
  },
  modalHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#ef4444',
    paddingVertical: 14,
    paddingHorizontal: 18,
  },
  modalHeaderNetwork: {
    backgroundColor: '#f97316',
  },
  modalHeaderText: {
    color: '#fff',
    fontSize: 17,
    fontWeight: '700',
    letterSpacing: 0.2,
  },
  modalBody: {
    paddingHorizontal: 20,
    paddingTop: 18,
    paddingBottom: 8,
  },
  modalMessage: {
    fontSize: 15,
    color: '#374151',
    lineHeight: 22,
  },
  modalAttemptsWrap: {
    marginTop: 16,
    backgroundColor: '#fff5f5',
    borderWidth: 1,
    borderColor: '#fca5a5',
    borderRadius: 12,
    paddingVertical: 12,
    paddingHorizontal: 14,
    alignItems: 'center',
  },
  modalAttemptsLabel: {
    fontSize: 11,
    fontWeight: '700',
    color: '#9ca3af',
    letterSpacing: 0.8,
    textTransform: 'uppercase',
    marginBottom: 8,
  },
  modalDotsRow: {
    flexDirection: 'row',
    gap: 8,
    marginBottom: 8,
  },
  modalDot: {
    width: 14,
    height: 14,
    borderRadius: 7,
  },
  modalDotFailed: {
    backgroundColor: '#ef4444',
  },
  modalDotOk: {
    backgroundColor: '#d1d5db',
  },
  modalAttemptsCount: {
    fontSize: 13,
    color: '#ef4444',
    fontWeight: '600',
    textAlign: 'center',
  },
  modalFooter: {
    flexDirection: 'row',
    justifyContent: 'flex-end',
    gap: 10,
    paddingHorizontal: 16,
    paddingVertical: 14,
    borderTopWidth: 1,
    borderTopColor: '#f3f4f6',
    marginTop: 8,
  },
  modalBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 10,
    paddingHorizontal: 22,
    borderRadius: 10,
    minWidth: 72,
  },
  modalBtnPrimary: {
    backgroundColor: '#ef4444',
  },
  modalBtnRetry: {
    backgroundColor: '#f0fdf4',
    borderWidth: 1.5,
    borderColor: colors.brand,
  },
  modalBtnText: {
    fontSize: 15,
    fontWeight: '700',
  },
});
