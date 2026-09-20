import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  TextInput,
  Alert,
  Switch,
  ActivityIndicator,
  StatusBar,
  Platform,
  Linking,
  Modal,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as LocalAuthentication from 'expo-local-authentication';
import { authService, accountService, fundTransferService, connectionService } from '../services/api';
import { colors } from '../constants/colors';
import { API_BASE_URL } from '../config';
import { useAutoRefresh } from '../hooks/useAutoRefresh';

const CUSTOM_SERVER_KEY = 'customServerUrl';

const toErrStr = (err) => {
  if (!err) return '';
  if (typeof err === 'string') return err;
  if (err instanceof Error) return err.message || String(err);
  if (typeof err === 'object') {
    const msgs = Object.values(err).flat();
    if (msgs.length) return msgs.map(String).join('. ');
  }
  return String(err);
};

export default function SettingsScreen({ navigation }) {
  const [member, setMember] = useState(null);
  const [serverUrl, setServerUrl] = useState(API_BASE_URL);
  const [customUrl, setCustomUrl] = useState('');
  const [editingUrl, setEditingUrl] = useState(false);
  const [testingConnection, setTestingConnection] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState(null); // null | 'ok' | 'fail'
  const [fingerprintAvailable, setFingerprintAvailable] = useState(false);
  const [fingerprintEnabled, setFingerprintEnabled] = useState(false);
  const [otpModal, setOtpModal] = useState(false);
  const [otpCode, setOtpCode] = useState('');
  const [otpSending, setOtpSending] = useState(false);
  const [otpVerifying, setOtpVerifying] = useState(false);
  const [otpError, setOtpError] = useState('');
  const [appVersion] = useState('1.0.4');
  const [storeInfo, setStoreInfo] = useState(null);

  // Opens Google Maps (or Apple Maps on iOS) directly in turn-by-turn navigation
  const openNavigation = () => {
    // Helper: parse lat/lng from a Google Maps URL (mirrors server-side logic)
    const parseCoordsFromUrl = (url) => {
      if (!url) return null;
      // Priority 1: !3d<lat>!4d<lng> — actual pin coordinates
      const latM = url.match(/!3d(-?\d+\.\d+)/);
      const lngM = url.match(/!4d(-?\d+\.\d+)/);
      if (latM && lngM) return { lat: parseFloat(latM[1]), lng: parseFloat(lngM[1]) };
      // Priority 2: /@lat,lng,zoom — viewport center
      const atM = url.match(/\/@(-?\d+\.\d+),(-?\d+\.\d+)/);
      if (atM) return { lat: parseFloat(atM[1]), lng: parseFloat(atM[2]) };
      // Priority 3: ?q=lat,lng
      const qM = url.match(/[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)/);
      if (qM) return { lat: parseFloat(qM[1]), lng: parseFloat(qM[2]) };
      return null;
    };

    // Resolve coordinates: prefer server-parsed values, then parse URL, then address
    let lat = storeInfo?.latitude ? parseFloat(storeInfo.latitude) : null;
    let lng = storeInfo?.longitude ? parseFloat(storeInfo.longitude) : null;

    if ((!lat || !lng) && storeInfo?.maps_url) {
      const parsed = parseCoordsFromUrl(storeInfo.maps_url);
      if (parsed) { lat = parsed.lat; lng = parsed.lng; }
    }

    const launchNav = (lat, lng) => {
      const googleNav = Platform.select({
        android: `google.navigation:q=${lat},${lng}&mode=d`,
        ios: `comgooglemaps://?daddr=${lat},${lng}&directionsmode=driving`,
      });
      const webFallback = `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}&travelmode=driving`;
      const appleMaps = `maps://maps.apple.com/?daddr=${lat},${lng}&dirflg=d`;
      Linking.canOpenURL(googleNav)
        .then((supported) => {
          if (supported) return Linking.openURL(googleNav);
          if (Platform.OS === 'ios') return Linking.openURL(appleMaps);
          return Linking.openURL(webFallback);
        })
        .catch(() => Linking.openURL(webFallback));
    };

    if (lat && lng) {
      launchNav(lat, lng);
    } else if (storeInfo?.maps_url) {
      // Last resort: open the URL as-is (will open Google Maps)
      Linking.openURL(storeInfo.maps_url);
    } else {
      const addr = [
        storeInfo?.address_line1,
        storeInfo?.address_line2,
        storeInfo?.city,
        storeInfo?.province,
      ].filter(Boolean).join(', ');
      if (addr) {
        Linking.openURL(
          `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(addr)}&travelmode=driving`
        );
      }
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  // Refresh member data every 60 seconds while screen is focused
  const autoRefreshCallback = useCallback(() => {
    loadData();
  }, []);
  useAutoRefresh(autoRefreshCallback, 60000);

  const brandDisplayTitle = (info) => {
    if (!info) return 'Self Checkout';
    if (info.show_store_name === false) {
      return info.system_name || 'Self Checkout';
    }
    return info.system_name || info.store_name || 'Self Checkout';
  };

  const loadData = async () => {
    try {
      const storedMember = await authService.getStoredMember();
      setMember(storedMember);

      // Fetch store info
      try {
        const storeRes = await connectionService.fetchStoreInfo();
        if (storeRes?.store) setStoreInfo(storeRes.store);
      } catch {
        // keep storeInfo null — UI will show defaults
      }

      // Fetch fresh member data from API to get up-to-date RFID and balance
      try {
        const freshData = await accountService.getAccountInfo();
        if (freshData?.member) {
          await AsyncStorage.setItem('memberData', JSON.stringify(freshData.member));
          setMember(freshData.member);
        }
      } catch {
        // If API call fails, keep using stored data
      }

      const saved = await AsyncStorage.getItem(CUSTOM_SERVER_KEY);
      if (saved) {
        setServerUrl(saved);
        setCustomUrl(saved);
      } else {
        setCustomUrl(API_BASE_URL);
      }

      const compatible = await LocalAuthentication.hasHardwareAsync();
      const enrolled = await LocalAuthentication.isEnrolledAsync();
      setFingerprintAvailable(compatible && enrolled);

      const bioEnabled = await AsyncStorage.getItem('biometricEnabled');
      setFingerprintEnabled(bioEnabled === 'true');
    } catch {
      // ignore
    }
  };

  const handleFingerprintToggle = async (value) => {
    if (!value) {
      // Turning OFF — no OTP needed
      setFingerprintEnabled(false);
      await AsyncStorage.setItem('biometricEnabled', 'false');
      return;
    }

    if (!fingerprintAvailable) {
      Alert.alert(
        'Fingerprint Unavailable',
        'No fingerprint is enrolled on this device. Please set up fingerprint in your device settings first.',
        [{ text: 'OK' }]
      );
      return;
    }

    if (!member?.email) {
      Alert.alert(
        'Email Required',
        'Your account has no email address. Please contact your administrator before enabling fingerprint login.',
        [{ text: 'OK' }]
      );
      return;
    }

    // Send OTP then open modal
    setOtpSending(true);
    setOtpError('');
    setOtpCode('');
    try {
      await fundTransferService.requestBiometricOTP();
      setOtpModal(true);
    } catch (err) {
      Alert.alert('Error', toErrStr(err) || 'Could not send OTP. Please try again.');
    } finally {
      setOtpSending(false);
    }
  };

  const handleOtpVerify = async () => {
    if (otpCode.length !== 6) {
      setOtpError('Please enter the 6-digit code.');
      return;
    }
    setOtpVerifying(true);
    setOtpError('');
    try {
      await fundTransferService.verifyBiometricOTP(otpCode);
      await AsyncStorage.setItem('biometricEnabled', 'true');
      setFingerprintEnabled(true);
      setOtpModal(false);
      setOtpCode('');
      Alert.alert('Success', 'Fingerprint login has been enabled.');
    } catch (err) {
      setOtpError(toErrStr(err) || 'Invalid or expired code. Try again.');
    } finally {
      setOtpVerifying(false);
    }
  };

  const handleResendOtp = async () => {
    setOtpSending(true);
    setOtpError('');
    setOtpCode('');
    try {
      await fundTransferService.requestBiometricOTP();
      Alert.alert('Sent', 'A new verification code has been sent to your email.');
    } catch (err) {
      setOtpError(toErrStr(err) || 'Failed to resend OTP.');
    } finally {
      setOtpSending(false);
    }
  };

  const handleSaveServerUrl = async () => {
    const trimmed = customUrl.trim().replace(/\/+$/, '');
    if (!trimmed) {
      Alert.alert('Invalid URL', 'Please enter a valid server URL.');
      return;
    }
    try {
      new URL(trimmed);
    } catch {
      Alert.alert('Invalid URL', 'The URL format is invalid. Example: https://your-server.com');
      return;
    }
    await AsyncStorage.setItem(CUSTOM_SERVER_KEY, trimmed);
    setServerUrl(trimmed);
    setEditingUrl(false);
    Alert.alert(
      'Saved',
      'Server URL updated. Restart the app for changes to take full effect.',
      [{ text: 'OK' }]
    );
  };

  const handleResetServerUrl = async () => {
    Alert.alert(
      'Reset Server URL',
      'Reset to the default server URL?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Reset',
          style: 'destructive',
          onPress: async () => {
            await AsyncStorage.removeItem(CUSTOM_SERVER_KEY);
            setServerUrl(API_BASE_URL);
            setCustomUrl(API_BASE_URL);
            setEditingUrl(false);
            setConnectionStatus(null);
          },
        },
      ]
    );
  };

  const handleTestConnection = async () => {
    setTestingConnection(true);
    setConnectionStatus(null);
    try {
      const url = (customUrl.trim().replace(/\/+$/, '') || serverUrl) + '/api/mobile/health/';
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 8000);
      const res = await fetch(url, { signal: controller.signal });
      clearTimeout(timeout);
      setConnectionStatus(res.ok ? 'ok' : 'fail');
    } catch {
      setConnectionStatus('fail');
    } finally {
      setTestingConnection(false);
    }
  };

  const handleLogout = async () => {
    Alert.alert(
      'Logout',
      'Are you sure you want to logout?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Logout',
          style: 'destructive',
          onPress: async () => {
            try {
              await authService.logout();
            } catch {
              // ignore
            }
            navigation.replace('Login');
          },
        },
      ]
    );
  };

  // ─── UI helpers ────────────────────────────────────────────────────────────

  const SectionHeader = ({ title }) => (
    <Text style={styles.sectionHeader}>{title}</Text>
  );

  const SettingRow = ({ icon, label, value, onPress, rightElement, danger }) => (
    <TouchableOpacity
      style={styles.row}
      onPress={onPress}
      activeOpacity={onPress ? 0.7 : 1}
      disabled={!onPress}
    >
      <View style={[styles.rowIconWrap, danger && styles.rowIconWrapDanger]}>
        <Ionicons name={icon} size={18} color={danger ? colors.error : colors.brand} />
      </View>
      <View style={styles.rowContent}>
        <Text style={[styles.rowLabel, danger && { color: colors.error }]}>{label}</Text>
        {value ? <Text style={styles.rowValue} numberOfLines={1}>{value}</Text> : null}
      </View>
      {rightElement || (onPress ? (
        <Ionicons name="chevron-forward" size={16} color={colors.muted} />
      ) : null)}
    </TouchableOpacity>
  );

  const Divider = () => <View style={styles.divider} />;

  // ───────────────────────────────────────────────────────────────────────────

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.brand} />

      {/* ── Biometric OTP Verification Modal ── */}
      <Modal
        transparent
        animationType="fade"
        visible={otpModal}
        onRequestClose={() => { setOtpModal(false); setOtpCode(''); setOtpError(''); }}
      >
        <View style={styles.otpOverlay}>
          <View style={styles.otpCard}>
            {/* Header */}
            <View style={styles.otpHeader}>
              <Ionicons name="finger-print" size={24} color="#fff" style={{ marginRight: 8 }} />
              <Text style={styles.otpHeaderTitle}>Verify Your Identity</Text>
            </View>

            {/* Body */}
            <View style={styles.otpBody}>
              <Ionicons name="mail-outline" size={40} color={colors.brand} style={{ marginBottom: 12 }} />
              <Text style={styles.otpSubtitle}>
                A 6-digit code was sent to
              </Text>
              <Text style={styles.otpEmail}>{member?.email || 'your email'}</Text>
              <Text style={styles.otpNote}>
                Enter the code below to enable Fingerprint Login.
              </Text>

              <TextInput
                style={[styles.otpInput, otpError ? styles.otpInputError : null]}
                value={otpCode}
                onChangeText={(t) => { setOtpCode(t.replace(/\D/g, '').slice(0, 6)); setOtpError(''); }}
                keyboardType="number-pad"
                maxLength={6}
                placeholder="000000"
                placeholderTextColor={colors.muted}
                textAlign="center"
                autoFocus
              />

              {otpError ? (
                <Text style={styles.otpErrorText}>{otpError}</Text>
              ) : null}

              <TouchableOpacity
                style={[styles.otpVerifyBtn, (otpVerifying || otpCode.length !== 6) && { opacity: 0.6 }]}
                onPress={handleOtpVerify}
                disabled={otpVerifying || otpCode.length !== 6}
              >
                {otpVerifying ? (
                  <ActivityIndicator color="#fff" size="small" />
                ) : (
                  <Text style={styles.otpVerifyBtnText}>Verify & Enable</Text>
                )}
              </TouchableOpacity>

              <TouchableOpacity
                style={styles.otpResendBtn}
                onPress={handleResendOtp}
                disabled={otpSending}
              >
                {otpSending ? (
                  <ActivityIndicator color={colors.brand} size="small" />
                ) : (
                  <Text style={styles.otpResendText}>Resend Code</Text>
                )}
              </TouchableOpacity>
            </View>

            {/* Cancel */}
            <TouchableOpacity
              style={styles.otpCancelBtn}
              onPress={() => { setOtpModal(false); setOtpCode(''); setOtpError(''); }}
            >
              <Text style={styles.otpCancelText}>Cancel</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Settings</Text>
      </View>

      <ScrollView style={styles.scroll} contentContainerStyle={styles.scrollContent} showsVerticalScrollIndicator={false}>

        {/* Account */}
        <SectionHeader title="ACCOUNT" />
        <View style={styles.card}>
          {/* Avatar + Name */}
          <View style={styles.profileRow}>
            <View style={styles.avatarCircle}>
              <Ionicons name="person" size={28} color={colors.brand} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.profileName}>
                {member?.full_name || member?.username || 'Member'}
              </Text>
              <Text style={styles.profileSub}>
                {member?.member_type_name || (member?.member_type === 'admin' ? 'Administrator' : member?.member_type === 'staff' ? 'Staff' : 'Member')}
              </Text>
              <View style={[styles.statusBadge, { backgroundColor: member?.is_active ? '#d1fae5' : '#fee2e2' }]}>
                <View style={[styles.statusDot, { backgroundColor: member?.is_active ? colors.success : colors.error }]} />
                <Text style={[styles.statusText, { color: member?.is_active ? colors.success : colors.error }]}>
                  {member?.is_active ? 'Active' : 'Inactive'}
                </Text>
              </View>
            </View>
          </View>

          <View style={styles.profileDivider} />

          {/* RFID Card */}
          <View style={styles.infoRow}>
            <View style={styles.infoIconWrap}>
              <Ionicons name="card-outline" size={16} color={colors.brand} />
            </View>
            <View style={styles.infoContent}>
              <Text style={styles.infoLabel}>RFID Card Number</Text>
              <Text style={styles.infoValue}>{member?.rfid_card_number_full || member?.rfid_card_number || '—'}</Text>
            </View>
          </View>

          <View style={styles.profileDivider} />

          {/* Balance */}
          <View style={styles.infoRow}>
            <View style={styles.infoIconWrap}>
              <Ionicons name="wallet-outline" size={16} color={colors.brand} />
            </View>
            <View style={styles.infoContent}>
              <Text style={styles.infoLabel}>Balance</Text>
              <Text style={[styles.infoValue, styles.balanceValue]}>
                ₱{member?.balance != null ? parseFloat(member.balance).toFixed(2) : '0.00'}
              </Text>
            </View>
          </View>

          <View style={styles.profileDivider} />

          {/* Email */}
          <View style={styles.infoRow}>
            <View style={styles.infoIconWrap}>
              <Ionicons name="mail-outline" size={16} color={colors.brand} />
            </View>
            <View style={styles.infoContent}>
              <Text style={styles.infoLabel}>Email</Text>
              <Text style={styles.infoValue}>{member?.email || '—'}</Text>
            </View>
          </View>

          <View style={styles.profileDivider} />

          {/* Phone */}
          <View style={styles.infoRow}>
            <View style={styles.infoIconWrap}>
              <Ionicons name="call-outline" size={16} color={colors.brand} />
            </View>
            <View style={styles.infoContent}>
              <Text style={styles.infoLabel}>Phone</Text>
              <Text style={styles.infoValue}>{member?.phone || '—'}</Text>
            </View>
          </View>

          <View style={styles.profileDivider} />

          {/* Date Joined */}
          <View style={styles.infoRow}>
            <View style={styles.infoIconWrap}>
              <Ionicons name="calendar-outline" size={16} color={colors.brand} />
            </View>
            <View style={styles.infoContent}>
              <Text style={styles.infoLabel}>Date Joined</Text>
              <Text style={styles.infoValue}>
                {member?.date_joined
                  ? new Date(member.date_joined).toLocaleDateString('en-PH', { year: 'numeric', month: 'long', day: 'numeric' })
                  : '—'}
              </Text>
            </View>
          </View>

          <View style={styles.profileDivider} />

          {/* Last Transaction */}
          <View style={styles.infoRow}>
            <View style={styles.infoIconWrap}>
              <Ionicons name="time-outline" size={16} color={colors.brand} />
            </View>
            <View style={styles.infoContent}>
              <Text style={styles.infoLabel}>Last Transaction</Text>
              <Text style={styles.infoValue}>
                {member?.last_transaction
                  ? new Date(member.last_transaction).toLocaleString('en-PH', { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
                  : 'No transactions yet'}
              </Text>
            </View>
          </View>
        </View>

        {/* Security */}
        <SectionHeader title="SECURITY" />
        <View style={styles.card}>
          <SettingRow
            icon="finger-print"
            label="Fingerprint Login"
            value={
              !fingerprintAvailable
                ? 'Not available on this device'
                : fingerprintEnabled
                ? 'Enabled — tap to disable'
                : 'Disabled — tap to enable (OTP required)'
            }
            rightElement={
              otpSending ? (
                <ActivityIndicator size="small" color={colors.brand} style={{ marginRight: 4 }} />
              ) : (
                <Switch
                  value={fingerprintEnabled}
                  onValueChange={handleFingerprintToggle}
                  trackColor={{ false: colors.border, true: colors.brand }}
                  thumbColor={fingerprintEnabled ? '#fff' : '#f4f3f4'}
                  disabled={!fingerprintAvailable || otpSending}
                />
              )
            }
          />
        </View>

        {/* Server Configuration */}
        <SectionHeader title="SERVER CONFIGURATION" />
        <View style={styles.card}>
          {editingUrl ? (
            <View style={styles.urlEditWrap}>
              <Text style={styles.urlEditLabel}>Server URL</Text>
              <TextInput
                style={styles.urlInput}
                value={customUrl}
                onChangeText={setCustomUrl}
                placeholder="https://your-server.com"
                placeholderTextColor={colors.muted}
                autoCapitalize="none"
                autoCorrect={false}
                keyboardType="url"
              />
              <View style={styles.urlButtonRow}>
                <TouchableOpacity
                  style={[styles.urlBtn, styles.urlBtnOutline]}
                  onPress={() => { setEditingUrl(false); setCustomUrl(serverUrl); setConnectionStatus(null); }}
                >
                  <Text style={styles.urlBtnOutlineText}>Cancel</Text>
                </TouchableOpacity>
                <TouchableOpacity style={[styles.urlBtn, styles.urlBtnPrimary]} onPress={handleSaveServerUrl}>
                  <Text style={styles.urlBtnPrimaryText}>Save</Text>
                </TouchableOpacity>
              </View>
            </View>
          ) : (
            <>
              <SettingRow
                icon="server-outline"
                label="Server URL"
                value={serverUrl}
                onPress={() => setEditingUrl(true)}
              />
              <Divider />
            </>
          )}

          {/* Connection test */}
          <TouchableOpacity style={styles.testRow} onPress={handleTestConnection} disabled={testingConnection}>
            <View style={styles.rowIconWrap}>
              {testingConnection ? (
                <ActivityIndicator size="small" color={colors.brand} />
              ) : (
                <Ionicons
                  name={connectionStatus === 'ok' ? 'checkmark-circle' : connectionStatus === 'fail' ? 'close-circle' : 'wifi'}
                  size={18}
                  color={connectionStatus === 'ok' ? colors.success : connectionStatus === 'fail' ? colors.error : colors.brand}
                />
              )}
            </View>
            <View style={styles.rowContent}>
              <Text style={styles.rowLabel}>Test Connection</Text>
              {connectionStatus === 'ok' && <Text style={[styles.rowValue, { color: colors.success }]}>Connected successfully</Text>}
              {connectionStatus === 'fail' && <Text style={[styles.rowValue, { color: colors.error }]}>Connection failed</Text>}
              {connectionStatus === null && !testingConnection && <Text style={styles.rowValue}>Tap to test</Text>}
            </View>
            <Ionicons name="chevron-forward" size={16} color={colors.muted} />
          </TouchableOpacity>

          {serverUrl !== API_BASE_URL && (
            <>
              <Divider />
              <SettingRow
                icon="refresh-outline"
                label="Reset to Default URL"
                onPress={handleResetServerUrl}
              />
            </>
          )}
        </View>

        {/* Store Information */}
        <SectionHeader title="STORE INFORMATION" />
        <View style={styles.card}>
          {/* Store name + branch */}
          <View style={styles.storeHeaderRow}>
            <View style={styles.storeIconCircle}>
              <Ionicons name="storefront-outline" size={26} color={colors.brand} />
            </View>
            <View style={{ flex: 1 }}>
              <Text style={styles.storeName}>
                {brandDisplayTitle(storeInfo)}
              </Text>
              {storeInfo?.branch_name ? (
                <Text style={styles.storeBranch}>{storeInfo.branch_name}</Text>
              ) : null}
              {storeInfo?.tagline ? (
                <Text style={styles.storeTagline}>"{storeInfo.tagline}"</Text>
              ) : null}
            </View>
          </View>

          <View style={styles.profileDivider} />

          {/* Address */}
          {(storeInfo?.address_line1 || storeInfo?.city) ? (
            <>
              <TouchableOpacity
                style={styles.infoRow}
                onPress={openNavigation}
                activeOpacity={0.7}
              >
                <View style={styles.infoIconWrap}>
                  <Ionicons name="navigate" size={16} color={colors.brand} />
                </View>
                <View style={styles.infoContent}>
                  <Text style={styles.infoLabel}>Address</Text>
                  <Text style={[styles.infoValue, styles.linkValue]}>
                    {[
                      storeInfo.address_line1,
                      storeInfo.address_line2,
                      [storeInfo.city, storeInfo.province].filter(Boolean).join(', '),
                      storeInfo.zip_code,
                    ].filter(Boolean).join('\n')}
                  </Text>
                  <Text style={styles.mapsHint}>Tap to start navigation</Text>
                </View>
                <Ionicons name="chevron-forward" size={16} color={colors.muted} />
              </TouchableOpacity>
              <View style={styles.profileDivider} />
            </>
          ) : null}

          {/* Contact number */}
          {storeInfo?.contact_number ? (
            <>
              <TouchableOpacity
                style={styles.infoRow}
                onPress={() => Linking.openURL(`tel:${storeInfo.contact_number}`)}
                activeOpacity={0.7}
              >
                <View style={styles.infoIconWrap}>
                  <Ionicons name="call-outline" size={16} color={colors.brand} />
                </View>
                <View style={styles.infoContent}>
                  <Text style={styles.infoLabel}>Contact Number</Text>
                  <Text style={[styles.infoValue, styles.linkValue]}>{storeInfo.contact_number}</Text>
                  {storeInfo.alt_contact_number ? (
                    <Text style={[styles.infoValue, styles.linkValue]}>{storeInfo.alt_contact_number}</Text>
                  ) : null}
                </View>
                <Ionicons name="chevron-forward" size={16} color={colors.muted} />
              </TouchableOpacity>
              <View style={styles.profileDivider} />
            </>
          ) : null}

          {/* Email */}
          {storeInfo?.email ? (
            <>
              <TouchableOpacity
                style={styles.infoRow}
                onPress={() => Linking.openURL(`mailto:${storeInfo.email}`)}
                activeOpacity={0.7}
              >
                <View style={styles.infoIconWrap}>
                  <Ionicons name="mail-outline" size={16} color={colors.brand} />
                </View>
                <View style={styles.infoContent}>
                  <Text style={styles.infoLabel}>Email</Text>
                  <Text style={[styles.infoValue, styles.linkValue]}>{storeInfo.email}</Text>
                </View>
                <Ionicons name="chevron-forward" size={16} color={colors.muted} />
              </TouchableOpacity>
              <View style={styles.profileDivider} />
            </>
          ) : null}

          {/* Website */}
          {storeInfo?.website ? (
            <>
              <TouchableOpacity
                style={styles.infoRow}
                onPress={() => Linking.openURL(storeInfo.website)}
                activeOpacity={0.7}
              >
                <View style={styles.infoIconWrap}>
                  <Ionicons name="globe-outline" size={16} color={colors.brand} />
                </View>
                <View style={styles.infoContent}>
                  <Text style={styles.infoLabel}>Website</Text>
                  <Text style={[styles.infoValue, styles.linkValue]}>{storeInfo.website}</Text>
                </View>
                <Ionicons name="chevron-forward" size={16} color={colors.muted} />
              </TouchableOpacity>
              <View style={styles.profileDivider} />
            </>
          ) : null}

          {/* Business Hours */}
          {storeInfo?.business_hours ? (
            <View style={styles.infoRow}>
              <View style={styles.infoIconWrap}>
                <Ionicons name="time-outline" size={16} color={colors.brand} />
              </View>
              <View style={styles.infoContent}>
                <Text style={styles.infoLabel}>Business Hours</Text>
                <Text style={styles.infoValue}>{storeInfo.business_hours}</Text>
              </View>
            </View>
          ) : null}
        </View>

        {/* App Info */}
        <SectionHeader title="APP INFO" />
        <View style={styles.card}>
          <SettingRow icon="information-circle-outline" label="App Name" value={brandDisplayTitle(storeInfo)} />
          <Divider />
          <SettingRow icon="code-slash-outline" label="Version" value={appVersion} />
          <Divider />
          <SettingRow icon="phone-portrait-outline" label="Platform" value={Platform.OS === 'ios' ? 'iOS' : 'Android'} />
        </View>

        {/* Logout */}
        <SectionHeader title="" />
        <View style={styles.card}>
          <SettingRow
            icon="log-out-outline"
            label="Logout"
            onPress={handleLogout}
            danger
          />
        </View>

        <View style={{ height: 32 }} />
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  header: {
    backgroundColor: colors.brand,
    paddingTop: Platform.OS === 'android' ? StatusBar.currentHeight + 12 : 52,
    paddingBottom: 16,
    paddingHorizontal: 20,
  },
  headerTitle: {
    color: '#fff',
    fontSize: 22,
    fontWeight: '700',
  },
  scroll: {
    flex: 1,
  },
  scrollContent: {
    paddingHorizontal: 16,
    paddingTop: 16,
  },
  sectionHeader: {
    fontSize: 11,
    fontWeight: '700',
    color: colors.muted,
    letterSpacing: 1,
    marginBottom: 6,
    marginTop: 12,
    marginLeft: 4,
  },
  card: {
    backgroundColor: colors.panel,
    borderRadius: 12,
    overflow: 'hidden',
    marginBottom: 4,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 4,
    elevation: 2,
  },
  profileRow: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: 16,
    gap: 14,
  },
  avatarCircle: {
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: '#e6f4ec',
    alignItems: 'center',
    justifyContent: 'center',
  },
  profileName: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  profileSub: {
    fontSize: 13,
    color: colors.textSecondary,
    marginTop: 2,
  },
  profileDivider: {
    height: 1,
    backgroundColor: colors.borderLight,
    marginHorizontal: 16,
  },
  statusBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    alignSelf: 'flex-start',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 10,
    marginTop: 6,
    gap: 4,
  },
  statusDot: {
    width: 6,
    height: 6,
    borderRadius: 3,
  },
  statusText: {
    fontSize: 11,
    fontWeight: '600',
  },
  infoRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 12,
    paddingHorizontal: 16,
    gap: 12,
  },
  infoIconWrap: {
    width: 30,
    height: 30,
    borderRadius: 8,
    backgroundColor: '#e6f4ec',
    alignItems: 'center',
    justifyContent: 'center',
  },
  infoContent: {
    flex: 1,
  },
  infoLabel: {
    fontSize: 11,
    color: colors.muted,
    fontWeight: '600',
    letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  infoValue: {
    fontSize: 14,
    color: colors.textPrimary,
    fontWeight: '500',
    marginTop: 2,
  },
  balanceValue: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.brand,
  },
  storeHeaderRow: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    padding: 16,
    gap: 14,
  },
  storeIconCircle: {
    width: 52,
    height: 52,
    borderRadius: 26,
    backgroundColor: '#e6f4ec',
    alignItems: 'center',
    justifyContent: 'center',
  },
  storeName: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  storeBranch: {
    fontSize: 13,
    color: colors.textSecondary,
    marginTop: 2,
  },
  storeTagline: {
    fontSize: 12,
    color: colors.muted,
    fontStyle: 'italic',
    marginTop: 4,
  },
  linkValue: {
    color: colors.brand,
    textDecorationLine: 'underline',
  },
  mapsHint: {
    fontSize: 11,
    color: colors.brand,
    marginTop: 4,
    fontStyle: 'italic',
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 13,
    paddingHorizontal: 16,
    gap: 12,
  },
  testRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 13,
    paddingHorizontal: 16,
    gap: 12,
  },
  rowIconWrap: {
    width: 32,
    height: 32,
    borderRadius: 8,
    backgroundColor: '#e6f4ec',
    alignItems: 'center',
    justifyContent: 'center',
  },
  rowIconWrapDanger: {
    backgroundColor: '#fef2f2',
  },
  rowContent: {
    flex: 1,
  },
  rowLabel: {
    fontSize: 15,
    color: colors.textPrimary,
    fontWeight: '500',
  },
  rowValue: {
    fontSize: 12,
    color: colors.textSecondary,
    marginTop: 2,
  },
  divider: {
    height: 1,
    backgroundColor: colors.borderLight,
    marginLeft: 60,
  },
  urlEditWrap: {
    padding: 16,
  },
  urlEditLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textSecondary,
    marginBottom: 8,
  },
  urlInput: {
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    fontSize: 14,
    color: colors.textPrimary,
    backgroundColor: colors.background,
  },
  urlButtonRow: {
    flexDirection: 'row',
    gap: 10,
    marginTop: 12,
    justifyContent: 'flex-end',
  },
  urlBtn: {
    paddingHorizontal: 20,
    paddingVertical: 9,
    borderRadius: 8,
  },
  urlBtnOutline: {
    borderWidth: 1,
    borderColor: colors.border,
  },
  urlBtnOutlineText: {
    fontSize: 14,
    color: colors.textSecondary,
    fontWeight: '500',
  },
  urlBtnPrimary: {
    backgroundColor: colors.brand,
  },
  urlBtnPrimaryText: {
    fontSize: 14,
    color: '#fff',
    fontWeight: '600',
  },

  // ── OTP Modal ──
  otpOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.55)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 24,
  },
  otpCard: {
    width: '100%',
    backgroundColor: '#fff',
    borderRadius: 20,
    overflow: 'hidden',
  },
  otpHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.brand,
    paddingVertical: 16,
    paddingHorizontal: 20,
  },
  otpHeaderTitle: {
    fontSize: 17,
    fontWeight: '700',
    color: '#fff',
  },
  otpBody: {
    alignItems: 'center',
    paddingHorizontal: 24,
    paddingTop: 24,
    paddingBottom: 8,
  },
  otpSubtitle: {
    fontSize: 14,
    color: colors.textSecondary || '#666',
    textAlign: 'center',
  },
  otpEmail: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.brand,
    marginTop: 2,
    marginBottom: 10,
    textAlign: 'center',
  },
  otpNote: {
    fontSize: 13,
    color: colors.textSecondary || '#666',
    textAlign: 'center',
    marginBottom: 20,
  },
  otpInput: {
    width: '70%',
    borderWidth: 2,
    borderColor: colors.border || '#e5e7eb',
    borderRadius: 12,
    paddingVertical: 14,
    fontSize: 28,
    fontWeight: '800',
    letterSpacing: 10,
    color: colors.brand,
    backgroundColor: '#f9fafb',
    textAlign: 'center',
    marginBottom: 10,
  },
  otpInputError: {
    borderColor: '#ef4444',
  },
  otpErrorText: {
    fontSize: 13,
    color: '#ef4444',
    marginBottom: 8,
    textAlign: 'center',
  },
  otpVerifyBtn: {
    width: '100%',
    backgroundColor: colors.brand,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 8,
    marginBottom: 10,
  },
  otpVerifyBtnText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '700',
  },
  otpResendBtn: {
    paddingVertical: 8,
    alignItems: 'center',
  },
  otpResendText: {
    fontSize: 14,
    color: colors.brand,
    fontWeight: '600',
  },
  otpCancelBtn: {
    borderTopWidth: 1,
    borderTopColor: colors.border || '#e5e7eb',
    paddingVertical: 14,
    alignItems: 'center',
  },
  otpCancelText: {
    fontSize: 15,
    color: colors.error || '#ef4444',
    fontWeight: '600',
  },
});
