import React, { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import {
  View,
  Text,
  StyleSheet,
  SectionList,
  ActivityIndicator,
  RefreshControl,
  TextInput,
  TouchableOpacity,
  Modal,
  ScrollView,
  StatusBar,
} from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import { productService } from '../services/api';
import { colors } from '../constants/colors';
import { useAutoRefresh } from '../hooks/useAutoRefresh';

export default function ProductsScreen() {
  const [products, setProducts] = useState([]);
  const [categories, setCategories] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [search, setSearch] = useState('');
  const [selectedCategories, setSelectedCategories] = useState([]);
  const [showCategoryModal, setShowCategoryModal] = useState(false);
  const [error, setError] = useState(null);

  // Stable refs so the polling callback always reads the latest filter state
  const searchRef = useRef(search);
  const categoryRef = useRef(selectedCategories);
  useEffect(() => { searchRef.current = search; }, [search]);
  useEffect(() => { categoryRef.current = selectedCategories; }, [selectedCategories]);

  useEffect(() => {
    loadProducts(false, search, selectedCategories);
  }, [search, selectedCategories]);

  // Auto-refresh every 30 seconds while screen is focused
  const autoRefreshCallback = useCallback(() => {
    loadProducts(false, searchRef.current, categoryRef.current);
  }, []);
  useAutoRefresh(autoRefreshCallback, 30000);

  const loadProducts = async (
    isRefresh = false,
    currentSearch = search,
    currentCategories = selectedCategories,
  ) => {
    if (isRefresh) {
      setRefreshing(true);
    } else if (!refreshing) {
      setLoading(true);
    }
    setError(null);
    try {
      const response = await productService.getProducts({
        search: currentSearch,
        category: currentCategories.join(','),
      });
      if (response.success) {
        setProducts(response.products);
        if (response.categories) {
          setCategories([...new Set(response.categories.map((c) => String(c)))]);
        }
      }
    } catch (err) {
      setError(typeof err === 'string' ? err : 'Failed to load products');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const onRefresh = useCallback(() => {
    loadProducts(true, search, selectedCategories);
  }, [search, selectedCategories]);

  const toggleCategory = (cat) => {
    setSelectedCategories((prev) =>
      prev.includes(cat) ? prev.filter((c) => c !== cat) : [...prev, cat]
    );
  };

  const clearCategories = () => setSelectedCategories([]);

  // Group products by category for SectionList
  const sections = useMemo(() => {
    const groups = {};
    products.forEach((p) => {
      const key = p.category || 'Uncategorized';
      if (!groups[key]) groups[key] = [];
      groups[key].push(p);
    });
    return Object.keys(groups)
      .sort()
      .map((title, sectionIndex) => ({
        key: `section-${sectionIndex}-${title}`,
        title,
        data: groups[title],
      }));
  }, [products]);

  const getStockStatus = (product) => {
    if (product.is_out_of_stock) {
      return { label: 'Out of Stock', color: colors.error };
    }
    if (product.is_low_stock) {
      return { label: 'Low Stock', color: colors.warning };
    }
    return { label: 'In Stock', color: colors.success };
  };

  const renderProduct = ({ item }) => {
    const stockStatus = getStockStatus(item);
    return (
      <View style={styles.productCard}>
        <View style={styles.productHeader}>
          <Text style={styles.productName} numberOfLines={2}>
            {item.name}
          </Text>
          <Text style={styles.productPrice}>₱{parseFloat(item.price).toFixed(2)}</Text>
        </View>

        {item.category ? (
          <View style={styles.categoryBadge}>
            <Text style={styles.categoryBadgeText}>{item.category}</Text>
          </View>
        ) : null}

        <View style={styles.productFooter}>
          <View style={styles.stockInfo}>
            <Ionicons name="cube-outline" size={14} color={colors.textSecondary} />
            <Text style={styles.stockText}>
              Stock:{' '}
              <Text style={{ color: stockStatus.color, fontWeight: '600' }}>
                {item.stock_quantity} units
              </Text>
            </Text>
          </View>
          <View style={[styles.statusBadge, { backgroundColor: stockStatus.color + '20' }]}>
            <Text style={[styles.statusText, { color: stockStatus.color }]}>
              {stockStatus.label}
            </Text>
          </View>
        </View>

        <Text style={styles.barcodeText}>#{item.barcode}</Text>
      </View>
    );
  };

  const renderSectionHeader = ({ section }) => (
    <View style={styles.sectionHeader}>
      <View style={styles.sectionHeaderLine} />
      <View style={styles.sectionHeaderBadge}>
        <Ionicons name="pricetag-outline" size={12} color={colors.brand} style={{ marginRight: 4 }} />
        <Text style={styles.sectionHeaderText}>{section.title}</Text>
        <Text style={styles.sectionHeaderCount}> · {section.data.length}</Text>
      </View>
      <View style={styles.sectionHeaderLine} />
    </View>
  );

  const renderEmpty = () => {
    if (loading) return null;
    return (
      <View style={styles.emptyContainer}>
        <Ionicons name="cube-outline" size={56} color={colors.muted} />
        <Text style={styles.emptyTitle}>No Products Found</Text>
        <Text style={styles.emptySubtitle}>
          {search || selectedCategories.length > 0
            ? 'Try adjusting your search or filter'
            : 'No products available at the moment'}
        </Text>
      </View>
    );
  };

  return (
    <View style={styles.container}>
      <StatusBar barStyle="light-content" backgroundColor={colors.brand} />

      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.headerTitle}>Products</Text>
        <Text style={styles.headerSubtitle}>
          {loading ? 'Loading...' : `${products.length} item${products.length !== 1 ? 's' : ''}`}
        </Text>
      </View>

      {/* Search & Filter Bar */}
      <View style={styles.filterBar}>
        <View style={styles.searchBox}>
          <Ionicons name="search-outline" size={18} color={colors.muted} style={styles.searchIcon} />
          <TextInput
            style={styles.searchInput}
            placeholder="Search by name or barcode..."
            placeholderTextColor={colors.muted}
            value={search}
            onChangeText={setSearch}
            returnKeyType="search"
            clearButtonMode="while-editing"
          />
          {search.length > 0 && (
            <TouchableOpacity onPress={() => setSearch('')}>
              <Ionicons name="close-circle" size={18} color={colors.muted} />
            </TouchableOpacity>
          )}
        </View>

        <TouchableOpacity
          style={[styles.categoryButton, selectedCategories.length > 0 ? styles.categoryButtonActive : null]}
          onPress={() => setShowCategoryModal(true)}
        >
          {selectedCategories.length > 0 && (
            <View style={styles.categoryBadgeCount}>
              <Text style={styles.categoryBadgeCountText}>{selectedCategories.length}</Text>
            </View>
          )}
          <Ionicons
            name="filter-outline"
            size={18}
            color={selectedCategories.length > 0 ? colors.textWhite : colors.brand}
          />
        </TouchableOpacity>
      </View>

      {/* Active category chips */}
      {selectedCategories.length > 0 ? (
        <View style={styles.activeFilterRow}>
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipsScroll}>
            {selectedCategories.map((cat, i) => (
              <View key={`chip-${i}-${cat}`} style={styles.activeChip}>
                <Text style={styles.activeChipText}>{cat}</Text>
                <TouchableOpacity onPress={() => toggleCategory(cat)}>
                  <Ionicons name="close" size={14} color={colors.brand} />
                </TouchableOpacity>
              </View>
            ))}
            {selectedCategories.length > 1 && (
              <TouchableOpacity style={styles.clearAllChip} onPress={clearCategories}>
                <Text style={styles.clearAllText}>Clear all</Text>
              </TouchableOpacity>
            )}
          </ScrollView>
        </View>
      ) : null}

      {/* Error state */}
      {error ? (
        <View style={styles.errorContainer}>
          <Ionicons name="alert-circle-outline" size={20} color={colors.error} />
          <Text style={styles.errorText}>{error}</Text>
          <TouchableOpacity style={styles.retryButton} onPress={() => loadProducts()}>
            <Text style={styles.retryText}>Retry</Text>
          </TouchableOpacity>
        </View>
      ) : null}

      {/* Products list */}
      {loading && products.length === 0 ? (
        <View style={styles.loadingContainer}>
          <ActivityIndicator size="large" color={colors.brand} />
          <Text style={styles.loadingText}>Loading products...</Text>
        </View>
      ) : (
        <SectionList
          sections={sections}
          keyExtractor={(item, index, section) => {
            const sectionKey =
              section?.key ?? section?.title ?? item.category ?? 'Uncategorized';
            const idPart =
              item.id != null && item.id !== ''
                ? String(item.id)
                : item.barcode != null && item.barcode !== ''
                  ? String(item.barcode)
                  : `row-${index}`;
            return `${sectionKey}:${idPart}:${index}`;
          }}
          renderItem={renderProduct}
          renderSectionHeader={renderSectionHeader}
          ListEmptyComponent={renderEmpty}
          contentContainerStyle={products.length === 0 ? styles.emptyList : styles.listContent}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={onRefresh}
              tintColor={colors.brand}
              colors={[colors.brand]}
            />
          }
          showsVerticalScrollIndicator={false}
          stickySectionHeadersEnabled={false}
        />
      )}

      {/* Category Filter Modal */}
      <Modal
        visible={showCategoryModal}
        transparent
        animationType="slide"
        onRequestClose={() => setShowCategoryModal(false)}
      >
        <TouchableOpacity
          style={styles.modalOverlay}
          activeOpacity={1}
          onPress={() => setShowCategoryModal(false)}
        >
          <View style={styles.modalSheet}>
            <View style={styles.modalHandle} />
            <Text style={styles.modalTitle}>Filter by Category</Text>

            <ScrollView showsVerticalScrollIndicator={false}>
              {/* All option */}
              <TouchableOpacity
                style={[styles.categoryOption, selectedCategories.length === 0 && styles.categoryOptionActive]}
                onPress={() => { clearCategories(); setShowCategoryModal(false); }}
              >
                <Text
                  style={[
                    styles.categoryOptionText,
                    selectedCategories.length === 0 && styles.categoryOptionTextActive,
                  ]}
                >
                  All Categories
                </Text>
                {selectedCategories.length === 0 && (
                  <Ionicons name="checkmark" size={18} color={colors.brand} />
                )}
              </TouchableOpacity>

              {/* Divider */}
              {categories.length > 0 && (
                <View style={styles.sectionDivider}>
                  <View style={styles.dividerLine} />
                  <Text style={styles.dividerLabel}>CATEGORIES</Text>
                  <View style={styles.dividerLine} />
                </View>
              )}

              {categories.map((cat, i) => {
                const isSelected = selectedCategories.includes(cat);
                return (
                  <TouchableOpacity
                    key={`cat-opt-${i}-${cat}`}
                    style={[styles.categoryOption, isSelected && styles.categoryOptionActive]}
                    onPress={() => toggleCategory(cat)}
                  >
                    <Text
                      style={[
                        styles.categoryOptionText,
                        isSelected && styles.categoryOptionTextActive,
                      ]}
                    >
                      {cat}
                    </Text>
                    <View style={[styles.checkbox, isSelected && styles.checkboxSelected]}>
                      {isSelected && <Ionicons name="checkmark" size={14} color="#fff" />}
                    </View>
                  </TouchableOpacity>
                );
              })}
            </ScrollView>

            {/* Apply button */}
            {selectedCategories.length > 0 && (
              <TouchableOpacity
                style={styles.applyButton}
                onPress={() => setShowCategoryModal(false)}
              >
                <Text style={styles.applyButtonText}>
                  Apply ({selectedCategories.length} selected)
                </Text>
              </TouchableOpacity>
            )}
          </View>
        </TouchableOpacity>
      </Modal>
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
    paddingTop: 50,
    paddingBottom: 16,
    paddingHorizontal: 20,
  },
  headerTitle: {
    fontSize: 22,
    fontWeight: '700',
    color: colors.textWhite,
  },
  headerSubtitle: {
    fontSize: 13,
    color: 'rgba(255,255,255,0.75)',
    marginTop: 2,
  },
  filterBar: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: colors.panel,
    borderBottomWidth: 1,
    borderBottomColor: colors.border,
    gap: 10,
  },
  searchBox: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.background,
    borderRadius: 10,
    paddingHorizontal: 10,
    height: 40,
  },
  searchIcon: {
    marginRight: 6,
  },
  searchInput: {
    flex: 1,
    fontSize: 14,
    color: colors.textPrimary,
    height: 40,
  },
  categoryButton: {
    width: 40,
    height: 40,
    borderRadius: 10,
    borderWidth: 1.5,
    borderColor: colors.brand,
    alignItems: 'center',
    justifyContent: 'center',
  },
  categoryButtonActive: {
    backgroundColor: colors.brand,
    borderColor: colors.brand,
  },
  activeFilterRow: {
    backgroundColor: colors.panel,
    paddingVertical: 8,
  },
  chipsScroll: {
    flexDirection: 'row',
    paddingHorizontal: 16,
    gap: 8,
    alignItems: 'center',
  },
  activeChip: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.brand + '15',
    borderRadius: 20,
    paddingHorizontal: 12,
    paddingVertical: 4,
    gap: 6,
  },
  activeChipText: {
    fontSize: 13,
    color: colors.brand,
    fontWeight: '600',
  },
  clearAllChip: {
    paddingHorizontal: 12,
    paddingVertical: 4,
    borderRadius: 20,
    borderWidth: 1,
    borderColor: colors.error,
  },
  clearAllText: {
    fontSize: 13,
    color: colors.error,
    fontWeight: '600',
  },
  categoryBadgeCount: {
    position: 'absolute',
    top: -6,
    right: -6,
    backgroundColor: colors.error,
    borderRadius: 8,
    minWidth: 16,
    height: 16,
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1,
  },
  categoryBadgeCountText: {
    fontSize: 10,
    color: '#fff',
    fontWeight: '700',
  },
  listContent: {
    padding: 16,
  },
  emptyList: {
    flexGrow: 1,
  },
  sectionHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    marginTop: 8,
    marginBottom: 10,
    gap: 8,
  },
  sectionHeaderLine: {
    flex: 1,
    height: 1.5,
    backgroundColor: colors.border,
    borderRadius: 1,
  },
  sectionHeaderBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.brand + '18',
    borderRadius: 20,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderWidth: 1,
    borderColor: colors.brand + '40',
  },
  sectionHeaderText: {
    fontSize: 12,
    fontWeight: '700',
    color: colors.brand,
    letterSpacing: 0.3,
  },
  sectionHeaderCount: {
    fontSize: 12,
    fontWeight: '600',
    color: colors.brand + 'AA',
  },
  productCard: {
    backgroundColor: colors.panel,
    borderRadius: 14,
    padding: 16,
    marginBottom: 12,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 1 },
    shadowOpacity: 0.06,
    shadowRadius: 4,
    elevation: 2,
  },
  productHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 8,
  },
  productName: {
    flex: 1,
    fontSize: 16,
    fontWeight: '600',
    color: colors.textPrimary,
    marginRight: 12,
  },
  productPrice: {
    fontSize: 17,
    fontWeight: '700',
    color: colors.brand,
  },
  categoryBadge: {
    alignSelf: 'flex-start',
    backgroundColor: colors.info + '18',
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 2,
    marginBottom: 10,
  },
  categoryBadgeText: {
    fontSize: 12,
    color: colors.info,
    fontWeight: '500',
  },
  productFooter: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  stockInfo: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 4,
  },
  stockText: {
    fontSize: 13,
    color: colors.textSecondary,
  },
  statusBadge: {
    borderRadius: 6,
    paddingHorizontal: 8,
    paddingVertical: 3,
  },
  statusText: {
    fontSize: 12,
    fontWeight: '600',
  },
  barcodeText: {
    fontSize: 11,
    color: colors.textMuted,
    marginTop: 8,
  },
  loadingContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
  },
  loadingText: {
    fontSize: 14,
    color: colors.textSecondary,
  },
  emptyContainer: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: 32,
    paddingTop: 60,
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: '600',
    color: colors.textPrimary,
    marginTop: 16,
  },
  emptySubtitle: {
    fontSize: 14,
    color: colors.textSecondary,
    textAlign: 'center',
    marginTop: 6,
  },
  errorContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: colors.error + '15',
    margin: 16,
    padding: 12,
    borderRadius: 10,
    gap: 8,
  },
  errorText: {
    flex: 1,
    fontSize: 13,
    color: colors.error,
  },
  retryButton: {
    paddingHorizontal: 10,
    paddingVertical: 4,
    backgroundColor: colors.error,
    borderRadius: 6,
  },
  retryText: {
    fontSize: 12,
    color: '#fff',
    fontWeight: '600',
  },
  modalOverlay: {
    flex: 1,
    backgroundColor: 'rgba(0,0,0,0.4)',
    justifyContent: 'flex-end',
  },
  modalSheet: {
    backgroundColor: colors.panel,
    borderTopLeftRadius: 20,
    borderTopRightRadius: 20,
    paddingHorizontal: 20,
    paddingBottom: 32,
    maxHeight: '70%',
  },
  modalHandle: {
    width: 40,
    height: 4,
    backgroundColor: colors.border,
    borderRadius: 2,
    alignSelf: 'center',
    marginTop: 12,
    marginBottom: 16,
  },
  modalTitle: {
    fontSize: 17,
    fontWeight: '700',
    color: colors.textPrimary,
    marginBottom: 12,
  },
  categoryOption: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingVertical: 14,
    borderBottomWidth: 1,
    borderBottomColor: colors.borderLight,
  },
  categoryOptionActive: {},
  checkbox: {
    width: 20,
    height: 20,
    borderRadius: 5,
    borderWidth: 1.5,
    borderColor: colors.border,
    alignItems: 'center',
    justifyContent: 'center',
  },
  checkboxSelected: {
    backgroundColor: colors.brand,
    borderColor: colors.brand,
  },
  applyButton: {
    backgroundColor: colors.brand,
    borderRadius: 12,
    paddingVertical: 14,
    alignItems: 'center',
    marginTop: 16,
  },
  applyButtonText: {
    color: '#fff',
    fontSize: 15,
    fontWeight: '700',
  },
  sectionDivider: {
    flexDirection: 'row',
    alignItems: 'center',
    marginVertical: 12,
    gap: 8,
  },
  dividerLine: {
    flex: 1,
    height: 1,
    backgroundColor: colors.border,
  },
  dividerLabel: {
    fontSize: 11,
    fontWeight: '700',
    color: colors.textSecondary,
    letterSpacing: 1,
  },
  categoryOptionText: {
    fontSize: 15,
    color: colors.textPrimary,
  },
  categoryOptionTextActive: {
    color: colors.brand,
    fontWeight: '600',
  },
});
