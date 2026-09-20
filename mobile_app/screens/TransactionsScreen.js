import React, { useState, useEffect, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  ActivityIndicator,
  RefreshControl,
  Alert,
  TouchableOpacity,
  Modal,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as LocalAuthentication from 'expo-local-authentication';
import { accountService } from '../services/api';
import { colors } from '../constants/colors';
import { useAutoRefresh } from '../hooks/useAutoRefresh';

const REFUND_REASONS = [
  { id: 'defective',   label: 'Defective / Damaged Item' },
  { id: 'wrong_item',  label: 'Wrong Item Received' },
  { id: 'overcharged', label: 'Overcharged / Price Error' },
  { id: 'duplicate',   label: 'Duplicate Transaction' },
  { id: 'not_received',label: 'Item Not Received' },
  { id: 'expired',     label: 'Expired Product' },
  { id: 'other',       label: 'Other' },
];

export default function TransactionsScreen() {
  const [transactions, setTransactions] = useState([]);
  const [balanceTransactions, setBalanceTransactions] = useState([]);
  const [allTransactions, setAllTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [page, setPage] = useState(1);
  const [balancePage, setBalancePage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [hasMoreBalance, setHasMoreBalance] = useState(true);
  const [pagination, setPagination] = useState(null);
  const [balancePagination, setBalancePagination] = useState(null);
  const [showAll, setShowAll] = useState(false);
  const [filterType, setFilterType] = useState('all'); // 'all', 'purchases', 'transfers'
  const [refundWindowDays, setRefundWindowDays] = useState(1); // from server refund policy
  const [refundingIds, setRefundingIds] = useState(new Set()); // tracks in-flight refund requests
  const [showItemModal, setShowItemModal] = useState(false);
  const [showReasonModal, setShowReasonModal] = useState(false);
  const [selectedReason, setSelectedReason] = useState(null);
  const [selectedItemIds, setSelectedItemIds] = useState(new Set());
  const [pendingRefundItem, setPendingRefundItem] = useState(null);

  useEffect(() => {
    loadAllData();
  }, []);

  // Auto-refresh every 30 seconds while screen is focused
  const autoRefreshCallback = useCallback(() => {
    loadAllData();
  }, []);
  useAutoRefresh(autoRefreshCallback, 30000);

  useEffect(() => {
    // Merge and sort transactions when data changes
    const merged = [];
    
    // Add purchase transactions with type marker
    if (filterType === 'all' || filterType === 'purchases') {
      const purchaseTransactions = transactions.map(t => ({
        ...t,
        transactionType: 'purchase',
        sortDate: new Date(t.created_at)
      }));
      merged.push(...purchaseTransactions);
    }
    
    // Add balance transactions with type marker
    if (filterType === 'all' || filterType === 'transfers') {
      const transferTransactions = balanceTransactions.map(t => ({
        ...t,
        transactionType: 'transfer',
        sortDate: new Date(t.created_at)
      }));
      merged.push(...transferTransactions);
    }
    
    // Sort by date (newest first)
    merged.sort((a, b) => b.sortDate - a.sortDate);
    
    setAllTransactions(merged);
  }, [transactions, balanceTransactions, filterType]);

  const loadAllData = async () => {
    setLoading(true);
    await Promise.all([
      loadTransactions(1, false),
      loadBalanceTransactions(1, false)
    ]);
    setLoading(false);
  };

  const loadTransactions = async (pageNum = 1, append = false) => {
    try {
      const response = await accountService.getTransactionHistory(pageNum, 10);
      if (response.success) {
        if (append) {
          setTransactions([...transactions, ...response.transactions]);
        } else {
          setTransactions(response.transactions);
        }
        setPagination(response.pagination);
        setHasMore(response.pagination.has_next);
        if (!append && response.refund_window_days != null) {
          setRefundWindowDays(response.refund_window_days);
        }
      }
    } catch (error) {
      console.error('Error loading transactions:', error);
      if (!append) {
        Alert.alert('Error', error.toString());
      }
    } finally {
      if (!append) {
        setRefreshing(false);
      }
    }
  };

  const loadBalanceTransactions = async (pageNum = 1, append = false) => {
    try {
      const response = await accountService.getBalanceTransactions(pageNum, 10);
      if (response.success) {
        if (append) {
          setBalanceTransactions([...balanceTransactions, ...response.balance_transactions]);
        } else {
          setBalanceTransactions(response.balance_transactions);
        }
        setBalancePagination(response.pagination);
        setHasMoreBalance(response.pagination.has_next);
      }
    } catch (error) {
      console.error('Error loading balance transactions:', error);
      if (!append) {
        Alert.alert('Error', error.toString());
      }
    }
  };


  const handleRefresh = () => {
    setRefreshing(true);
    setPage(1);
    setBalancePage(1);
    setShowAll(false);
    loadAllData();
  };

  const loadMore = () => {
    if (!loading && showAll) {
      if (filterType === 'all') {
        // Load more from both if needed
        if (hasMore) {
          const nextPage = page + 1;
          setPage(nextPage);
          loadTransactions(nextPage, true);
        }
        if (hasMoreBalance) {
          const nextBalancePage = balancePage + 1;
          setBalancePage(nextBalancePage);
          loadBalanceTransactions(nextBalancePage, true);
        }
      } else if (filterType === 'purchases' && hasMore) {
        const nextPage = page + 1;
        setPage(nextPage);
        loadTransactions(nextPage, true);
      } else if (filterType === 'transfers' && hasMoreBalance) {
        const nextBalancePage = balancePage + 1;
        setBalancePage(nextBalancePage);
        loadBalanceTransactions(nextBalancePage, true);
      }
    }
  };

  const handleViewAll = async () => {
    setShowAll(true);
    setLoading(true);
    setPage(1);
    setBalancePage(1);
    await Promise.all([
      loadTransactions(1, false),
      loadBalanceTransactions(1, false)
    ]);
  };

  const handleViewRecent = async () => {
    setShowAll(false);
    setLoading(true);
    setPage(1);
    setBalancePage(1);
    await Promise.all([
      loadTransactions(1, false),
      loadBalanceTransactions(1, false)
    ]);
  };

  const handleDropdownSelect = (option) => {
    if (option === 'all') {
      handleViewAll();
    } else {
      handleViewRecent();
    }
  };

  const formatCurrency = (amount) => {
    const num = parseFloat(amount || 0);
    return `₱${num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  const formatDateTime = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getPaymentMethodStyle = (paymentMethod) => {
    switch (paymentMethod) {
      case 'debit':
        return { backgroundColor: colors.debit, label: 'DEBIT' };
      case 'cash':
        return { backgroundColor: colors.cash, label: 'CASH' };
      default:
        return { backgroundColor: colors.muted, label: 'OTHER' };
    }
  };

  const getStatusStyle = (status) => {
    switch (status) {
      case 'completed':
        return { backgroundColor: colors.success, label: 'COMPLETED' };
      case 'pending':
        return { backgroundColor: colors.warning, label: 'PENDING' };
      case 'cancelled':
        return { backgroundColor: colors.error, label: 'CANCELLED' };
      case 'refund_requested':
        return { backgroundColor: '#ea580c', label: 'REFUND REQUESTED' };
      case 'return_window':
        return { backgroundColor: '#d97706', label: 'AWAITING RETURN' };
      case 'return_expired':
        return { backgroundColor: '#9d174d', label: 'RETURN EXPIRED' };
      case 'refunded':
        return { backgroundColor: '#7c3aed', label: 'REFUNDED' };
      default:
        return { backgroundColor: colors.muted, label: status?.toUpperCase() || 'UNKNOWN' };
    }
  };

  const handleRequestRefund = (item) => {
    setPendingRefundItem(item);
    setSelectedReason(null);
    setSelectedItemIds(new Set());
    setShowItemModal(true);
  };

  const handleItemToggle = (itemId) => {
    setSelectedItemIds(prev => {
      const next = new Set(prev);
      if (next.has(itemId)) {
        next.delete(itemId);
      } else {
        next.add(itemId);
      }
      return next;
    });
  };

  const handleSelectAllItems = () => {
    if (!pendingRefundItem?.items) return;
    const allIds = pendingRefundItem.items.map(i => i.id);
    setSelectedItemIds(new Set(allIds));
  };

  const handleItemModalNext = () => {
    setShowItemModal(false);
    // Small delay so first modal fully unmounts before second animates in
    setTimeout(() => setShowReasonModal(true), 120);
  };

  const handleReasonBack = () => {
    setShowReasonModal(false);
    setTimeout(() => setShowItemModal(true), 120);
  };

  const authenticateUser = async () => {
    try {
      const hasHardware = await LocalAuthentication.hasHardwareAsync();
      const isEnrolled = await LocalAuthentication.isEnrolledAsync();

      if (!hasHardware || !isEnrolled) {
        // Device has no biometrics / no enrolled biometrics — fall back to device PIN/passcode
        const fallback = await LocalAuthentication.authenticateAsync({
          promptMessage: 'Verify your identity to submit refund',
          disableDeviceFallback: false,
          cancelLabel: 'Cancel',
        });
        return fallback.success;
      }

      const supportedTypes = await LocalAuthentication.supportedAuthenticationTypesAsync();
      const hasFace = supportedTypes.includes(LocalAuthentication.AuthenticationType.FACIAL_RECOGNITION);
      const hasFingerprint = supportedTypes.includes(LocalAuthentication.AuthenticationType.FINGERPRINT);

      const promptMessage = hasFace
        ? 'Use Face ID to confirm refund request'
        : hasFingerprint
          ? 'Use fingerprint to confirm refund request'
          : 'Enter your PIN to confirm refund request';

      const result = await LocalAuthentication.authenticateAsync({
        promptMessage,
        fallbackLabel: 'Use PIN',
        disableDeviceFallback: false,
        cancelLabel: 'Cancel',
      });

      return result.success;
    } catch (error) {
      console.error('Authentication error:', error);
      return false;
    }
  };

  const handleSubmitRefund = async () => {
    if (!selectedReason) return;
    setShowReasonModal(false);

    // Biometric / PIN authentication before proceeding
    const authenticated = await authenticateUser();
    if (!authenticated) {
      Alert.alert(
        'Authentication Failed',
        'Identity verification is required to submit a refund request. Please try again.',
        [
          {
            text: 'Try Again',
            onPress: () => {
              // Re-open reason modal so user can try again
              setTimeout(() => setShowReasonModal(true), 120);
            },
          },
          { text: 'Cancel', style: 'cancel' },
        ]
      );
      return;
    }

    const item = pendingRefundItem;
    const reasonLabel = REFUND_REASONS.find(r => r.id === selectedReason)?.label || selectedReason;
    const itemIds = Array.from(selectedItemIds);
    const selectedItemNames = item.items
      ? item.items.filter(i => itemIds.includes(i.id)).map(i => `• ${i.product_name} x${i.quantity}`)
      : [];
    const itemSummary = selectedItemNames.length > 0
      ? `\nItems: ${selectedItemNames.length} selected\n${selectedItemNames.join('\n')}`
      : '\nItems: All items';
    Alert.alert(
      'Confirm Refund Request',
      `Submit a refund request for transaction ${item.transaction_number}?\n\nAmount: ${formatCurrency(item.total_amount)}\nReason: ${reasonLabel}${itemSummary}\n\nAn admin will review and process your request.`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Submit Request',
          style: 'default',
          onPress: async () => {
            setRefundingIds(prev => new Set(prev).add(item.id));
            try {
              const result = await accountService.requestRefund(item.id, selectedReason, itemIds);
              if (result.success) {
                Alert.alert('Request Submitted', result.message);
                loadAllData();
              } else {
                Alert.alert('Error', result.error || 'Failed to submit refund request.');
              }
            } catch (error) {
              Alert.alert('Error', error.toString());
            } finally {
              setRefundingIds(prev => {
                const next = new Set(prev);
                next.delete(item.id);
                return next;
              });
            }
          },
        },
      ]
    );
  };

  const renderTransaction = ({ item }) => {
    if (item.transactionType === 'transfer') {
      const isDeposit = item.transaction_type === 'deposit';

      return (
        <View style={styles.card}>
          <View style={[styles.cardIconBox, { backgroundColor: isDeposit ? '#e6f4ea' : '#fdecea' }]}>
            <Ionicons
              name={isDeposit ? 'arrow-down-circle' : 'arrow-up-circle'}
              size={30}
              color={isDeposit ? colors.success : colors.error}
            />
          </View>
          <View style={styles.cardBody}>
            <View style={styles.cardTopRow}>
              <Text style={styles.cardTitle}>{isDeposit ? 'Fund Deposit' : 'Fund Deduction'}</Text>
              <Text style={[styles.cardAmount, isDeposit ? styles.amountGreen : styles.amountRed]}>
                {isDeposit ? '+' : '-'}{formatCurrency(item.amount)}
              </Text>
            </View>
            <View style={styles.cardMidRow}>
              <Text style={styles.cardDate}>{formatDateTime(item.created_at)}</Text>
              <View style={[styles.statusPill, { backgroundColor: '#e6f4ea' }]}>
                <Text style={[styles.statusPillText, { color: colors.success }]}>Completed</Text>
              </View>
            </View>
            <View style={styles.cardDivider} />
            <View style={styles.balanceRow}>
              <View style={styles.balanceBlock}>
                <Text style={styles.balanceMeta}>Before</Text>
                <Text style={styles.balanceFig}>{formatCurrency(item.balance_before)}</Text>
              </View>
              <Ionicons name="arrow-forward" size={14} color={colors.muted} style={{ marginTop: 8 }} />
              <View style={styles.balanceBlock}>
                <Text style={styles.balanceMeta}>After</Text>
                <Text style={[styles.balanceFig, { color: colors.brand, fontWeight: '700' }]}>
                  {formatCurrency(item.balance_after)}
                </Text>
              </View>
            </View>
            {item.notes ? (
              <Text style={styles.cardNote} numberOfLines={1}>{item.notes}</Text>
            ) : null}
          </View>
        </View>
      );
    }

    const paymentStyle = getPaymentMethodStyle(item.payment_method);
    const statusStyle = getStatusStyle(item.status);

    const statusPillColors = {
      completed:        { bg: '#e6f4ea', text: colors.success },
      pending:          { bg: '#fff3e0', text: colors.warning },
      cancelled:        { bg: '#fdecea', text: colors.error },
      refund_requested: { bg: '#fff4ed', text: '#ea580c' },
      return_window:    { bg: '#fef9c3', text: '#92400e' },
      return_expired:   { bg: '#fce7f3', text: '#9d174d' },
      refunded:         { bg: '#f3f0ff', text: '#7c3aed' },
    };
    const pillColor = statusPillColors[item.status] || { bg: '#f1f5f9', text: colors.muted };

    const isRefunding = refundingIds.has(item.id);
    const purchaseDate = new Date(item.created_at);
    const refundCutoff = new Date(Date.now() - refundWindowDays * 24 * 60 * 60 * 1000);
    const withinRefundWindow = purchaseDate >= refundCutoff;
    const canRequestRefund = item.status === 'completed' && withinRefundWindow;

    return (
      <View style={styles.card}>
        <View style={[styles.cardIconBox, { backgroundColor: '#eef2ff' }]}>
          <Ionicons name="cart-outline" size={26} color="#4f46e5" />
        </View>
        <View style={styles.cardBody}>
          <View style={styles.cardTopRow}>
            <Text style={styles.cardTitle} numberOfLines={1}>{item.transaction_number}</Text>
            <Text style={styles.cardAmount}>{formatCurrency(item.total_amount)}</Text>
          </View>
          <View style={styles.cardMidRow}>
            <Text style={styles.cardDate}>{formatDateTime(item.created_at)}</Text>
            <View style={[styles.statusPill, { backgroundColor: pillColor.bg }]}>
              <Text style={[styles.statusPillText, { color: pillColor.text }]}>
                {statusStyle.label.charAt(0) + statusStyle.label.slice(1).toLowerCase()}
              </Text>
            </View>
          </View>
          <View style={styles.cardDivider} />
          <View style={styles.cardFooterRow}>
            <View style={[styles.payPill, { backgroundColor: paymentStyle.backgroundColor + '22' }]}>
              <Text style={[styles.payPillText, { color: paymentStyle.backgroundColor }]}>
                {paymentStyle.label}
              </Text>
            </View>
            <Text style={styles.cardMeta}>{item.payment_method_display}</Text>
            {item.items && item.items.length > 0 && (
              <View style={styles.itemCountBadge}>
                <Ionicons name="cube-outline" size={12} color={colors.textSecondary} />
                <Text style={styles.itemCountText}>
                  {item.items.length} item{item.items.length > 1 ? 's' : ''}
                </Text>
              </View>
            )}
          </View>

          {item.status === 'completed' && !withinRefundWindow && (
            <View style={styles.refundExpiredBanner}>
              <Ionicons name="time-outline" size={13} color={colors.muted} style={{ marginRight: 5 }} />
              <Text style={styles.refundExpiredText}>
                Refund window closed ({refundWindowDays} day{refundWindowDays !== 1 ? 's' : ''})
              </Text>
            </View>
          )}

          {canRequestRefund && (
            <TouchableOpacity
              style={[styles.refundBtn, isRefunding && styles.refundBtnDisabled]}
              onPress={() => handleRequestRefund(item)}
              disabled={isRefunding}
              activeOpacity={0.8}
            >
              {isRefunding ? (
                <ActivityIndicator size="small" color="#ea580c" style={{ marginRight: 6 }} />
              ) : (
                <Ionicons name="return-down-back-outline" size={14} color="#ea580c" style={{ marginRight: 5 }} />
              )}
              <Text style={styles.refundBtnText}>
                {isRefunding ? 'Submitting…' : 'Request Refund'}
              </Text>
            </TouchableOpacity>
          )}

          {item.status === 'refund_requested' && (
            <View style={styles.refundPendingBanner}>
              <Ionicons name="time-outline" size={13} color="#ea580c" style={{ marginRight: 5 }} />
              <Text style={styles.refundPendingText}>Refund request pending admin approval</Text>
            </View>
          )}

          {item.status === 'return_window' && (
            <View style={styles.returnWindowCard}>
              <View style={styles.returnWindowHeader}>
                <Ionicons name="hourglass-outline" size={15} color="#92400e" style={{ marginRight: 6 }} />
                <Text style={styles.returnWindowTitle}>Waiting for Item Return</Text>
              </View>
              <Text style={styles.returnWindowBody}>
                Your refund has been approved. Please return the item(s) to the store within{' '}
                <Text style={styles.returnWindowEmphasis}>
                  {item.return_window_details?.window_days ?? 3} days
                </Text>
                . The refund money will only be credited after staff confirm receipt.
              </Text>
              {item.return_window_details && (
                <View style={styles.returnDeadlineRow}>
                  <Ionicons name="calendar-outline" size={12} color="#92400e" style={{ marginRight: 4 }} />
                  <Text style={styles.returnDeadlineLabel}>Return by: </Text>
                  <Text style={[
                    styles.returnDeadlineValue,
                    (item.return_window_details.days_remaining <= 1) && styles.returnDeadlineUrgent,
                  ]}>
                    {new Date(item.return_window_details.return_deadline).toLocaleDateString('en-US', {
                      month: 'short', day: 'numeric', year: 'numeric',
                    })}
                  </Text>
                  {item.return_window_details.days_remaining > 0 ? (
                    <Text style={[
                      styles.returnDaysLeft,
                      item.return_window_details.days_remaining <= 1 && styles.returnDaysLeftUrgent,
                    ]}>
                      {' '}({item.return_window_details.days_remaining} day{item.return_window_details.days_remaining !== 1 ? 's' : ''} left)
                    </Text>
                  ) : (
                    <Text style={[styles.returnDaysLeft, styles.returnDaysLeftUrgent]}> (expires today)</Text>
                  )}
                </View>
              )}
            </View>
          )}

          {item.status === 'return_expired' && (
            <View style={styles.returnExpiredCard}>
              <View style={styles.returnWindowHeader}>
                <Ionicons name="close-circle-outline" size={15} color="#9d174d" style={{ marginRight: 6 }} />
                <Text style={styles.returnExpiredTitle}>Return Period Expired</Text>
              </View>
              <Text style={styles.returnExpiredBody}>
                The 3-day return window has passed without an item return. No refund will be processed for this transaction.
              </Text>
            </View>
          )}

          {item.status === 'refunded' && (
            <View style={styles.refundedCard}>
              {/* Header row */}
              <View style={styles.refundedCardHeader}>
                <Ionicons name="checkmark-circle" size={15} color="#7c3aed" style={{ marginRight: 6 }} />
                <Text style={styles.refundedCardTitle}>
                  {item.refund_details?.is_partial ? 'Partial Refund Approved' : 'Refund Approved'}
                </Text>
                {item.refund_details?.refund_amount != null && (
                  <Text style={styles.refundedCardAmount}>
                    +{formatCurrency(item.refund_details.refund_amount)}
                  </Text>
                )}
              </View>

              {/* Refunded items list */}
              {item.refund_details?.refunded_items?.length > 0 && (
                <View style={styles.refundedItemsList}>
                  {item.refund_details.refunded_items.map((ri) => (
                    <View key={ri.id} style={styles.refundedItemRow}>
                      <Ionicons name="cube-outline" size={11} color="#7c3aed" style={{ marginRight: 4, marginTop: 1 }} />
                      <Text style={styles.refundedItemName} numberOfLines={1}>
                        {ri.product_name}
                      </Text>
                      <Text style={styles.refundedItemQty}>×{ri.quantity}</Text>
                      <Text style={styles.refundedItemPrice}>{formatCurrency(ri.total_price)}</Text>
                    </View>
                  ))}
                </View>
              )}

              {/* Balance before → after */}
              {item.refund_details?.balance_before != null && item.refund_details?.balance_after != null && (
                <View style={styles.refundedBalanceRow}>
                  <View style={styles.refundedBalanceBlock}>
                    <Text style={styles.refundedBalanceMeta}>Balance Before</Text>
                    <Text style={styles.refundedBalanceFig}>{formatCurrency(item.refund_details.balance_before)}</Text>
                  </View>
                  <Ionicons name="arrow-forward" size={13} color="#7c3aed" style={{ marginHorizontal: 6, marginTop: 8 }} />
                  <View style={styles.refundedBalanceBlock}>
                    <Text style={styles.refundedBalanceMeta}>Balance After</Text>
                    <Text style={[styles.refundedBalanceFig, { color: '#7c3aed', fontWeight: '700' }]}>
                      {formatCurrency(item.refund_details.balance_after)}
                    </Text>
                  </View>
                </View>
              )}
            </View>
          )}
        </View>
      </View>
    );
  };

  const renderItemModal = () => {
    const items = pendingRefundItem?.items || [];
    const allSelected = items.length > 0 && items.every(i => selectedItemIds.has(i.id));
    return (
      <Modal
        visible={showItemModal}
        transparent
        animationType="slide"
        onRequestClose={() => setShowItemModal(false)}
      >
        <View style={styles.modalOverlay}>
          <View style={styles.modalContainer}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Select Items to Refund</Text>
              <TouchableOpacity onPress={() => setShowItemModal(false)} activeOpacity={0.7}>
                <Ionicons name="close" size={22} color={colors.textSecondary} />
              </TouchableOpacity>
            </View>
            <Text style={styles.modalSubtitle}>
              Choose the items you want to request a refund for.
            </Text>

            {/* Select All row */}
            {items.length > 1 && (
              <TouchableOpacity
                style={styles.selectAllRow}
                onPress={allSelected ? () => setSelectedItemIds(new Set()) : handleSelectAllItems}
                activeOpacity={0.7}
              >
                <View style={[styles.itemCheckbox, allSelected && styles.itemCheckboxSelected]}>
                  {allSelected && <Ionicons name="checkmark" size={13} color="#fff" />}
                </View>
                <Text style={styles.selectAllText}>
                  {allSelected ? 'Deselect All' : 'Select All'}
                </Text>
              </TouchableOpacity>
            )}

            {items.length === 0 ? (
              <View style={styles.noItemsBox}>
                <Ionicons name="cube-outline" size={32} color={colors.muted} />
                <Text style={styles.noItemsText}>No item details available</Text>
              </View>
            ) : (
              items.map((itemRow) => {
                const checked = selectedItemIds.has(itemRow.id);
                return (
                  <TouchableOpacity
                    key={itemRow.id}
                    style={[styles.itemOption, checked && styles.itemOptionSelected]}
                    onPress={() => handleItemToggle(itemRow.id)}
                    activeOpacity={0.7}
                  >
                    <View style={[styles.itemCheckbox, checked && styles.itemCheckboxSelected]}>
                      {checked && <Ionicons name="checkmark" size={13} color="#fff" />}
                    </View>
                    <View style={styles.itemOptionBody}>
                      <Text style={[styles.itemOptionName, checked && styles.itemOptionNameSelected]} numberOfLines={2}>
                        {itemRow.product_name}
                      </Text>
                      <View style={styles.itemOptionMeta}>
                        <Text style={styles.itemOptionQty}>Qty: {itemRow.quantity}</Text>
                        <Text style={styles.itemOptionPrice}>{formatCurrency(itemRow.total_price)}</Text>
                      </View>
                    </View>
                  </TouchableOpacity>
                );
              })
            )}

            <TouchableOpacity
              style={[styles.continueBtn, selectedItemIds.size === 0 && items.length > 0 && styles.continueBtnDisabled]}
              onPress={handleItemModalNext}
              disabled={selectedItemIds.size === 0 && items.length > 0}
              activeOpacity={0.8}
            >
              <Text style={styles.continueBtnText}>
                {selectedItemIds.size === 0 && items.length > 0
                  ? 'Select at least one item'
                  : `Next — ${selectedItemIds.size || items.length} item${(selectedItemIds.size || items.length) !== 1 ? 's' : ''}`}
              </Text>
              {(selectedItemIds.size > 0 || items.length === 0) && (
                <Ionicons name="arrow-forward" size={16} color="#fff" style={{ marginLeft: 6 }} />
              )}
            </TouchableOpacity>
          </View>
        </View>
      </Modal>
    );
  };

  const renderReasonModal = () => {
    const items = pendingRefundItem?.items || [];
    const selectedCount = selectedItemIds.size || items.length;
    const selectedNames = items
      .filter(i => selectedItemIds.size === 0 || selectedItemIds.has(i.id))
      .map(i => i.product_name);

    return (
    <Modal
      visible={showReasonModal}
      transparent
      animationType="slide"
      onRequestClose={() => setShowReasonModal(false)}
    >
      <View style={styles.modalOverlay}>
        <View style={styles.modalContainer}>
          <View style={styles.modalHeader}>
            <TouchableOpacity onPress={handleReasonBack} activeOpacity={0.7} style={styles.backBtn}>
              <Ionicons name="arrow-back" size={20} color={colors.textSecondary} />
            </TouchableOpacity>
            <Text style={styles.modalTitle}>Select Refund Reason</Text>
            <TouchableOpacity onPress={() => setShowReasonModal(false)} activeOpacity={0.7}>
              <Ionicons name="close" size={22} color={colors.textSecondary} />
            </TouchableOpacity>
          </View>
          <Text style={styles.modalSubtitle}>
            Why are you requesting a refund for this transaction?
          </Text>

          {/* Selected items summary chip */}
          <View style={styles.itemsSummaryBox}>
            <Ionicons name="cube-outline" size={14} color="#ea580c" style={{ marginRight: 5 }} />
            <Text style={styles.itemsSummaryText} numberOfLines={2}>
              {selectedCount} item{selectedCount !== 1 ? 's' : ''} selected
              {selectedNames.length > 0 ? `: ${selectedNames.join(', ')}` : ''}
            </Text>
          </View>
          {REFUND_REASONS.map((reason) => (
            <TouchableOpacity
              key={reason.id}
              style={[styles.reasonOption, selectedReason === reason.id && styles.reasonOptionSelected]}
              onPress={() => setSelectedReason(reason.id)}
              activeOpacity={0.7}
            >
              <View style={[styles.reasonRadio, selectedReason === reason.id && styles.reasonRadioSelected]}>
                {selectedReason === reason.id && <View style={styles.reasonRadioDot} />}
              </View>
              <Text style={[styles.reasonLabel, selectedReason === reason.id && styles.reasonLabelSelected]}>
                {reason.label}
              </Text>
            </TouchableOpacity>
          ))}
          <TouchableOpacity
            style={[styles.continueBtn, !selectedReason && styles.continueBtnDisabled]}
            onPress={handleSubmitRefund}
            disabled={!selectedReason}
            activeOpacity={0.8}
          >
            <Ionicons name="finger-print" size={16} color="#fff" style={{ marginRight: 6 }} />
            <Text style={styles.continueBtnText}>Verify &amp; Continue</Text>
            <Ionicons name="arrow-forward" size={16} color="#fff" style={{ marginLeft: 6 }} />
          </TouchableOpacity>
          <View style={styles.authNoteRow}>
            <Ionicons name="shield-checkmark-outline" size={13} color={colors.textSecondary} style={{ marginRight: 5 }} />
            <Text style={styles.authNoteText}>Biometric or PIN verification required to continue</Text>
          </View>
        </View>
      </View>
    </Modal>
    );
  };

  const renderFilterTabs = () => (
    <View style={styles.filterRow}>
      {['all', 'purchases', 'transfers'].map((tab) => {
        const labels = { all: 'All', purchases: 'Purchases', transfers: 'Transfers' };
        const icons  = { all: 'list-outline', purchases: 'cart-outline', transfers: 'swap-horizontal-outline' };
        const active = filterType === tab;
        return (
          <TouchableOpacity
            key={tab}
            style={[styles.filterPill, active && styles.filterPillActive]}
            onPress={() => setFilterType(tab)}
            activeOpacity={0.8}
          >
            <Ionicons
              name={icons[tab]}
              size={15}
              color={active ? '#fff' : colors.textSecondary}
              style={{ marginRight: 4 }}
            />
            <Text style={[styles.filterPillText, active && styles.filterPillTextActive]}>
              {labels[tab]}
            </Text>
          </TouchableOpacity>
        );
      })}
    </View>
  );

  const renderViewToggle = () => (
    <View style={styles.toggleRow}>
      <View style={styles.countBadge}>
        <Ionicons name="layers-outline" size={14} color={colors.textSecondary} />
        <Text style={styles.countText}>
          {allTransactions.length} transaction{allTransactions.length !== 1 ? 's' : ''}
        </Text>
      </View>
      <TouchableOpacity
        style={[styles.toggleBtn, showAll && styles.toggleBtnActive]}
        onPress={showAll ? handleViewRecent : handleViewAll}
        activeOpacity={0.8}
      >
        <Ionicons
          name={showAll ? 'time-outline' : 'albums-outline'}
          size={14}
          color={showAll ? colors.brand : colors.textSecondary}
          style={{ marginRight: 4 }}
        />
        <Text style={[styles.toggleBtnText, showAll && styles.toggleBtnTextActive]}>
          {showAll ? 'Show Recent' : 'View All'}
        </Text>
      </TouchableOpacity>
    </View>
  );

  const hasMoreToLoad = () => {
    if (filterType === 'all') {
      return (hasMore || hasMoreBalance) && showAll;
    } else if (filterType === 'purchases') {
      return hasMore && showAll;
    } else if (filterType === 'transfers') {
      return hasMoreBalance && showAll;
    }
    return false;
  };

  if (loading && allTransactions.length === 0) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color={colors.brand} />
        <Text style={styles.loadingText}>Loading transactions…</Text>
      </View>
    );
  }

  return (
    <View style={styles.container}>
      {renderItemModal()}
      {renderReasonModal()}
      {renderFilterTabs()}
      {renderViewToggle()}
      <FlatList
        data={allTransactions}
        renderItem={renderTransaction}
        keyExtractor={(item) => `${item.transactionType}-${item.id}`}
        contentContainerStyle={styles.listContent}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={handleRefresh}
            tintColor={colors.brand}
            colors={[colors.brand]}
          />
        }
        onEndReached={showAll ? loadMore : null}
        onEndReachedThreshold={0.5}
        ListEmptyComponent={
          <View style={styles.emptyContainer}>
            <Ionicons name="receipt-outline" size={56} color={colors.muted} />
            <Text style={styles.emptyTitle}>No Transactions</Text>
            <Text style={styles.emptySubtitle}>Your transaction history will appear here.</Text>
          </View>
        }
        ListFooterComponent={
          hasMoreToLoad() ? (
            <View style={styles.footer}>
              <ActivityIndicator size="small" color={colors.brand} />
            </View>
          ) : null
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f1f5f9',
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#f1f5f9',
    gap: 12,
  },
  loadingText: {
    fontSize: 14,
    color: colors.textSecondary,
    marginTop: 4,
  },

  // ── Filter pills ──────────────────────────────────────────────
  filterRow: {
    flexDirection: 'row',
    paddingHorizontal: 16,
    paddingVertical: 12,
    gap: 8,
    backgroundColor: '#fff',
    borderBottomWidth: 1,
    borderBottomColor: '#e8ecf0',
  },
  filterPill: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 8,
    borderRadius: 20,
    backgroundColor: '#f1f5f9',
    borderWidth: 1,
    borderColor: '#e2e8f0',
  },
  filterPillActive: {
    backgroundColor: colors.brand,
    borderColor: colors.brand,
  },
  filterPillText: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textSecondary,
  },
  filterPillTextActive: {
    color: '#fff',
  },

  // ── View toggle bar ───────────────────────────────────────────
  toggleRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 10,
    backgroundColor: '#f1f5f9',
  },
  countBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 5,
  },
  countText: {
    fontSize: 13,
    color: colors.textSecondary,
  },
  toggleBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 16,
    backgroundColor: '#fff',
    borderWidth: 1,
    borderColor: '#e2e8f0',
  },
  toggleBtnActive: {
    borderColor: colors.brand + '66',
    backgroundColor: colors.brand + '0d',
  },
  toggleBtnText: {
    fontSize: 13,
    fontWeight: '600',
    color: colors.textSecondary,
  },
  toggleBtnTextActive: {
    color: colors.brand,
  },

  // ── List ──────────────────────────────────────────────────────
  listContent: {
    paddingHorizontal: 16,
    paddingBottom: 24,
    paddingTop: 4,
  },

  // ── Transaction card ──────────────────────────────────────────
  card: {
    flexDirection: 'row',
    backgroundColor: '#fff',
    borderRadius: 14,
    marginTop: 10,
    padding: 14,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.07,
    shadowRadius: 6,
    elevation: 2,
  },
  cardIconBox: {
    width: 48,
    height: 48,
    borderRadius: 12,
    justifyContent: 'center',
    alignItems: 'center',
    marginRight: 12,
    marginTop: 2,
  },
  cardBody: {
    flex: 1,
  },
  cardTopRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 3,
  },
  cardTitle: {
    fontSize: 15,
    fontWeight: '700',
    color: colors.textPrimary,
    flex: 1,
    marginRight: 8,
  },
  cardAmount: {
    fontSize: 16,
    fontWeight: '800',
    color: colors.brand,
    letterSpacing: -0.3,
  },
  amountGreen: {
    color: '#16a34a',
  },
  amountRed: {
    color: colors.error,
  },
  cardMidRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 8,
  },
  cardDate: {
    fontSize: 12,
    color: colors.textSecondary,
  },
  statusPill: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 10,
  },
  statusPillText: {
    fontSize: 11,
    fontWeight: '700',
  },
  cardDivider: {
    height: 1,
    backgroundColor: '#f0f4f8',
    marginBottom: 8,
  },

  // Purchase card footer
  cardFooterRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
    flexWrap: 'wrap',
  },
  payPill: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
  payPillText: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.4,
  },
  cardMeta: {
    fontSize: 13,
    color: colors.textSecondary,
    flex: 1,
  },
  itemCountBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 3,
  },
  itemCountText: {
    fontSize: 12,
    color: colors.textSecondary,
  },

  // Transfer card balance area
  balanceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  balanceBlock: {
    alignItems: 'flex-start',
  },
  balanceMeta: {
    fontSize: 11,
    color: colors.textSecondary,
    marginBottom: 2,
  },
  balanceFig: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.textPrimary,
  },
  cardNote: {
    marginTop: 8,
    fontSize: 12,
    color: colors.textSecondary,
    fontStyle: 'italic',
  },

  // ── Empty state ───────────────────────────────────────────────
  emptyContainer: {
    alignItems: 'center',
    paddingTop: 60,
    paddingBottom: 40,
    gap: 10,
  },
  emptyTitle: {
    fontSize: 17,
    fontWeight: '700',
    color: colors.textPrimary,
    marginTop: 4,
  },
  emptySubtitle: {
    fontSize: 14,
    color: colors.textSecondary,
    textAlign: 'center',
    paddingHorizontal: 24,
  },

  // ── Footer loader ─────────────────────────────────────────────
  footer: {
    paddingVertical: 20,
    alignItems: 'center',
  },

  // ── Refund button ─────────────────────────────────────────────
  refundBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 10,
    paddingVertical: 7,
    paddingHorizontal: 12,
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#ea580c',
    backgroundColor: '#fff4ed',
    alignSelf: 'flex-start',
  },
  refundBtnDisabled: {
    opacity: 0.55,
  },
  refundBtnText: {
    fontSize: 12,
    fontWeight: '700',
    color: '#ea580c',
  },
  refundExpiredBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 10,
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 8,
    backgroundColor: '#f1f5f9',
    borderLeftWidth: 3,
    borderLeftColor: '#94a3b8',
  },
  refundExpiredText: {
    fontSize: 12,
    color: colors.textSecondary,
    fontWeight: '500',
    flex: 1,
  },
  refundPendingBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 10,
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 8,
    backgroundColor: '#fff4ed',
    borderLeftWidth: 3,
    borderLeftColor: '#ea580c',
  },
  refundPendingText: {
    fontSize: 12,
    color: '#ea580c',
    fontWeight: '600',
    flex: 1,
  },
  refundedBanner: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 10,
    paddingVertical: 6,
    paddingHorizontal: 10,
    borderRadius: 8,
    backgroundColor: '#f3f0ff',
    borderLeftWidth: 3,
    borderLeftColor: '#7c3aed',
  },
  refundedBannerText: {
    fontSize: 12,
    color: '#7c3aed',
    fontWeight: '600',
    flex: 1,
  },

  // ── Return Window card ─────────────────────────────────────────
  returnWindowCard: {
    marginTop: 10,
    borderRadius: 10,
    backgroundColor: '#fefce8',
    borderLeftWidth: 3,
    borderLeftColor: '#d97706',
    paddingVertical: 10,
    paddingHorizontal: 12,
  },
  returnWindowHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 5,
  },
  returnWindowTitle: {
    fontSize: 12,
    fontWeight: '700',
    color: '#92400e',
    flex: 1,
  },
  returnWindowBody: {
    fontSize: 12,
    color: '#78350f',
    lineHeight: 17,
    marginBottom: 8,
  },
  returnWindowEmphasis: {
    fontWeight: '700',
    color: '#b45309',
  },
  returnDeadlineRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingTop: 6,
    borderTopWidth: 1,
    borderTopColor: '#fde68a',
  },
  returnDeadlineLabel: {
    fontSize: 11,
    color: '#92400e',
  },
  returnDeadlineValue: {
    fontSize: 11,
    fontWeight: '700',
    color: '#92400e',
  },
  returnDeadlineUrgent: {
    color: '#dc2626',
  },
  returnDaysLeft: {
    fontSize: 11,
    color: '#92400e',
  },
  returnDaysLeftUrgent: {
    color: '#dc2626',
    fontWeight: '700',
  },

  // ── Return Expired card ────────────────────────────────────────
  returnExpiredCard: {
    marginTop: 10,
    borderRadius: 10,
    backgroundColor: '#fdf2f8',
    borderLeftWidth: 3,
    borderLeftColor: '#9d174d',
    paddingVertical: 10,
    paddingHorizontal: 12,
  },
  returnExpiredTitle: {
    fontSize: 12,
    fontWeight: '700',
    color: '#9d174d',
    flex: 1,
  },
  returnExpiredBody: {
    fontSize: 12,
    color: '#831843',
    lineHeight: 17,
  },

  // ── Refund approved detail card ───────────────────────────────
  refundedCard: {
    marginTop: 10,
    borderRadius: 10,
    backgroundColor: '#f3f0ff',
    borderLeftWidth: 3,
    borderLeftColor: '#7c3aed',
    paddingVertical: 10,
    paddingHorizontal: 12,
  },
  refundedCardHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 6,
  },
  refundedCardTitle: {
    fontSize: 12,
    fontWeight: '700',
    color: '#7c3aed',
    flex: 1,
  },
  refundedCardAmount: {
    fontSize: 13,
    fontWeight: '800',
    color: '#16a34a',
  },
  refundedItemsList: {
    marginBottom: 8,
    gap: 3,
  },
  refundedItemRow: {
    flexDirection: 'row',
    alignItems: 'center',
  },
  refundedItemName: {
    fontSize: 11,
    color: '#5b21b6',
    flex: 1,
  },
  refundedItemQty: {
    fontSize: 11,
    color: '#7c3aed',
    marginRight: 6,
  },
  refundedItemPrice: {
    fontSize: 11,
    fontWeight: '700',
    color: '#7c3aed',
  },
  refundedBalanceRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 4,
    paddingTop: 8,
    borderTopWidth: 1,
    borderTopColor: '#ddd6fe',
  },
  refundedBalanceBlock: {
    alignItems: 'flex-start',
  },
  refundedBalanceMeta: {
    fontSize: 10,
    color: '#7c3aed',
    marginBottom: 1,
  },
  refundedBalanceFig: {
    fontSize: 13,
    fontWeight: '600',
    color: '#5b21b6',
  },

  // ── Item selection modal ─────────────────────────────────────
  selectAllRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 10,
    paddingHorizontal: 4,
    marginBottom: 6,
    borderBottomWidth: 1,
    borderBottomColor: '#f0f4f8',
  },
  selectAllText: {
    fontSize: 13,
    fontWeight: '700',
    color: colors.textSecondary,
    marginLeft: 10,
  },
  noItemsBox: {
    alignItems: 'center',
    paddingVertical: 24,
    gap: 8,
  },
  noItemsText: {
    fontSize: 13,
    color: colors.textSecondary,
  },
  itemOption: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    paddingVertical: 12,
    paddingHorizontal: 14,
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: '#e2e8f0',
    marginBottom: 8,
    backgroundColor: '#fafafa',
  },
  itemOptionSelected: {
    borderColor: '#ea580c',
    backgroundColor: '#fff4ed',
  },
  itemCheckbox: {
    width: 22,
    height: 22,
    borderRadius: 6,
    borderWidth: 2,
    borderColor: '#cbd5e1',
    marginRight: 12,
    marginTop: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#fff',
  },
  itemCheckboxSelected: {
    borderColor: '#ea580c',
    backgroundColor: '#ea580c',
  },
  itemOptionBody: {
    flex: 1,
  },
  itemOptionName: {
    fontSize: 14,
    fontWeight: '600',
    color: colors.textPrimary,
    marginBottom: 4,
  },
  itemOptionNameSelected: {
    color: '#ea580c',
    fontWeight: '700',
  },
  itemOptionMeta: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
  },
  itemOptionQty: {
    fontSize: 12,
    color: colors.textSecondary,
  },
  itemOptionPrice: {
    fontSize: 13,
    fontWeight: '700',
    color: colors.brand,
  },

  // ── Refund reason modal ───────────────────────────────────────
  backBtn: {
    padding: 4,
    marginRight: 4,
  },
  itemsSummaryBox: {
    flexDirection: 'row',
    alignItems: 'flex-start',
    backgroundColor: '#fff4ed',
    borderRadius: 10,
    paddingVertical: 8,
    paddingHorizontal: 12,
    marginBottom: 14,
    borderWidth: 1,
    borderColor: '#fed7aa',
  },
  itemsSummaryText: {
    fontSize: 12,
    color: '#ea580c',
    fontWeight: '600',
    flex: 1,
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.45)',
    justifyContent: 'flex-end',
  },
  modalContainer: {
    backgroundColor: '#fff',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingHorizontal: 20,
    paddingTop: 20,
    paddingBottom: 36,
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 6,
  },
  modalTitle: {
    fontSize: 18,
    fontWeight: '800',
    color: colors.textPrimary,
  },
  modalSubtitle: {
    fontSize: 13,
    color: colors.textSecondary,
    marginBottom: 16,
  },
  reasonOption: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingVertical: 13,
    paddingHorizontal: 14,
    borderRadius: 12,
    borderWidth: 1.5,
    borderColor: '#e2e8f0',
    marginBottom: 8,
    backgroundColor: '#fafafa',
  },
  reasonOptionSelected: {
    borderColor: '#ea580c',
    backgroundColor: '#fff4ed',
  },
  reasonRadio: {
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: 2,
    borderColor: '#cbd5e1',
    marginRight: 12,
    justifyContent: 'center',
    alignItems: 'center',
  },
  reasonRadioSelected: {
    borderColor: '#ea580c',
  },
  reasonRadioDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    backgroundColor: '#ea580c',
  },
  reasonLabel: {
    fontSize: 14,
    fontWeight: '500',
    color: colors.textPrimary,
    flex: 1,
  },
  reasonLabelSelected: {
    color: '#ea580c',
    fontWeight: '700',
  },
  continueBtn: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 8,
    paddingVertical: 14,
    borderRadius: 12,
    backgroundColor: '#ea580c',
  },
  continueBtnDisabled: {
    backgroundColor: '#fdba74',
  },
  continueBtnText: {
    fontSize: 15,
    fontWeight: '800',
    color: '#fff',
  },
  authNoteRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    marginTop: 10,
  },
  authNoteText: {
    fontSize: 11,
    color: colors.textSecondary,
    flex: 1,
  },
});


