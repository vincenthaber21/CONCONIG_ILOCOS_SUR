import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  RefreshControl,
  ActivityIndicator,
  Alert,
  Modal,
  FlatList,
  StatusBar,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { accountService, authService } from '../services/api';
import { colors } from '../constants/colors';
import { useAutoRefresh } from '../hooks/useAutoRefresh';

export default function HomeScreen({ navigation }) {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);
  const [selectedYear, setSelectedYear] = useState(new Date().getFullYear());
  const [selectedMonth, setSelectedMonth] = useState(new Date().getMonth() + 1);
  const [showMonthPicker, setShowMonthPicker] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  // Stable ref for current year/month so the polling callback stays stable
  const selectedYearRef = useRef(selectedYear);
  const selectedMonthRef = useRef(selectedMonth);
  useEffect(() => { selectedYearRef.current = selectedYear; }, [selectedYear]);
  useEffect(() => { selectedMonthRef.current = selectedMonth; }, [selectedMonth]);

  useEffect(() => {
    loadAccountSummary(selectedYear, selectedMonth);
  }, [selectedYear, selectedMonth]);

  // Auto-refresh every 30 seconds while the screen is visible
  const autoRefreshCallback = useCallback(() => {
    loadAccountSummary(selectedYearRef.current, selectedMonthRef.current);
  }, []);
  useAutoRefresh(autoRefreshCallback, 30000);

  const loadAccountSummary = async (year, month) => {
    try {
      setError(null);
      const response = await accountService.getAccountSummary(year, month);
      if (response.success) {
        setSummary(response.summary);
        // Update selected month/year from response if provided
        if (response.summary.selected_year) {
          setSelectedYear(response.summary.selected_year);
        }
        if (response.summary.selected_month) {
          setSelectedMonth(response.summary.selected_month);
        }
      } else {
        setError(response.error || 'Failed to load account data.');
      }
    } catch (err) {
      // Check if it's an authentication error
      const errorMessage = typeof err === 'string' ? err : err.message || '';
      if (errorMessage.includes('Authentication') || errorMessage.includes('401') || errorMessage.includes('Unauthorized')) {
        // Session expired, logout and redirect to login
        await authService.logout();
        navigation.replace('Login');
      } else {
        setError(errorMessage || 'Could not connect to the server.');
      }
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const handleRefresh = () => {
    setRefreshing(true);
    loadAccountSummary(selectedYear, selectedMonth);
  };

  const getMonthName = (month) => {
    const months = [
      'January', 'February', 'March', 'April', 'May', 'June',
      'July', 'August', 'September', 'October', 'November', 'December'
    ];
    return months[month - 1] || months[0];
  };

  const handleMonthSelect = (year, month) => {
    setSelectedYear(year);
    setSelectedMonth(month);
    setShowMonthPicker(false);
    setLoading(true);
    loadAccountSummary(year, month);
  };

  const generateMonthOptions = () => {
    const options = [];
    const currentDate = new Date();
    const currentYear = currentDate.getFullYear();
    const currentMonth = currentDate.getMonth() + 1;
    
    // Generate options for last 12 months
    for (let i = 0; i < 12; i++) {
      let year = currentYear;
      let month = currentMonth - i;
      
      if (month <= 0) {
        month += 12;
        year -= 1;
      }
      
      options.push({ year, month, label: `${getMonthName(month)} ${year}` });
    }
    
    return options;
  };

  const handleLogout = async () => {
    setShowSettings(false);
    Alert.alert(
      'Logout',
      'Are you sure you want to logout?',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Logout',
          style: 'destructive',
          onPress: async () => {
            await authService.logout();
            navigation.replace('Login');
          },
        },
      ]
    );
  };

  const formatCurrency = (amount) => {
    const num = parseFloat(amount || 0);
    return `₱${num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  };

  const getGreeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 18) return 'Good afternoon';
    return 'Good evening';
  };

  if (loading) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color={colors.brand} />
        <Text style={styles.loadingText}>Loading your account...</Text>
      </View>
    );
  }

  if (!summary) {
    return (
      <View style={styles.centered}>
        <Ionicons name="cloud-offline-outline" size={56} color={colors.muted} />
        <Text style={styles.emptyText}>
          {error || 'No data available'}
        </Text>
        <TouchableOpacity
          style={styles.retryButton}
          onPress={() => {
            setLoading(true);
            setError(null);
            loadAccountSummary(selectedYear, selectedMonth);
          }}
          activeOpacity={0.7}
        >
          <Ionicons name="refresh-outline" size={18} color="#fff" style={{ marginRight: 6 }} />
          <Text style={styles.retryButtonText}>Try Again</Text>
        </TouchableOpacity>
      </View>
    );
  }

  const { member, recent_transactions, total_spent_this_month } = summary;
  const isCurrentMonth =
    selectedYear === new Date().getFullYear() && selectedMonth === new Date().getMonth() + 1;

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.scrollContent}
      refreshControl={
        <RefreshControl refreshing={refreshing} onRefresh={handleRefresh} tintColor={colors.brand} />
      }
      showsVerticalScrollIndicator={false}
    >
      <StatusBar barStyle="light-content" backgroundColor={colors.brand} />

      {/* ── Header ── */}
      <View style={styles.header}>
        <View style={styles.headerLeft}>
          <Text style={styles.greeting}>{getGreeting()}</Text>
          <Text style={styles.name} numberOfLines={1}>{member.full_name}</Text>
        </View>
        <TouchableOpacity onPress={() => setShowSettings(true)} style={styles.avatarButton}>
          <View style={styles.avatarCircle}>
            <Text style={styles.avatarInitial}>
              {member.full_name ? member.full_name.charAt(0).toUpperCase() : '?'}
            </Text>
          </View>
        </TouchableOpacity>
      </View>

      {/* ── Balance Hero Card ── */}
      <View style={styles.heroWrapper}>
        <View style={styles.heroCard}>
          <View style={styles.heroCardBody}>
            <View style={styles.heroLabelRow}>
              <Ionicons name="wallet-outline" size={15} color={colors.textSecondary} />
              <Text style={styles.heroLabel}>Account Balance</Text>
            </View>
            <Text style={styles.heroAmount}>{formatCurrency(member.balance)}</Text>
          </View>
          <View style={styles.heroDivider} />
          <TouchableOpacity
            style={styles.heroAction}
            onPress={() => navigation.navigate('Transactions')}
            activeOpacity={0.7}
          >
            <Ionicons name="receipt-outline" size={17} color={colors.brand} />
            <Text style={styles.heroActionText}>View All Transactions</Text>
            <Ionicons name="chevron-forward" size={16} color={colors.brand} />
          </TouchableOpacity>
        </View>
      </View>

      {/* ── Monthly Summary ── */}
      <View style={styles.card}>
        <View style={styles.cardHeader}>
          <Text style={styles.cardTitle}>Monthly Spending</Text>
          <TouchableOpacity
            onPress={() => setShowMonthPicker(true)}
            style={styles.monthChip}
            activeOpacity={0.7}
          >
            <Ionicons name="calendar-outline" size={13} color={colors.brand} />
            <Text style={styles.monthChipText}>
              {isCurrentMonth
                ? 'This Month'
                : `${getMonthName(selectedMonth).slice(0, 3)} ${selectedYear}`}
            </Text>
            <Ionicons name="chevron-down" size={13} color={colors.brand} />
          </TouchableOpacity>
        </View>

        <View style={styles.spendRow}>
          <View style={styles.spendIconWrap}>
            <Ionicons name="trending-down-outline" size={22} color={colors.brand} />
          </View>
          <View>
            <Text style={styles.spendLabel}>Total Spent</Text>
            <Text style={styles.spendAmount}>{formatCurrency(total_spent_this_month)}</Text>
          </View>
        </View>
      </View>

      {/* ── Recent Transactions ── */}
      {recent_transactions && recent_transactions.length > 0 ? (
        <View style={styles.card}>
          <View style={styles.cardHeader}>
            <Text style={styles.cardTitle}>Recent Transactions</Text>
            <TouchableOpacity onPress={() => navigation.navigate('Transactions')} activeOpacity={0.7}>
              <Text style={styles.seeAll}>See All</Text>
            </TouchableOpacity>
          </View>

          {recent_transactions.slice(0, 5).map((transaction, index) => {
            const statusPillColors = {
              completed: { bg: '#e6f4ea', text: colors.success },
              pending:   { bg: '#fff3e0', text: colors.warning },
              cancelled: { bg: '#fdecea', text: colors.error },
            };
            const pillColor = statusPillColors[transaction.status] || { bg: '#f1f5f9', text: colors.muted };
            const statusLabel = transaction.status
              ? transaction.status.charAt(0).toUpperCase() + transaction.status.slice(1)
              : null;

            return (
              <View key={transaction.id} style={[styles.txCard, index > 0 && styles.txCardGap]}>
                <View style={styles.txIconBox}>
                  <Ionicons name="cart-outline" size={22} color="#4f46e5" />
                </View>
                <View style={styles.txBody}>
                  <View style={styles.txTopRow}>
                    <Text style={styles.txNumber} numberOfLines={1}>{transaction.transaction_number}</Text>
                    <Text style={styles.txAmount}>{formatCurrency(transaction.total_amount)}</Text>
                  </View>
                  <View style={styles.txMidRow}>
                    <Text style={styles.txDate}>{formatDate(transaction.created_at)}</Text>
                    {statusLabel ? (
                      <View style={[styles.txStatusPill, { backgroundColor: pillColor.bg }]}>
                        <Text style={[styles.txStatusText, { color: pillColor.text }]}>{statusLabel}</Text>
                      </View>
                    ) : null}
                  </View>
                  {(transaction.payment_method_display || transaction.items) ? (
                    <>
                      <View style={styles.txDivider} />
                      <View style={styles.txFooterRow}>
                        {transaction.payment_method_display ? (
                          <Text style={styles.txMeta}>{transaction.payment_method_display}</Text>
                        ) : null}
                        {transaction.items && transaction.items.length > 0 ? (
                          <View style={styles.txItemCount}>
                            <Ionicons name="cube-outline" size={11} color={colors.textSecondary} />
                            <Text style={styles.txItemCountText}>
                              {transaction.items.length} item{transaction.items.length > 1 ? 's' : ''}
                            </Text>
                          </View>
                        ) : null}
                      </View>
                    </>
                  ) : null}
                </View>
              </View>
            );
          })}
        </View>
      ) : (
        <View style={styles.card}>
          <View style={styles.emptyState}>
            <Ionicons name="receipt-outline" size={36} color={colors.muted} />
            <Text style={styles.emptyStateText}>No transactions yet</Text>
          </View>
        </View>
      )}

      {/* ── Month Picker Modal ── */}
      <Modal
        visible={showMonthPicker}
        transparent={true}
        animationType="slide"
        onRequestClose={() => setShowMonthPicker(false)}
      >
        <View style={styles.sheetOverlay}>
          <View style={styles.sheet}>
            <View style={styles.sheetHandle} />
            <View style={styles.sheetHeader}>
              <Text style={styles.sheetTitle}>Select Month</Text>
              <TouchableOpacity onPress={() => setShowMonthPicker(false)} style={styles.sheetClose}>
                <Ionicons name="close" size={22} color={colors.textSecondary} />
              </TouchableOpacity>
            </View>
            <FlatList
              data={generateMonthOptions()}
              keyExtractor={(item) => `${item.year}-${item.month}`}
              renderItem={({ item }) => {
                const isSelected = selectedYear === item.year && selectedMonth === item.month;
                return (
                  <TouchableOpacity
                    style={[styles.monthOption, isSelected && styles.monthOptionSelected]}
                    onPress={() => handleMonthSelect(item.year, item.month)}
                    activeOpacity={0.7}
                  >
                    <Text style={[styles.monthOptionText, isSelected && styles.monthOptionTextSelected]}>
                      {item.label}
                    </Text>
                    {isSelected && (
                      <Ionicons name="checkmark-circle" size={20} color={colors.brand} />
                    )}
                  </TouchableOpacity>
                );
              }}
            />
          </View>
        </View>
      </Modal>

      {/* Settings Modal */}
      <Modal
        visible={showSettings}
        transparent={true}
        animationType="fade"
        onRequestClose={() => setShowSettings(false)}
      >
        <TouchableOpacity
          style={styles.settingsOverlay}
          activeOpacity={1}
          onPress={() => setShowSettings(false)}
        >
          <View style={styles.settingsCard} onStartShouldSetResponder={() => true}>
            {/* User info strip */}
            <View style={styles.settingsUserStrip}>
              <View style={styles.settingsAvatar}>
                <Text style={styles.settingsAvatarText}>
                  {member.full_name ? member.full_name.charAt(0).toUpperCase() : '?'}
                </Text>
              </View>
              <View style={{ flex: 1 }}>
                <Text style={styles.settingsUserName}>{member.full_name}</Text>
                <Text style={styles.settingsUserSub}>Member Account</Text>
              </View>
              <TouchableOpacity onPress={() => setShowSettings(false)} style={styles.settingsXBtn}>
                <Ionicons name="close" size={22} color={colors.textSecondary} />
              </TouchableOpacity>
            </View>

            {/* Logout row */}
            <TouchableOpacity style={styles.settingsRow} onPress={handleLogout} activeOpacity={0.7}>
              <View style={styles.settingsRowLeft}>
                <View style={[styles.settingsRowIcon, { backgroundColor: '#fef2f2' }]}>
                  <Ionicons name="log-out-outline" size={20} color={colors.error} />
                </View>
                <Text style={[styles.settingsRowLabel, { color: colors.error }]}>Logout</Text>
              </View>
              <Ionicons name="chevron-forward" size={18} color={colors.error} />
            </TouchableOpacity>
          </View>
        </TouchableOpacity>
      </Modal>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f0f4f8',
  },
  scrollContent: {
    paddingBottom: 32,
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#f0f4f8',
    gap: 12,
  },
  loadingText: {
    fontSize: 14,
    color: colors.textSecondary,
    marginTop: 8,
  },
  emptyText: {
    fontSize: 16,
    color: colors.textSecondary,
    marginTop: 8,
    textAlign: 'center',
    paddingHorizontal: 32,
  },
  retryButton: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.brand,
    paddingVertical: 12,
    paddingHorizontal: 28,
    borderRadius: 24,
    marginTop: 24,
  },
  retryButtonText: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '600',
  },

  // ── Header ──
  header: {
    backgroundColor: colors.brand,
    paddingTop: 56,
    paddingBottom: 56,
    paddingHorizontal: 20,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  headerLeft: {
    flex: 1,
    paddingRight: 12,
  },
  greeting: {
    color: 'rgba(255,255,255,0.8)',
    fontSize: 14,
    fontWeight: '400',
  },
  name: {
    color: colors.textWhite,
    fontSize: 22,
    fontWeight: '700',
    marginTop: 2,
  },
  avatarButton: {
    padding: 2,
  },
  avatarCircle: {
    width: 42,
    height: 42,
    borderRadius: 21,
    backgroundColor: 'rgba(255,255,255,0.25)',
    justifyContent: 'center',
    alignItems: 'center',
    borderWidth: 2,
    borderColor: 'rgba(255,255,255,0.5)',
  },
  avatarInitial: {
    color: colors.textWhite,
    fontSize: 18,
    fontWeight: '700',
  },

  // ── Hero Balance Card ──
  heroWrapper: {
    marginHorizontal: 16,
    marginTop: -36,
    marginBottom: 16,
  },
  heroCard: {
    backgroundColor: colors.panel,
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
    color: colors.textSecondary,
    fontWeight: '500',
  },
  heroAmount: {
    fontSize: 36,
    fontWeight: '800',
    color: colors.brand,
    letterSpacing: -0.5,
  },
  heroDivider: {
    height: 1,
    backgroundColor: colors.borderLight,
  },
  heroAction: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    padding: 14,
    paddingHorizontal: 20,
  },
  heroActionText: {
    flex: 1,
    fontSize: 14,
    color: colors.brand,
    fontWeight: '600',
  },

  // ── Card (generic section container) ──
  card: {
    backgroundColor: colors.panel,
    marginHorizontal: 16,
    marginBottom: 16,
    borderRadius: 16,
    padding: 20,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.07,
    shadowRadius: 8,
    elevation: 3,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  cardTitle: {
    fontSize: 16,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  seeAll: {
    fontSize: 13,
    color: colors.brand,
    fontWeight: '600',
  },

  // ── Month Chip ──
  monthChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
    backgroundColor: '#e8f5e9',
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 20,
  },
  monthChipText: {
    fontSize: 12,
    color: colors.brand,
    fontWeight: '600',
  },

  // ── Spending Stat ──
  spendRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    backgroundColor: '#f8fdf9',
    borderRadius: 12,
    padding: 14,
  },
  spendIconWrap: {
    width: 44,
    height: 44,
    borderRadius: 12,
    backgroundColor: '#e8f5e9',
    justifyContent: 'center',
    alignItems: 'center',
  },
  spendLabel: {
    fontSize: 12,
    color: colors.textSecondary,
    fontWeight: '500',
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    marginBottom: 3,
  },
  spendAmount: {
    fontSize: 24,
    fontWeight: '800',
    color: colors.textPrimary,
  },

  // ── Transaction Cards (HomeScreen recent) ──
  txCard: {
    flexDirection: 'row',
    backgroundColor: '#f8fafc',
    borderRadius: 12,
    padding: 12,
    borderWidth: 1,
    borderColor: '#eef2f7',
  },
  txCardGap: {
    marginTop: 8,
  },
  txIconBox: {
    width: 42,
    height: 42,
    borderRadius: 11,
    backgroundColor: '#eef2ff',
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
    marginTop: 1,
  },
  txBody: {
    flex: 1,
  },
  txTopRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 3,
  },
  txNumber: {
    fontSize: 14,
    fontWeight: '700',
    color: colors.textPrimary,
    flex: 1,
    marginRight: 8,
  },
  txAmount: {
    fontSize: 14,
    fontWeight: '800',
    color: colors.brand,
    letterSpacing: -0.2,
  },
  txMidRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  txDate: {
    fontSize: 12,
    color: colors.textSecondary,
  },
  txStatusPill: {
    paddingHorizontal: 7,
    paddingVertical: 2,
    borderRadius: 10,
  },
  txStatusText: {
    fontSize: 11,
    fontWeight: '700',
  },
  txDivider: {
    height: 1,
    backgroundColor: '#eef2f7',
    marginTop: 8,
    marginBottom: 6,
  },
  txFooterRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  txMeta: {
    fontSize: 12,
    color: colors.textSecondary,
    flex: 1,
  },
  txItemCount: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
  },
  txItemCountText: {
    fontSize: 11,
    color: colors.textSecondary,
  },

  // ── Empty State ──
  emptyState: {
    alignItems: 'center',
    paddingVertical: 20,
    gap: 8,
  },
  emptyStateText: {
    fontSize: 14,
    color: colors.muted,
  },

  // ── Month Picker Sheet ──
  sheetOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.45)',
    justifyContent: 'flex-end',
  },
  sheet: {
    backgroundColor: colors.panel,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    maxHeight: '70%',
    paddingBottom: 24,
  },
  sheetHandle: {
    width: 40,
    height: 4,
    borderRadius: 2,
    backgroundColor: colors.borderLight,
    alignSelf: 'center',
    marginTop: 12,
    marginBottom: 4,
  },
  sheetHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderLight,
  },
  sheetTitle: {
    fontSize: 18,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  sheetClose: {
    padding: 4,
  },
  monthOption: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 14,
    paddingHorizontal: 20,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderLight,
  },
  monthOptionSelected: {
    backgroundColor: '#f0faf2',
  },
  monthOptionText: {
    fontSize: 15,
    color: colors.textPrimary,
  },
  monthOptionTextSelected: {
    color: colors.brand,
    fontWeight: '700',
  },

  // ── Settings Modal ──
  settingsOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.45)',
    justifyContent: 'center',
    alignItems: 'center',
    padding: 20,
  },
  settingsCard: {
    backgroundColor: colors.panel,
    borderRadius: 20,
    width: '100%',
    maxWidth: 400,
    overflow: 'hidden',
  },
  settingsUserStrip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    padding: 20,
    backgroundColor: '#f8fdf9',
    borderBottomWidth: 1,
    borderBottomColor: colors.borderLight,
  },
  settingsAvatar: {
    width: 44,
    height: 44,
    borderRadius: 22,
    backgroundColor: colors.brand,
    justifyContent: 'center',
    alignItems: 'center',
  },
  settingsAvatarText: {
    color: colors.textWhite,
    fontSize: 18,
    fontWeight: '700',
  },
  settingsUserName: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.textPrimary,
  },
  settingsUserSub: {
    fontSize: 12,
    color: colors.textSecondary,
    marginTop: 1,
  },
  settingsXBtn: {
    padding: 4,
  },
  settingsRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 18,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderLight,
  },
  settingsRowLeft: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 14,
    flex: 1,
  },
  settingsRowIcon: {
    width: 38,
    height: 38,
    borderRadius: 10,
    justifyContent: 'center',
    alignItems: 'center',
  },
  settingsRowLabel: {
    fontSize: 15,
    color: colors.textPrimary,
    fontWeight: '600',
  },
});

