import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TextInput,
  TouchableOpacity,
  Alert,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Modal,
  Keyboard,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { CameraView, Camera, useCameraPermissions } from 'expo-camera';
import * as ImagePicker from 'expo-image-picker';
import QRCode from 'react-native-qrcode-svg';
import { fundTransferService, accountService } from '../services/api';
import { useAutoRefresh } from '../hooks/useAutoRefresh';
import { colors } from '../constants/colors';

// ─── Design Tokens ────────────────────────────────────────────────────────────
const C = {
  primary:     colors.accent,
  green:       colors.brand,
  greenMid:    colors.brand,
  greenLight:  '#E8F5E9',
  greenPale:   '#F1F8F2',
  greenBorder: '#A5D6A7',
  white:       colors.textWhite,
  bg:          colors.background,
  surface:     colors.panel,
  ink:         colors.textPrimary,
  ink2:        colors.textPrimary,
  ink3:        colors.textSecondary,
  divider:     colors.border,
  red:         colors.error,
  redLight:    '#FFEBEE',
  amber:       colors.warning,
  amberLight:  '#FFF3E0',
};

// ─── Helpers ──────────────────────────────────────────────────────────────────
const fmt = (n) =>
  `₱${parseFloat(n || 0).toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;

const fmtDate = (d) =>
  new Date(d).toLocaleString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });

const fmtExpiry = (d) =>
  new Date(d).toLocaleString('en-US', {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  });

const initials = (name = '') =>
  name.split(' ').map((w) => w[0]).join('').slice(0, 2).toUpperCase();

const fmtTimer = (s) => {
  if (!s || s < 0) return '00:00';
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
};

const QUICK_AMOUNTS = [100, 500, 1000, 5000];

// Convert any error value (string, object, Error) to a displayable string
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

// ─── 6-Box OTP Input ──────────────────────────────────────────────────────────
const OTPBoxInput = React.forwardRef(({ value, onChange, autoFocus }, forwardedRef) => {
  const localRef = useRef(null);
  const inputRef = forwardedRef || localRef;
  const digits = Array.from({ length: 6 }, (_, i) => value[i] || '');
  return (
    <TouchableOpacity
      onPress={() => inputRef.current?.focus()}
      activeOpacity={1}
      style={s.otpWrapper}
    >
      {digits.map((digit, i) => (
        <View
          key={i}
          style={[
            s.otpBox,
            value.length === i && s.otpBoxActive,
            digit && s.otpBoxFilled,
          ]}
        >
          <Text style={s.otpBoxText}>{digit}</Text>
        </View>
      ))}
      <TextInput
        ref={inputRef}
        style={s.otpHidden}
        value={value}
        onChangeText={(v) => {
          const clean = v.replace(/[^0-9]/g, '').slice(0, 6);
          onChange(clean);
          if (clean.length === 6) Keyboard.dismiss();
        }}
        keyboardType="number-pad"
        maxLength={6}
        autoFocus={autoFocus}
        caretHidden
        showSoftInputOnFocus
      />
    </TouchableOpacity>
  );
});

// ─────────────────────────────────────────────────────────────────────────────
export default function FundTransferScreen({ navigation }) {
  const [searchQuery, setSearchQuery]           = useState('');
  const [amount, setAmount]                     = useState('');
  const [notes, setNotes]                       = useState('');
  const [recipient, setRecipient]               = useState(null);
  const [searchResults, setSearchResults]       = useState([]);
  const [searching, setSearching]               = useState(false);
  const [currentBalance, setCurrentBalance]     = useState(null);
  const [showOTPModal, setShowOTPModal]         = useState(false);
  const [otpCode, setOtpCode]                   = useState('');
  const [requestingOTP, setRequestingOTP]       = useState(false);
  const [verifyingOTP, setVerifyingOTP]         = useState(false);
  const [otpExpiresIn, setOtpExpiresIn]         = useState(null);
  const [otpExpiryDate, setOtpExpiryDate]       = useState(null);
  const [showSuccess, setShowSuccess]           = useState(false);
  const [transactionData, setTransactionData]   = useState(null);

  // ── QR state ────────────────────────────────────────────────────────────
  const [showQRScanner, setShowQRScanner]       = useState(false);
  const [showMyQR, setShowMyQR]                 = useState(false);
  const [myQRToken, setMyQRToken]               = useState(null);
  const [loadingMyQR, setLoadingMyQR]           = useState(false);
  const [scanningQR, setScanningQR]             = useState(false);
  const [cameraPermission, requestCameraPermission] = useCameraPermissions();
  const qrScanLock                              = useRef(false);

  const searchTimeout   = useRef(null);
  const otpTimer        = useRef(null);
  const otpInputRef     = useRef(null);
  const skipNextSearch  = useRef(false);

  useEffect(() => {
    loadCurrentBalance();
    return () => {
      clearTimeout(searchTimeout.current);
      clearInterval(otpTimer.current);
    };
  }, []);

  // Auto-refresh balance every 30 seconds
  const autoRefreshCallback = useCallback(() => {
    loadCurrentBalance();
  }, []);
  useAutoRefresh(autoRefreshCallback, 30000);

  useEffect(() => {
    if (skipNextSearch.current) {
      skipNextSearch.current = false;
      return;
    }
    if (searchQuery.trim().length >= 2) {
      clearTimeout(searchTimeout.current);
      searchTimeout.current = setTimeout(handleSearchMember, 400);
    } else {
      setRecipient(null);
      setSearchResults([]);
    }
    return () => clearTimeout(searchTimeout.current);
  }, [searchQuery]);

  // ── QR API calls ───────────────────────────────────────────────────────────────────────────
  const openQRScanner = async () => {
    if (!cameraPermission?.granted) {
      const result = await requestCameraPermission();
      if (!result.granted) {
        Alert.alert('Permission Required', 'Camera access is needed to scan QR codes.');
        return;
      }
    }
    qrScanLock.current = false;
    setShowQRScanner(true);
  };

  const processMemberQRPayload = async (data, { closeScanner = false } = {}) => {
    if (qrScanLock.current || scanningQR) return;
    qrScanLock.current = true;
    setScanningQR(true);
    try {
      const res = await fundTransferService.scanQRCode(data);
      if (res.success) {
        if (closeScanner) setShowQRScanner(false);
        skipNextSearch.current = true;
        setRecipient(res.member);
        setSearchQuery(res.member.full_name);
        setSearchResults([]);
      } else {
        Alert.alert('Invalid QR', res.error || 'Could not resolve QR code.', [
          { text: 'Try Again', onPress: () => { qrScanLock.current = false; } },
          ...(closeScanner
            ? [{ text: 'Cancel', onPress: () => setShowQRScanner(false) }]
            : [{ text: 'OK', style: 'cancel', onPress: () => { qrScanLock.current = false; } }]),
        ]);
      }
    } catch (e) {
      Alert.alert('Scan Failed', typeof e === 'string' ? e : e.message || 'QR scan failed.', [
        { text: 'Try Again', onPress: () => { qrScanLock.current = false; } },
        ...(closeScanner
          ? [{ text: 'Cancel', onPress: () => setShowQRScanner(false) }]
          : [{ text: 'OK', style: 'cancel', onPress: () => { qrScanLock.current = false; } }]),
      ]);
    } finally {
      setScanningQR(false);
    }
  };

  const handleQRScanned = async ({ data }) => {
    await processMemberQRPayload(data, { closeScanner: true });
  };

  const pickImageAndScanQR = async () => {
    const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!perm.granted) {
      Alert.alert(
        'Permission Required',
        'Photo library access is needed to scan a QR code from an image.',
      );
      return;
    }

    let uri;
    try {
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ImagePicker.MediaTypeOptions.Images,
        allowsEditing: false,
        quality: 1,
      });
      if (result.canceled || !result.assets?.[0]?.uri) return;
      uri = result.assets[0].uri;
    } catch (e) {
      Alert.alert('Error', toErrStr(e) || 'Could not open photo library.');
      return;
    }

    try {
      const barcodes = await Camera.scanFromURLAsync(uri, ['qr']);
      if (!barcodes?.length) {
        Alert.alert(
          'No QR code found',
          'Pick a photo where the QR code is clearly visible.',
        );
        return;
      }
      await processMemberQRPayload(barcodes[0].data, { closeScanner: showQRScanner });
    } catch (e) {
      Alert.alert(
        'Could not read image',
        typeof e === 'string' ? e : e.message || 'QR decoding failed.',
      );
    }
  };

  const openMyQR = async () => {
    setShowMyQR(true);
    if (myQRToken) return;
    setLoadingMyQR(true);
    try {
      const res = await fundTransferService.getMyQRCode();
      if (res.success) setMyQRToken(res.qr_token);
      else Alert.alert('Error', res.error || 'Could not load QR code.');
    } catch (e) {
      Alert.alert('Error', typeof e === 'string' ? e : e.message || 'Failed to load QR code.');
    } finally {
      setLoadingMyQR(false);
    }
  };

  // ── API calls ──────────────────────────────────────────────────────────────────────────────
  const loadCurrentBalance = async () => {
    try {
      const res = await accountService.getAccountInfo();
      if (res.success && res.member) setCurrentBalance(parseFloat(res.member.balance));
    } catch (e) {
      console.error('Failed to load balance:', e);
    }
  };

  const handleSearchMember = async () => {
    const q = searchQuery.trim();
    if (!q || q.length < 2) { setRecipient(null); setSearchResults([]); return; }
    setSearching(true);
    try {
      const res = await fundTransferService.searchMember(q);
      if (res.success) {
        if (res.member) {
          // Exact RFID match — select directly
          setRecipient(res.member);
          setSearchResults([]);
        } else if (res.members && res.members.length > 0) {
          // Name search — show dropdown
          setSearchResults(res.members);
          setRecipient(null);
        }
      } else {
        setRecipient(null);
        setSearchResults([]);
      }
    } catch (e) {
      setRecipient(null);
      setSearchResults([]);
      const msg = typeof e === 'string' ? e : e.message || '';
      if (!msg.includes('not found')) Alert.alert('Error', msg || 'Search failed');
    } finally {
      setSearching(false);
    }
  };

  const handleSelectFromDropdown = (member) => {
    skipNextSearch.current = true;
    setRecipient(member);
    setSearchResults([]);
    setSearchQuery(member.full_name);
  };

  const handleTransfer = () => {
    if (!recipient) { Alert.alert('Error', 'Please select a recipient first'); return; }
    const val = parseFloat(amount);
    if (!amount || isNaN(val) || val <= 0) { Alert.alert('Error', 'Enter a valid amount'); return; }
    if (val > currentBalance) { Alert.alert('Error', 'Insufficient balance'); return; }

    Alert.alert(
      'Confirm Transfer',
      `Transfer ${fmt(val)} to ${recipient.full_name}?`,
      [
        { text: 'Cancel', style: 'cancel' },
        { text: 'Continue', onPress: requestOTP },
      ]
    );
  };

  const requestOTP = async () => {
    setRequestingOTP(true);
    try {
      const res = await fundTransferService.requestTransferOTP(
        recipient.rfid_card_number, parseFloat(amount), notes
      );
      if (res.success) {
        setShowOTPModal(true);
        setOtpCode('');
        startOTPTimer(res.expires_in || 600);
      } else {
        Alert.alert('Error', toErrStr(res.error) || 'Failed to send OTP. Please try again.');
      }
    } catch (e) {
      Alert.alert('Error', toErrStr(e) || 'Failed to send OTP');
    } finally {
      setRequestingOTP(false);
    }
  };

  const startOTPTimer = (seconds) => {
    clearInterval(otpTimer.current);
    const expiryDate = new Date(Date.now() + seconds * 1000);
    setOtpExpiryDate(expiryDate);
    let left = seconds;
    setOtpExpiresIn(left);
    otpTimer.current = setInterval(() => {
      left -= 1;
      setOtpExpiresIn(left);
      if (left <= 0) {
        clearInterval(otpTimer.current);
        setOtpExpiresIn(null);
        Alert.alert('OTP Expired', 'The code has expired. Please request a new one.');
        setShowOTPModal(false);
        setOtpCode('');
      }
    }, 1000);
  };

  const handleVerifyOTP = async () => {
    if (!otpCode || otpCode.length !== 6) {
      Alert.alert('Error', 'Enter a valid 6-digit code');
      return;
    }
    setVerifyingOTP(true);
    try {
      const res = await fundTransferService.verifyTransferOTP(otpCode);
      if (res.success) {
        clearInterval(otpTimer.current);
        setOtpExpiresIn(null);
        setOtpExpiryDate(null);
        setTransactionData(res);
        setShowOTPModal(false);
        setShowSuccess(true);
        setOtpCode('');
        setSearchQuery('');
        setAmount('');
        setNotes('');
        setRecipient(null);
        loadCurrentBalance();
      } else {
        Alert.alert('Verification Failed', toErrStr(res.error) || 'Invalid or expired OTP code. Please try again.');
      }
    } catch (e) {
      Alert.alert('Error', toErrStr(e) || 'Verification failed');
    } finally {
      setVerifyingOTP(false);
    }
  };

  const closeOTPModal = () => {
    clearInterval(otpTimer.current);
    setOtpExpiresIn(null);
    setOtpExpiryDate(null);
    setShowOTPModal(false);
    setOtpCode('');
  };

  // ── Derived state ────────────────────────────────────────────────────────────────────────────
  const parsedAmount    = parseFloat(amount) || 0;
  const isOverBalance   = currentBalance !== null && parsedAmount > currentBalance;
  const canTransfer     = !!recipient && parsedAmount > 0 && !isOverBalance && !requestingOTP;

  // ── Amount input handler ─────────────────────────────────────────────────────────────────────────
  const handleAmountChange = (text) => {
    const cleaned = text.replace(/[^0-9.]/g, '');
    const parts   = cleaned.split('.');
    if (parts.length > 2) return;
    if (parts[1] && parts[1].length > 2) return;
    setAmount(cleaned);
  };

  // ─────────────────────────────────────────────────────────────────────────────
  return (
    <KeyboardAvoidingView
      style={s.root}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
    >
      <ScrollView
        style={s.scroll}
        contentContainerStyle={s.scrollContent}
        keyboardShouldPersistTaps="handled"
        showsVerticalScrollIndicator={false}
      >
        {/* ── Header ── */}
        <View style={s.header}>
          <TouchableOpacity style={s.backBtn} onPress={() => navigation?.goBack()}>
            <Ionicons name="arrow-back" size={20} color={C.white} />
          </TouchableOpacity>
          <View style={s.headerMeta}>
            <Text style={s.headerTitle}>Fund Transfer</Text>
            <Text style={s.headerSub}>Send money to any member</Text>
          </View>
          {/* QR quick-action buttons */}
          <View style={s.headerQRRow}>
            <TouchableOpacity style={s.headerQRBtn} onPress={openQRScanner} activeOpacity={0.8}>
              <Ionicons name="scan-outline" size={18} color={C.white} />
              <Text style={s.headerQRBtnText}>Scan QR</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[s.headerQRBtn, s.headerQRBtnAlt]} onPress={openMyQR} activeOpacity={0.8}>
              <Ionicons name="qr-code-outline" size={18} color={C.green} />
              <Text style={[s.headerQRBtnText, { color: C.green }]}>My QR</Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* ── Balance Hero Card ── */}
        <View style={s.heroWrapper}>
          <View style={s.heroCard}>
            <View style={s.heroCardBody}>
              <View style={s.heroLabelRow}>
                <Ionicons name="wallet-outline" size={15} color={C.ink3} />
                <Text style={s.heroLabel}>Available Balance</Text>
              </View>
              <Text style={s.heroAmount}>
                {currentBalance !== null ? fmt(currentBalance) : '···'}
              </Text>
            </View>
          </View>
        </View>

        {/* ── Send To ── */}
        <View style={s.section}>
          <Text style={s.sectionTitle}>Send To</Text>
          <View style={s.card}>
            <View style={s.searchRow}>
              <View style={s.searchIconWrap}>
                <Ionicons name="person-outline" size={18} color={C.green} />
              </View>
              <TextInput
                style={s.searchInput}
                placeholder="RFID or member name"
                placeholderTextColor={C.ink3}
                value={searchQuery}
                onChangeText={(v) => { setSearchQuery(v); if (recipient) setRecipient(null); }}
                autoCapitalize="words"
                autoCorrect={false}
              />
              {searching
                ? <ActivityIndicator size="small" color={C.greenMid} style={{ marginLeft: 4 }} />
                : searchQuery.length > 0 && (
                  <TouchableOpacity onPress={() => { setSearchQuery(''); setRecipient(null); setSearchResults([]); }}>
                    <Ionicons name="close-circle" size={18} color={C.ink3} />
                  </TouchableOpacity>
                )
              }
            </View>

            {/* QR scan inline shortcut */}
            <TouchableOpacity style={s.qrScanInline} onPress={openQRScanner} activeOpacity={0.8}>
              <Ionicons name="scan-outline" size={16} color={C.green} />
              <Text style={s.qrScanInlineText}>Scan recipient's QR code instead</Text>
              <Ionicons name="chevron-forward" size={14} color={C.green} />
            </TouchableOpacity>
            <TouchableOpacity style={s.qrUploadInline} onPress={pickImageAndScanQR} activeOpacity={0.8}>
              <Ionicons name="images-outline" size={16} color={C.green} />
              <Text style={s.qrUploadInlineText}>Upload QR image from gallery</Text>
              <Ionicons name="chevron-forward" size={14} color={C.green} />
            </TouchableOpacity>

            {recipient && (
              <View style={s.recipientRow}>
                <View style={s.avatar}>
                  <Text style={s.avatarText}>{initials(recipient.full_name)}</Text>
                </View>
                <View style={s.recipientInfo}>
                  <Text style={s.recipientName}>{recipient.full_name}</Text>
                  <Text style={s.recipientSub}>RFID · {recipient.rfid_card_number}</Text>
                  {recipient.member_type_name && (
                    <Text style={s.memberType}>{recipient.member_type_name}</Text>
                  )}
                </View>
                <Ionicons name="checkmark-circle" size={22} color={C.green} />
              </View>
            )}

            {/* ── Name-search dropdown ── */}
            {searchResults.length > 0 && (
              <View style={s.dropdownList}>
                {searchResults.map((m, idx) => (
                  <TouchableOpacity
                    key={m.id}
                    style={[s.dropdownItem, idx < searchResults.length - 1 && s.dropdownItemBorder]}
                    onPress={() => handleSelectFromDropdown(m)}
                    activeOpacity={0.7}
                  >
                    <View style={s.dropdownAvatar}>
                      <Text style={s.avatarText}>{initials(m.full_name)}</Text>
                    </View>
                    <View style={s.dropdownMeta}>
                      <Text style={s.dropdownName}>{m.full_name}</Text>
                      <Text style={s.dropdownSub}>RFID · {m.rfid_card_number}</Text>
                    </View>
                    <Ionicons name="chevron-forward" size={16} color={C.ink3} />
                  </TouchableOpacity>
                ))}
              </View>
            )}

            {searchQuery.trim().length >= 2 && !recipient && !searching && searchResults.length === 0 && (
              <View style={s.noResultRow}>
                <Ionicons name="alert-circle-outline" size={15} color={C.amber} />
                <Text style={s.noResultText}>No member found</Text>
              </View>
            )}
          </View>
        </View>

        {/* ── Amount ── */}
        <View style={s.section}>
          <Text style={s.sectionTitle}>Amount</Text>
          <View style={s.card}>
            <View style={s.amountInputRow}>
              <Text style={s.pesoSign}>₱</Text>
              <TextInput
                style={[s.amountInput, isOverBalance && { color: C.red }]}
                placeholder="0.00"
                placeholderTextColor={C.divider}
                value={amount}
                onChangeText={handleAmountChange}
                keyboardType="decimal-pad"
              />
            </View>
            <View style={s.amountDivider} />

            {parsedAmount > 0 ? (
              isOverBalance ? (
                <View style={s.hintRow}>
                  <Ionicons name="warning-outline" size={14} color={C.red} />
                  <Text style={[s.hintText, { color: C.red }]}>Insufficient balance</Text>
                </View>
              ) : (
                <View style={s.hintRow}>
                  <Ionicons name="checkmark-circle-outline" size={14} color={C.green} />
                  <Text style={[s.hintText, { color: C.green }]}>Sending {fmt(amount)}</Text>
                </View>
              )
            ) : (
              <Text style={s.hintText}>Enter the amount to send</Text>
            )}

            <View style={s.quickRow}>
              {QUICK_AMOUNTS.map((v) => (
                <TouchableOpacity
                  key={v}
                  style={[s.quickChip, amount === String(v) && s.quickChipActive]}
                  onPress={() => setAmount(String(v))}
                >
                  <Text style={[s.quickChipText, amount === String(v) && s.quickChipTextActive]}>
                    ₱{v.toLocaleString()}
                  </Text>
                </TouchableOpacity>
              ))}
            </View>
          </View>
        </View>

        {/* ── Note ── */}
        <View style={s.section}>
          <Text style={s.sectionTitle}>
            Note <Text style={s.optional}>(optional)</Text>
          </Text>
          <View style={s.card}>
            <TextInput
              style={s.notesInput}
              placeholder="e.g. Monthly share, payment for goods…"
              placeholderTextColor={C.ink3}
              value={notes}
              onChangeText={setNotes}
              multiline
              numberOfLines={3}
              maxLength={200}
              textAlignVertical="top"
            />
          </View>
        </View>

        {/* ── Live Transfer Summary ── */}
        {recipient && parsedAmount > 0 && !isOverBalance && (
          <View style={s.summaryBox}>
            <View style={s.summaryRow}>
              <Text style={s.summaryKey}>Sending to</Text>
              <Text style={s.summaryVal}>{recipient.full_name}</Text>
            </View>
            <View style={s.summaryDivider} />
            <View style={s.summaryRow}>
              <Text style={s.summaryKey}>Amount</Text>
              <Text style={[s.summaryVal, s.summaryAmt]}>{fmt(amount)}</Text>
            </View>
            <View style={s.summaryDivider} />
            <View style={s.summaryRow}>
              <Text style={s.summaryKey}>Balance after</Text>
              <Text style={s.summaryVal}>{fmt(currentBalance - parsedAmount)}</Text>
            </View>
          </View>
        )}

        {/* ── CTA ── */}
        <TouchableOpacity
          style={[s.ctaBtn, !canTransfer && s.ctaBtnDisabled]}
          onPress={handleTransfer}
          disabled={!canTransfer}
          activeOpacity={0.85}
        >
          {requestingOTP ? (
            <ActivityIndicator size="small" color={C.white} />
          ) : (
            <>
              <Ionicons name="send" size={18} color={C.white} />
              <Text style={s.ctaBtnText}>Send Money</Text>
            </>
          )}
        </TouchableOpacity>

      </ScrollView>

      {/* ══ OTP Modal ════════════════════════════════════════════════════════════ */}
      <Modal
        visible={showOTPModal}
        transparent
        animationType="slide"
        onRequestClose={closeOTPModal}
        onShow={() => setTimeout(() => otpInputRef.current?.focus(), 150)}
      >
        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
          style={s.overlay}
        >
          <View style={s.sheet}>
            <View style={s.sheetHandle} />
            <View style={s.sheetHeader}>
              <Text style={s.sheetTitle}>Verify Transfer</Text>
              <TouchableOpacity style={s.sheetClose} onPress={closeOTPModal}>
                <Ionicons name="close" size={18} color={C.ink2} />
              </TouchableOpacity>
            </View>

            <ScrollView contentContainerStyle={s.sheetBody} keyboardShouldPersistTaps="handled">
              <View style={s.otpIconBg}>
                <Ionicons name="mail-outline" size={28} color={C.green} />
              </View>
              <Text style={s.otpTitle}>Enter verification code</Text>
              <Text style={s.otpDesc}>
                A 6-digit code was sent to your registered email address.
              </Text>

              {/* ── Request Expiry Sign ── */}
              {otpExpiryDate !== null && (
                <View style={s.expirySignCard}>
                  <View style={s.expirySignHeader}>
                    <Ionicons
                      name={otpExpiresIn !== null && otpExpiresIn <= 60 ? 'warning' : 'calendar-outline'}
                      size={15}
                      color={otpExpiresIn !== null && otpExpiresIn <= 60 ? C.red : C.amber}
                    />
                    <Text style={[
                      s.expirySignLabel,
                      otpExpiresIn !== null && otpExpiresIn <= 60 && { color: C.red },
                    ]}>
                      REQUEST EXPIRES
                    </Text>
                  </View>
                  <Text style={[
                    s.expirySignDate,
                    otpExpiresIn !== null && otpExpiresIn <= 60 && { color: C.red },
                  ]}>
                    {fmtExpiry(otpExpiryDate)}
                  </Text>
                  {otpExpiresIn !== null && (
                    <View style={[s.timerBadge, otpExpiresIn <= 60 && s.timerBadgeUrgent, { marginTop: 8, marginBottom: 0 }]}>
                      <Ionicons
                        name="time-outline"
                        size={13}
                        color={otpExpiresIn <= 60 ? C.red : C.amber}
                      />
                      <Text style={[s.timerText, otpExpiresIn <= 60 && { color: C.red }]}>
                        {' '}Time remaining: {fmtTimer(otpExpiresIn)}
                      </Text>
                    </View>
                  )}
                </View>
              )}

              <OTPBoxInput ref={otpInputRef} value={otpCode} onChange={setOtpCode} autoFocus />

              <TouchableOpacity
                style={[s.verifyBtn, (otpCode.length !== 6 || verifyingOTP) && s.verifyBtnOff]}
                onPress={handleVerifyOTP}
                disabled={otpCode.length !== 6 || verifyingOTP}
              >
                {verifyingOTP
                  ? <ActivityIndicator size="small" color={C.white} />
                  : <Text style={s.verifyBtnText}>Verify & Transfer</Text>
                }
              </TouchableOpacity>

              <TouchableOpacity style={s.resendLink} onPress={requestOTP} disabled={requestingOTP}>
                <Text style={s.resendText}>
                  {requestingOTP ? 'Sending…' : "Didn't receive a code? Resend"}
                </Text>
              </TouchableOpacity>
            </ScrollView>
          </View>
        </KeyboardAvoidingView>
      </Modal>

      {/* ══ Success Modal ════════════════════════════════════════════════════════ */}
      <Modal
        visible={showSuccess}
        transparent
        animationType="slide"
        onRequestClose={() => setShowSuccess(false)}
      >
        <View style={s.overlay}>
          <View style={[s.sheet, { maxHeight: '92%' }]}>
            <View style={s.sheetHandle} />

            {transactionData && (
              <ScrollView
                contentContainerStyle={s.sheetBody}
                showsVerticalScrollIndicator={false}
              >
                {/* Success icon */}
                <View style={s.successRing}>
                  <View style={s.successCircle}>
                    <Ionicons name="checkmark" size={32} color={C.white} />
                  </View>
                </View>
                <Text style={s.successTitle}>Transfer Successful</Text>
                <Text style={s.successSub}>
                  {transactionData.message || 'Funds have been sent successfully.'}
                </Text>

                {/* Receipt */}
                <View style={s.receipt}>
                  <View style={s.receiptHeader}>
                    <Text style={s.receiptHeaderText}>Transfer Details</Text>
                  </View>
                  {[
                    ['Recipient', transactionData.transfer?.recipient?.full_name],
                    ['RFID',      transactionData.transfer?.recipient?.rfid_card_number],
                    ['Amount',    fmt(transactionData.transfer?.amount)],
                    ['Note',      transactionData.transfer?.notes || '—'],
                  ].map(([k, v], idx, arr) => (
                    <View
                      key={k}
                      style={[s.receiptRow, idx < arr.length - 1 && s.receiptRowBorder]}
                    >
                      <Text style={s.receiptKey}>{k}</Text>
                      <Text style={[s.receiptVal, k === 'Amount' && s.receiptValAmt]}>{v}</Text>
                    </View>
                  ))}
                </View>

                {/* Balance change cards */}
                <View style={s.balChangeRow}>
                  {transactionData.sender_transaction && (
                    <View style={[s.balChangeCard, s.balChangeCardDebit]}>
                      <Text style={s.balChangeBadge}>YOUR BALANCE</Text>
                      <Text style={[s.balChangeAmt, { color: C.red }]}>
                        -{fmt(transactionData.sender_transaction.amount)}
                      </Text>
                      <Text style={s.balChangeNew}>
                        New: {fmt(transactionData.sender_transaction.balance_after)}
                      </Text>
                    </View>
                  )}
                  {transactionData.recipient_transaction && (
                    <View style={[s.balChangeCard, s.balChangeCardCredit]}>
                      <Text style={s.balChangeBadge}>RECIPIENT</Text>
                      <Text style={[s.balChangeAmt, { color: C.green }]}>
                        +{fmt(transactionData.recipient_transaction.amount)}
                      </Text>
                      <Text style={s.balChangeNew}>
                        New: {fmt(transactionData.recipient_transaction.balance_after)}
                      </Text>
                    </View>
                  )}
                </View>

                {transactionData.sender_transaction?.created_at && (
                  <Text style={s.receiptDate}>
                    {fmtDate(transactionData.sender_transaction.created_at)}
                  </Text>
                )}

                <TouchableOpacity style={s.doneBtn} onPress={() => setShowSuccess(false)}>
                  <Text style={s.doneBtnText}>Done</Text>
                </TouchableOpacity>
              </ScrollView>
            )}
          </View>
        </View>
      </Modal>

      {/* ══ QR Scanner Modal ═════════════════════════════════════════════════════ */}
      <Modal
        visible={showQRScanner}
        transparent={false}
        animationType="slide"
        onRequestClose={() => setShowQRScanner(false)}
      >
        <View style={s.scanRoot}>
          {/* Header */}
          <View style={s.scanHeader}>
            <TouchableOpacity style={s.scanClose} onPress={() => setShowQRScanner(false)}>
              <Ionicons name="close" size={22} color={C.white} />
            </TouchableOpacity>
            <Text style={s.scanTitle}>Scan Member QR Code</Text>
            <View style={{ width: 40 }} />
          </View>

          {/* Camera */}
          {cameraPermission?.granted ? (
            <CameraView
              style={s.scanCamera}
              facing="back"
              barcodeScannerSettings={{ barcodeTypes: ['qr'] }}
              onBarcodeScanned={handleQRScanned}
            >
              {/* Viewfinder overlay */}
              <View style={s.scanOverlay}>
                <View style={s.scanCornerTL} />
                <View style={s.scanCornerTR} />
                <View style={s.scanCornerBL} />
                <View style={s.scanCornerBR} />
              </View>
              {scanningQR && (
                <View style={s.scanSpinner}>
                  <ActivityIndicator size="large" color={C.white} />
                </View>
              )}
            </CameraView>
          ) : (
            <View style={s.scanNoPerm}>
              <Ionicons name="camera-off-outline" size={48} color={C.ink3} />
              <Text style={s.scanNoPermText}>Camera permission is required.</Text>
              <TouchableOpacity style={s.verifyBtn} onPress={requestCameraPermission}>
                <Text style={s.verifyBtnText}>Grant Permission</Text>
              </TouchableOpacity>
            </View>
          )}

          <View style={s.scanFooter}>
            <Text style={s.scanHint}>Point the camera at the recipient's QR code</Text>
            <TouchableOpacity style={s.scanGalleryBtn} onPress={pickImageAndScanQR} activeOpacity={0.85}>
              <Ionicons name="images-outline" size={20} color="#fff" />
              <Text style={s.scanGalleryBtnText}>Choose QR image</Text>
            </TouchableOpacity>
          </View>
        </View>
      </Modal>

      {/* ══ My QR Code Modal ════════════════════════════════════════════════════ */}
      <Modal
        visible={showMyQR}
        transparent
        animationType="slide"
        onRequestClose={() => setShowMyQR(false)}
      >
        <View style={s.overlay}>
          <View style={[s.sheet, { maxHeight: '70%' }]}>
            <View style={s.sheetHandle} />
            <View style={s.sheetHeader}>
              <Text style={s.sheetTitle}>My QR Code</Text>
              <TouchableOpacity style={s.sheetClose} onPress={() => setShowMyQR(false)}>
                <Ionicons name="close" size={18} color={C.ink2} />
              </TouchableOpacity>
            </View>
            <ScrollView contentContainerStyle={s.sheetBody} showsVerticalScrollIndicator={false}>
              <Text style={s.myQRDesc}>
                Let another member scan this to send you money instantly.
              </Text>
              {loadingMyQR ? (
                <ActivityIndicator size="large" color={C.green} style={{ marginVertical: 40 }} />
              ) : myQRToken ? (
                <>
                  <View style={s.myQRBox}>
                    <QRCode
                      value={myQRToken}
                      size={200}
                      color={C.ink}
                      backgroundColor={C.white}
                      logo={undefined}
                    />
                  </View>
                  <Text style={s.myQRTokenText}>{myQRToken.slice(0, 8).toUpperCase()}…</Text>
                </>
              ) : (
                <View style={s.scanNoPerm}>
                  <Ionicons name="qr-code-outline" size={40} color={C.ink3} />
                  <Text style={s.scanNoPermText}>Could not load QR code.</Text>
                </View>
              )}
            </ScrollView>
          </View>
        </View>
      </Modal>
    </KeyboardAvoidingView>
  );
}

// ─── Styles ──────────────────────────────────────────────────────────────────
const s = StyleSheet.create({
  root:          { flex: 1, backgroundColor: C.bg },
  scroll:        { flex: 1 },
  scrollContent: { paddingBottom: 40 },

  // ── Header
  header: {
    backgroundColor: C.green,
    paddingTop: 56,
    paddingHorizontal: 20,
    paddingBottom: 56,
  },
  backBtn: {
    width: 38, height: 38, borderRadius: 19,
    backgroundColor: 'rgba(255,255,255,0.15)',
    alignItems: 'center', justifyContent: 'center',
    marginBottom: 18,
  },
  headerMeta:     { marginBottom: 0 },
  headerTitle:    { fontSize: 24, fontWeight: '700', color: C.white, letterSpacing: -0.3 },
  headerSub:      { fontSize: 13, color: 'rgba(255,255,255,0.65)', marginTop: 3 },

  // ── Balance Hero Card
  heroWrapper: {
    marginHorizontal: 16,
    marginTop: -36,
    marginBottom: 4,
  },
  heroCard: {
    backgroundColor: C.surface,
    borderRadius: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.12,
    shadowRadius: 12,
    elevation: 6,
    overflow: 'hidden',
  },
  heroCardBody: {
    padding: 20,
  },
  heroLabelRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: 8,
  },
  heroLabel: {
    fontSize: 13,
    color: C.ink3,
    fontWeight: '500',
  },
  heroAmount: {
    fontSize: 36,
    fontWeight: '800',
    color: C.green,
    letterSpacing: -0.5,
  },

  // ── Sections
  section:       { marginTop: 20, paddingHorizontal: 16 },
  sectionTitle:  { fontSize: 13, fontWeight: '600', color: C.ink2, marginBottom: 8, marginLeft: 2 },
  optional:      { fontWeight: '400', color: C.ink3 },

  // ── Card
  card: {
    backgroundColor: C.surface,
    borderRadius: 16,
    padding: 16,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.07,
    shadowRadius: 6,
    elevation: 2,
  },

  // ── Search
  searchRow:     { flexDirection: 'row', alignItems: 'center', gap: 10 },
  searchIconWrap: {
    width: 36, height: 36, borderRadius: 10,
    backgroundColor: C.greenPale, alignItems: 'center', justifyContent: 'center',
  },
  searchInput:   { flex: 1, fontSize: 15, color: C.ink, height: 44 },

  // ── Recipient
  recipientRow: {
    marginTop: 14, flexDirection: 'row', alignItems: 'center',
    backgroundColor: C.greenLight, borderRadius: 12, padding: 12, gap: 12,
  },
  avatar:        { width: 46, height: 46, borderRadius: 23, backgroundColor: C.green, alignItems: 'center', justifyContent: 'center' },
  avatarText:    { fontSize: 15, fontWeight: '700', color: C.white },
  recipientInfo: { flex: 1 },
  recipientName: { fontSize: 15, fontWeight: '600', color: C.ink },
  recipientSub:  { fontSize: 12, color: C.greenMid, marginTop: 2 },
  memberType:    { fontSize: 11, color: C.ink3, marginTop: 3 },

  noResultRow: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    marginTop: 12, padding: 10,
    backgroundColor: C.amberLight, borderRadius: 10,
  },
  noResultText:  { fontSize: 13, color: C.amber },

  // ── Dropdown search results
  dropdownList: {
    marginTop: 10,
    borderRadius: 12,
    borderWidth: 1,
    borderColor: C.divider,
    overflow: 'hidden',
  },
  dropdownItem: {
    flexDirection: 'row', alignItems: 'center', gap: 12,
    paddingHorizontal: 12, paddingVertical: 11,
    backgroundColor: C.surface,
  },
  dropdownItemBorder: { borderBottomWidth: 1, borderBottomColor: C.divider },
  dropdownAvatar: {
    width: 38, height: 38, borderRadius: 19,
    backgroundColor: C.greenMid, alignItems: 'center', justifyContent: 'center',
  },
  dropdownMeta:  { flex: 1 },
  dropdownName:  { fontSize: 14, fontWeight: '600', color: C.ink },
  dropdownSub:   { fontSize: 12, color: C.ink3, marginTop: 2 },

  // ── Amount
  amountInputRow:{ flexDirection: 'row', alignItems: 'center' },
  pesoSign:      { fontSize: 32, fontWeight: '700', color: C.ink3, marginRight: 4 },
  amountInput:   { flex: 1, fontSize: 38, fontWeight: '700', color: C.ink, paddingVertical: 4 },
  amountDivider: { height: 1, backgroundColor: C.divider, marginVertical: 12 },
  hintRow:       { flexDirection: 'row', alignItems: 'center', gap: 5, marginBottom: 2 },
  hintText:      { fontSize: 13, color: C.ink3 },
  quickRow:      { flexDirection: 'row', gap: 8, marginTop: 14, flexWrap: 'wrap' },
  quickChip:     { borderWidth: 1.5, borderColor: C.divider, borderRadius: 100, paddingHorizontal: 14, paddingVertical: 7 },
  quickChipActive:     { borderColor: C.green, backgroundColor: C.greenLight },
  quickChipText:       { fontSize: 13, fontWeight: '500', color: C.ink2 },
  quickChipTextActive: { color: C.green, fontWeight: '600' },

  // ── Notes
  notesInput:    { fontSize: 14, color: C.ink, minHeight: 68, paddingTop: 2 },

  // ── Summary preview
  summaryBox: {
    marginHorizontal: 16,
    marginTop: 16,
    backgroundColor: C.greenPale,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: C.greenBorder,
    padding: 16,
  },
  summaryRow:    { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingVertical: 6 },
  summaryDivider:{ height: 1, backgroundColor: C.greenBorder, opacity: 0.4 },
  summaryKey:    { fontSize: 13, color: C.ink3 },
  summaryVal:    { fontSize: 14, fontWeight: '500', color: C.ink },
  summaryAmt:    { fontSize: 15, fontWeight: '700', color: C.green },

  // ── CTA button
  ctaBtn: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10,
    backgroundColor: C.green,
    marginHorizontal: 16,
    marginTop: 20,
    borderRadius: 16,
    height: 56,
    shadowColor: C.green,
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.35,
    shadowRadius: 10,
    elevation: 5,
  },
  ctaBtnDisabled:{ backgroundColor: '#B0BEC5', shadowOpacity: 0, elevation: 0 },
  ctaBtnText:    { fontSize: 16, fontWeight: '700', color: C.white, letterSpacing: 0.2 },

  // ── Modal shared
  overlay: {
    flex: 1, backgroundColor: 'rgba(0,0,0,0.4)', justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: C.surface,
    borderTopLeftRadius: 28, borderTopRightRadius: 28,
    paddingBottom: Platform.OS === 'ios' ? 36 : 24,
    maxHeight: '82%',
  },
  sheetHandle: {
    width: 36, height: 4, backgroundColor: C.divider, borderRadius: 2,
    alignSelf: 'center', marginTop: 12, marginBottom: 4,
  },
  sheetHeader: {
    flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center',
    paddingHorizontal: 24, paddingVertical: 16,
    borderBottomWidth: 1, borderBottomColor: C.divider,
  },
  sheetTitle:  { fontSize: 18, fontWeight: '700', color: C.ink },
  sheetClose:  { width: 30, height: 30, borderRadius: 15, backgroundColor: '#F2F2F7', alignItems: 'center', justifyContent: 'center' },
  sheetBody:   { paddingHorizontal: 24, paddingTop: 28, paddingBottom: 40, alignItems: 'center' },

  // ── OTP modal
  otpIconBg:   { width: 68, height: 68, borderRadius: 22, backgroundColor: C.greenLight, alignItems: 'center', justifyContent: 'center', marginBottom: 18 },
  otpTitle:    { fontSize: 17, fontWeight: '700', color: C.ink, textAlign: 'center', marginBottom: 8 },
  otpDesc:     { fontSize: 14, color: C.ink3, textAlign: 'center', lineHeight: 21, marginBottom: 20 },
  timerBadge:  { flexDirection: 'row', alignItems: 'center', backgroundColor: C.amberLight, borderRadius: 100, paddingHorizontal: 14, paddingVertical: 7, marginBottom: 24 },
  timerBadgeUrgent: { backgroundColor: C.redLight },
  timerText:   { fontSize: 13, fontWeight: '500', color: C.amber },

  // ── Request Expiry Sign
  expirySignCard: {
    width: '100%',
    backgroundColor: C.amberLight,
    borderRadius: 14,
    borderWidth: 1.5,
    borderColor: '#FFE0B2',
    padding: 14,
    alignItems: 'center',
    marginBottom: 24,
  },
  expirySignHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    marginBottom: 6,
  },
  expirySignLabel: {
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 1.2,
    color: C.amber,
    textTransform: 'uppercase',
  },
  expirySignDate: {
    fontSize: 17,
    fontWeight: '700',
    color: C.amber,
    letterSpacing: 0.2,
  },

  // 6-box OTP
  otpWrapper:  { flexDirection: 'row', gap: 10, marginBottom: 24, alignSelf: 'stretch', justifyContent: 'center' },
  otpBox: {
    width: 44, height: 54, borderRadius: 12,
    borderWidth: 1.5, borderColor: C.divider,
    backgroundColor: '#F8F9FA',
    alignItems: 'center', justifyContent: 'center',
  },
  otpBoxActive: { borderColor: C.green, backgroundColor: C.greenPale },
  otpBoxFilled: { borderColor: C.green, backgroundColor: C.white },
  otpBoxText:   { fontSize: 22, fontWeight: '700', color: C.ink },
  otpHidden:    { position: 'absolute', left: 0, top: 0, right: 0, bottom: 0, opacity: 0, color: 'transparent' },

  verifyBtn:   { width: '100%', height: 52, backgroundColor: C.green, borderRadius: 14, alignItems: 'center', justifyContent: 'center', marginBottom: 12 },
  verifyBtnOff:{ backgroundColor: '#B0BEC5' },
  verifyBtnText:{ color: C.white, fontSize: 16, fontWeight: '700' },
  resendLink:  { paddingVertical: 10 },
  resendText:  { color: C.greenMid, fontSize: 14, fontWeight: '500' },

  // ── Success modal
  successRing:   { width: 90, height: 90, borderRadius: 45, backgroundColor: C.greenLight, alignItems: 'center', justifyContent: 'center', marginBottom: 16 },
  successCircle: { width: 64, height: 64, borderRadius: 32, backgroundColor: C.green, alignItems: 'center', justifyContent: 'center' },
  successTitle:  { fontSize: 20, fontWeight: '700', color: C.ink, textAlign: 'center', marginBottom: 6 },
  successSub:    { fontSize: 14, color: C.ink3, textAlign: 'center', marginBottom: 24 },

  // Receipt
  receipt: {
    width: '100%', borderRadius: 16, borderWidth: 1,
    borderColor: C.divider, overflow: 'hidden', marginBottom: 16,
  },
  receiptHeader:    { backgroundColor: C.greenPale, paddingVertical: 10, paddingHorizontal: 16 },
  receiptHeaderText:{ fontSize: 11, fontWeight: '600', color: C.green, textTransform: 'uppercase', letterSpacing: 0.8 },
  receiptRow:       { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 12 },
  receiptRowBorder: { borderBottomWidth: 1, borderBottomColor: C.divider },
  receiptKey:       { fontSize: 13, color: C.ink3 },
  receiptVal:       { fontSize: 14, fontWeight: '500', color: C.ink, maxWidth: '60%', textAlign: 'right' },
  receiptValAmt:    { fontSize: 16, fontWeight: '700', color: C.ink },

  // Balance change
  balChangeRow:       { flexDirection: 'row', gap: 10, width: '100%', marginBottom: 16 },
  balChangeCard:      { flex: 1, borderRadius: 12, padding: 14 },
  balChangeCardDebit: { backgroundColor: C.redLight },
  balChangeCardCredit:{ backgroundColor: C.greenLight },
  balChangeBadge:     { fontSize: 9, fontWeight: '700', letterSpacing: 0.8, color: C.ink3, marginBottom: 6 },
  balChangeAmt:       { fontSize: 17, fontWeight: '700', marginBottom: 2 },
  balChangeNew:       { fontSize: 11, color: C.ink3 },

  receiptDate: { fontSize: 12, color: C.ink3, marginBottom: 20 },
  doneBtn:     { width: '100%', height: 52, backgroundColor: C.green, borderRadius: 14, alignItems: 'center', justifyContent: 'center' },
  doneBtnText: { color: C.white, fontSize: 16, fontWeight: '700' },

  // ── Header QR buttons
  headerQRRow: {
    flexDirection: 'row', gap: 10, marginTop: 16,
  },
  headerQRBtn: {
    flexDirection: 'row', alignItems: 'center', gap: 6,
    backgroundColor: 'rgba(255,255,255,0.15)',
    borderRadius: 22, paddingHorizontal: 14, paddingVertical: 8,
  },
  headerQRBtnAlt: {
    backgroundColor: C.white,
  },
  headerQRBtnText: {
    fontSize: 13, fontWeight: '600', color: C.white,
  },

  // ── QR scan inline shortcut
  qrScanInline: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    marginTop: 12, paddingTop: 12,
    borderTopWidth: 1, borderTopColor: C.divider,
  },
  qrScanInlineText: {
    flex: 1, fontSize: 13, color: C.green, fontWeight: '500',
  },
  qrUploadInline: {
    flexDirection: 'row', alignItems: 'center', gap: 8,
    marginTop: 8, paddingVertical: 4,
  },
  qrUploadInlineText: {
    flex: 1, fontSize: 13, color: C.green, fontWeight: '500',
  },

  // ── QR Scanner full-screen modal
  scanRoot:   { flex: 1, backgroundColor: '#000' },
  scanHeader: {
    flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between',
    paddingTop: Platform.OS === 'ios' ? 56 : 40,
    paddingHorizontal: 20, paddingBottom: 16,
    backgroundColor: 'rgba(0,0,0,0.6)',
  },
  scanClose:  {
    width: 40, height: 40, borderRadius: 20,
    backgroundColor: 'rgba(255,255,255,0.15)',
    alignItems: 'center', justifyContent: 'center',
  },
  scanTitle:  { fontSize: 17, fontWeight: '700', color: '#fff' },
  scanCamera: { flex: 1 },
  scanOverlay: {
    position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
    alignItems: 'center', justifyContent: 'center',
  },
  // Corner brackets for viewfinder
  scanCornerTL: {
    position: 'absolute',
    top: '28%', left: '20%',
    width: 32, height: 32,
    borderTopWidth: 3, borderLeftWidth: 3,
    borderColor: C.white, borderRadius: 4,
  },
  scanCornerTR: {
    position: 'absolute',
    top: '28%', right: '20%',
    width: 32, height: 32,
    borderTopWidth: 3, borderRightWidth: 3,
    borderColor: C.white, borderRadius: 4,
  },
  scanCornerBL: {
    position: 'absolute',
    bottom: '28%', left: '20%',
    width: 32, height: 32,
    borderBottomWidth: 3, borderLeftWidth: 3,
    borderColor: C.white, borderRadius: 4,
  },
  scanCornerBR: {
    position: 'absolute',
    bottom: '28%', right: '20%',
    width: 32, height: 32,
    borderBottomWidth: 3, borderRightWidth: 3,
    borderColor: C.white, borderRadius: 4,
  },
  scanSpinner: {
    position: 'absolute', alignSelf: 'center',
    backgroundColor: 'rgba(0,0,0,0.55)',
    borderRadius: 12, padding: 16,
  },
  scanFooter: {
    paddingVertical: 22,
    paddingHorizontal: 20,
    alignItems: 'center',
    gap: 14,
    backgroundColor: 'rgba(0,0,0,0.6)',
  },
  scanHint:   { fontSize: 14, color: 'rgba(255,255,255,0.75)', textAlign: 'center' },
  scanGalleryBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 10,
    backgroundColor: 'rgba(255,255,255,0.14)',
    paddingHorizontal: 22,
    paddingVertical: 12,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: 'rgba(255,255,255,0.28)',
  },
  scanGalleryBtnText: {
    fontSize: 15,
    fontWeight: '600',
    color: '#fff',
  },
  scanNoPerm: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 16, padding: 32 },
  scanNoPermText: { fontSize: 15, color: C.ink3, textAlign: 'center' },

  // ── My QR modal
  myQRDesc: { fontSize: 14, color: C.ink3, textAlign: 'center', marginBottom: 24, lineHeight: 21 },
  myQRBox: {
    padding: 20, backgroundColor: C.white,
    borderRadius: 20, marginBottom: 14,
    shadowColor: '#000', shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1, shadowRadius: 8, elevation: 3,
  },
  myQRTokenText: {
    fontSize: 12, color: C.ink3, fontFamily: Platform.OS === 'ios' ? 'Courier' : 'monospace',
    marginBottom: 16,
  },
});

