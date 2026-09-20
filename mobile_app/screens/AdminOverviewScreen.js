import React, { useEffect, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  RefreshControl,
  StatusBar,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { authService, adminService } from '../services/api';
import { colors } from '../constants/colors';

const INITIAL_TEMPLATE_DATA = {
  activeCashierLogin: 1,
  activeCashierName: null,
  assignedMobile: null,
  shiftStatus: 'Waiting for live data',
  queueStatus: 'No queue data yet',
  pendingApprovals: 0,
  flaggedTransactions: 0,
  lowStockItems: 0,
  lastSync: null,
};

export default function AdminOverviewScreen() {
  const [refreshing, setRefreshing] = useState(false);
  const [adminName, setAdminName] = useState('Admin');
  const [templateData, setTemplateData] = useState(INITIAL_TEMPLATE_DATA);

  const loadTemplateData = async () => {
    try {
      const member = await authService.getStoredMember();
      if (member?.full_name) {
        setAdminName(member.full_name);
      }

      let queueSynced = false;
      let watchlistSynced = false;

      // Pull live Important Details from backend.
      try {
        const detailsResponse = await adminService.getImportantDetails();
        if (detailsResponse?.success && detailsResponse.important_details) {
          const details = detailsResponse.important_details;
          setTemplateData((prev) => ({
            ...prev,
            activeCashierLogin: Number(details.active_cashier_login_count || 0),
            activeCashierName: details.active_cashier_name || null,
            assignedMobile: details.assigned_mobile || null,
            shiftStatus: details.cashier_shift_status || prev.shiftStatus,
            queueStatus: details.queue_status || prev.queueStatus,
          }));
          queueSynced = true;
        }
      } catch {
        // Keep fallback values if endpoint is unavailable.
      }

      // Pull operational watchlist values from backend.
      try {
        const watchlistResponse = await adminService.getOperationalWatchlist();
        if (watchlistResponse?.success && watchlistResponse.watchlist) {
          const watchlist = watchlistResponse.watchlist;
          setTemplateData((prev) => ({
            ...prev,
            pendingApprovals: Number(watchlist.pending_approvals || 0),
            flaggedTransactions: Number(watchlist.flagged_transactions || 0),
            lowStockItems: Number(watchlist.low_stock_items || 0),
          }));
          watchlistSynced = true;
        }
      } catch {
        // Keep fallback values if endpoint is unavailable.
      }

      setTemplateData((prev) => ({
        ...prev,
        // Mark sync time if at least one admin endpoint succeeded.
        lastSync: (queueSynced || watchlistSynced) ? new Date() : prev.lastSync,
      }));
    } finally {
      setRefreshing(false);
    }
  };

  useEffect(() => {
    loadTemplateData();
  }, []);

  const onRefresh = () => {
    setRefreshing(true);
    loadTemplateData();
  };

  const formatSyncTime = (date) => {
    if (!date) return 'No sync yet';
    return date.toLocaleString('en-PH', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const StatCard = ({ title, value, icon, tone = 'normal' }) => (
    <View style={styles.statCard}>
      <View style={styles.statTopRow}>
        <Text style={styles.statTitle} numberOfLines={2}>
          {title}
        </Text>
        <View style={[styles.statIconWrap, tone === 'alert' && styles.statIconWrapAlert]}>
          <Ionicons
            name={icon}
            size={16}
            color={tone === 'alert' ? colors.error : colors.brand}
          />
        </View>
      </View>
      <Text style={[styles.statValue, tone === 'alert' && styles.statValueAlert]}>
        {value}
      </Text>
    </View>
  );

  const activeCashierText =
    templateData.activeCashierLogin > 0
      ? templateData.activeCashierName
        ? `${templateData.activeCashierLogin} active cashier logged in (${templateData.activeCashierName})`
        : `${templateData.activeCashierLogin} active cashier logged in`
      : 'No active cashier login';
  const assignedMobileText = templateData.assignedMobile || 'No mobile assigned';

  return (
    <ScrollView
      style={styles.container}
      contentContainerStyle={styles.content}
      refreshControl={<RefreshControl refreshing={refreshing} onRefresh={onRefresh} tintColor={colors.brand} />}
      showsVerticalScrollIndicator={false}
    >
      <StatusBar barStyle="light-content" backgroundColor={colors.brand} />

      <View style={styles.header}>
        <Text style={styles.headerLabel}>Admin Dashboard</Text>
        <Text style={styles.headerName} numberOfLines={1}>{adminName}</Text>
        <Text style={styles.syncText}>Last sync: {formatSyncTime(templateData.lastSync)}</Text>
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Important Details</Text>
        <StatCard
          title="Active Cashier Login"
          value={activeCashierText}
          icon="person-circle-outline"
        />
        <StatCard
          title="Assigned Mobile"
          value={assignedMobileText}
          icon="phone-portrait-outline"
          tone={templateData.assignedMobile ? 'normal' : 'alert'}
        />
        <StatCard
          title="Cashier Shift Status"
          value={templateData.shiftStatus}
          icon="time-outline"
        />
        <StatCard
          title="Checkout Queue"
          value={templateData.queueStatus}
          icon="people-outline"
        />
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Operational Watchlist</Text>
        <View style={styles.metricsGrid}>
          <View style={styles.metricBox}>
            <Text style={styles.metricLabel}>Pending Approvals</Text>
            <Text style={styles.metricValue}>{templateData.pendingApprovals}</Text>
          </View>
          <View style={styles.metricBox}>
            <Text style={styles.metricLabel}>Flagged Transactions</Text>
            <Text style={[styles.metricValue, { color: colors.error }]}>
              {templateData.flaggedTransactions}
            </Text>
          </View>
          <View style={styles.metricBox}>
            <Text style={styles.metricLabel}>Low Stock Items</Text>
            <Text style={styles.metricValue}>{templateData.lowStockItems}</Text>
          </View>
        </View>
      </View>

    </ScrollView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#f1f5f9',
  },
  content: {
    paddingBottom: 28,
  },
  header: {
    backgroundColor: colors.brand,
    paddingTop: 58,
    paddingBottom: 26,
    paddingHorizontal: 18,
  },
  headerLabel: {
    color: 'rgba(255,255,255,0.82)',
    fontSize: 13,
    fontWeight: '600',
  },
  headerName: {
    color: '#fff',
    fontSize: 23,
    fontWeight: '800',
    marginTop: 4,
  },
  syncText: {
    marginTop: 8,
    color: 'rgba(255,255,255,0.82)',
    fontSize: 12,
  },
  section: {
    marginTop: 14,
    marginHorizontal: 14,
    backgroundColor: '#fff',
    borderRadius: 14,
    padding: 14,
    borderWidth: 1,
    borderColor: '#e2e8f0',
  },
  sectionTitle: {
    fontSize: 15,
    color: colors.textPrimary,
    fontWeight: '700',
    marginBottom: 10,
  },
  statCard: {
    backgroundColor: '#f8fafc',
    borderRadius: 12,
    padding: 12,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: '#e2e8f0',
  },
  statTopRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    columnGap: 8,
  },
  statTitle: {
    flex: 1,
    fontSize: 12,
    color: colors.textSecondary,
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    fontWeight: '600',
    lineHeight: 16,
  },
  statIconWrap: {
    width: 28,
    height: 28,
    borderRadius: 8,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: '#e6f4ec',
  },
  statIconWrapAlert: {
    backgroundColor: '#fdecec',
  },
  statValue: {
    marginTop: 8,
    fontSize: 16,
    color: colors.textPrimary,
    fontWeight: '700',
    lineHeight: 22,
    flexShrink: 1,
  },
  statValueAlert: {
    color: colors.error,
  },
  metricsGrid: {
    gap: 8,
  },
  metricBox: {
    backgroundColor: '#f8fafc',
    borderRadius: 12,
    borderWidth: 1,
    borderColor: '#e2e8f0',
    paddingVertical: 12,
    paddingHorizontal: 12,
  },
  metricLabel: {
    fontSize: 12,
    color: colors.textSecondary,
    marginBottom: 4,
  },
  metricValue: {
    fontSize: 22,
    color: colors.textPrimary,
    fontWeight: '800',
  },
});

