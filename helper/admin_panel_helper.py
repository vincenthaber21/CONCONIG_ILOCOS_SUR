"""
Admin Panel Performance Helper Module
Optimizes database queries, caching, and background tasks for the Gen-Glow system
"""

import json
import logging
import secrets
import threading
from functools import wraps
from datetime import datetime, timedelta, date
from decimal import Decimal
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict

from django.conf import settings
from django.db import models, connection, transaction
from django.db.models import Sum, Count, Avg, Q, F, Prefetch, Value, IntegerField, DecimalField
from django.db.models.functions import TruncDate, TruncMonth, TruncWeek, Coalesce
from django.core.cache import cache
from django.utils import timezone
from django.core.paginator import Paginator

# Import models from your apps
from inventory.models import Product, Category
from members.models import Member, MemberType, BalanceTransaction, DeletedMember
from transactions.models import Transaction, TransactionItem

logger = logging.getLogger(__name__)

# ============================================
# CACHE MANAGEMENT
# ============================================

class CacheKeys:
    """Centralized cache key management"""
    DASHBOARD_STATS = 'dashboard_stats_{range}_{date}'
    PRODUCT_LIST = 'product_list_page_{page}_{search}_{filter}'
    MEMBER_LIST = 'member_list_page_{page}_{search}'
    TRANSACTION_LIST = 'transaction_list_page_{page}'
    TOP_PRODUCTS = 'top_products_{limit}_{period}'
    CATEGORY_SALES = 'category_sales_{limit}'
    LOW_STOCK_COUNT = 'low_stock_count'
    OUT_OF_STOCK_COUNT = 'out_of_stock_count'
    TODAY_SALES = 'today_sales_{date}'
    CHART_DATA = 'chart_data_{range}_{start}_{end}'
    REFUND_STATS = 'refund_stats_{range}_{date}'
    MEMBER_BALANCE = 'member_balance_{member_id}'
    PRODUCT_BY_BARCODE = 'product_barcode_{barcode}'
    MEMBER_BY_RFID = 'member_rfid_{rfid}'


class CacheService:
    """Service for managing cache operations with fallback"""
    
    DEFAULT_TIMEOUT = 300  # 5 minutes
    DASHBOARD_TIMEOUT = 60  # 1 minute for dashboard
    STATS_TIMEOUT = 1800  # 30 minutes for static stats
    SHORT_TIMEOUT = 30  # 30 seconds for real-time data
    
    @staticmethod
    def get(key: str, default=None):
        """Get value from cache"""
        try:
            return cache.get(key, default)
        except Exception as e:
            logger.warning(f"Cache get error for key {key}: {e}")
            return default
    
    @staticmethod
    def set(key: str, value, timeout: int = DEFAULT_TIMEOUT):
        """Set value in cache"""
        try:
            cache.set(key, value, timeout)
        except Exception as e:
            logger.warning(f"Cache set error for key {key}: {e}")
    
    @staticmethod
    def delete(key: str):
        """Delete from cache"""
        try:
            cache.delete(key)
        except Exception as e:
            logger.warning(f"Cache delete error for key {key}: {e}")
    
    @staticmethod
    def delete_pattern(pattern: str):
        """Delete keys matching pattern - for Redis/Django cache backends"""
        try:
            # Try to use delete_pattern if available (Redis cache)
            if hasattr(cache, 'delete_pattern'):
                cache.delete_pattern(pattern)
            else:
                # For locmem cache, we need to clear everything or use a workaround
                # Since locmem doesn't support pattern deletion, we'll invalidate specific known keys
                if 'dashboard_stats' in pattern:
                    # Invalidate common dashboard keys
                    for range_type in ['week', 'month', 'year', 'day']:
                        cache.delete(f'dashboard_stats_{range_type}_*')
        except Exception as e:
            logger.warning(f"Cache delete pattern error: {e}")
    
    @staticmethod
    def invalidate_dashboard():
        """Invalidate all dashboard-related cache"""
        CacheService.delete_pattern('dashboard_stats_*')
        CacheService.delete('today_sales_*')
        CacheService.delete('chart_data_*')
        CacheService.delete('refund_stats_*')
        CacheService.delete_pattern('top_products_*')
    
    @staticmethod
    def invalidate_product(product_id=None):
        """Invalidate product-related cache"""
        CacheService.delete_pattern('product_list_*')
        CacheService.delete_pattern('low_stock*')
        CacheService.delete_pattern('top_products_*')
        if product_id:
            CacheService.delete(f'product_detail_{product_id}')


# ============================================
# QUERY OPTIMIZATION
# ============================================

class QueryOptimizer:
    """Optimize database queries with aggressive prefetching and select_related"""
    
    @staticmethod
    def optimize_transaction_queryset(queryset):
        """Optimize transaction queryset with common prefetches"""
        return queryset.select_related(
            'member'
        ).prefetch_related(
            Prefetch(
                'items', 
                queryset=TransactionItem.objects.select_related('product').only(
                    'id', 'transaction_id', 'product_id', 'product_name', 
                    'product_barcode', 'quantity', 'unit_price', 'total_price'
                )
            )
        ).defer('notes')  # Defer large text fields if not needed
    
    @staticmethod
    def optimize_member_queryset(queryset):
        """Optimize member queryset"""
        return queryset.select_related(
            'member_type', 'member_role', 'user'
        ).only(
            'id', 'first_name', 'last_name', 'rfid_card_number', 'email',
            'phone', 'balance', 'member_role_id', 'is_active', 'date_joined',
            'member_type', 'member_role', 'user'
        )
    
    @staticmethod
    def optimize_product_queryset(queryset):
        """Optimize product queryset"""
        return queryset.select_related('category').only(
            'id', 'name', 'barcode', 'price', 'cost', 'stock_quantity',
            'low_stock_threshold', 'is_active', 'category', 'description'
        )
    
    @staticmethod
    def bulk_update_stock(updates: List[Tuple[Product, int]]) -> int:
        """
        Bulk update product stock quantities efficiently
        updates: List of (product, new_quantity) tuples
        Returns number of updates performed
        """
        if not updates:
            return 0
        
        updated_count = 0
        with transaction.atomic():
            for product, new_quantity in updates:
                # Use update() instead of save() for better performance
                affected = Product.objects.filter(id=product.id).update(
                    stock_quantity=new_quantity,
                    updated_at=timezone.now()
                )
                updated_count += affected
        
        # Invalidate product caches
        CacheService.invalidate_product()
        
        return updated_count
    
    @staticmethod
    def get_or_create_member_with_cache(rfid: str) -> Optional[Member]:
        """Get member by RFID with caching"""
        cache_key = CacheKeys.MEMBER_BY_RFID.format(rfid=rfid)
        
        cached_member = CacheService.get(cache_key)
        if cached_member:
            return cached_member
        
        try:
            member = Member.objects.select_related('member_type', 'member_role', 'user').get(
                rfid_card_number=rfid, 
                is_active=True
            )
            CacheService.set(cache_key, member, CacheService.SHORT_TIMEOUT)
            return member
        except Member.DoesNotExist:
            return None


# ============================================
# AGGREGATED DATA SERVICES
# ============================================

class DashboardDataService:
    """Service for efficient dashboard data aggregation with caching"""
    
    def __init__(self, request=None):
        self.request = request
        self.today = timezone.localtime(timezone.now()).date()
    
    def get_dashboard_stats(self, range_type: str = 'month', range_date: str = None) -> Dict:
        """Get cached dashboard statistics"""
        cache_key = CacheKeys.DASHBOARD_STATS.format(
            range=range_type, 
            date=range_date or str(self.today)
        )
        
        cached_data = CacheService.get(cache_key)
        if cached_data:
            return cached_data
        
        # Compute fresh data
        data = self._compute_dashboard_stats(range_type, range_date)
        CacheService.set(cache_key, data, CacheService.DASHBOARD_TIMEOUT)
        
        return data
    
    def _compute_dashboard_stats(self, range_type: str, range_date: str = None) -> Dict:
        """Compute dashboard statistics efficiently using single queries"""
        
        # Define date range based on range_type
        if range_type == 'week':
            # Get week start
            week_start = self.today - timedelta(days=self.today.weekday())
            range_start = week_start
            range_end = self.today
        elif range_type == 'month':
            range_start = self.today.replace(day=1)
            range_end = self.today
        elif range_type == 'year':
            range_start = self.today.replace(month=1, day=1)
            range_end = self.today
        else:  # day
            range_start = self.today
            range_end = self.today
        
        # Convert to datetime for filtering
        start_datetime = timezone.make_aware(datetime.combine(range_start, datetime.min.time()))
        end_datetime = timezone.make_aware(datetime.combine(range_end, datetime.max.time()))
        
        today_start = timezone.make_aware(datetime.combine(self.today, datetime.min.time()))
        today_end = timezone.make_aware(datetime.combine(self.today, datetime.max.time()))
        
        # Base queryset for completed transactions in range
        range_txns = Transaction.objects.filter(
            status='completed',
            created_at__range=(start_datetime, end_datetime)
        )
        
        # Use conditional aggregation for multiple metrics in one query
        stats = range_txns.aggregate(
            total_revenue=Coalesce(Sum('total_amount'), Decimal('0.00')),
            total_transactions=Count('id'),
            avg_transaction=Coalesce(Avg('total_amount'), Decimal('0.00')),
            cash_revenue=Coalesce(Sum('total_amount', filter=Q(payment_method='cash')), Decimal('0.00')),
            debit_revenue=Coalesce(Sum('total_amount', filter=Q(payment_method='debit')), Decimal('0.00')),
            total_vat=Coalesce(Sum('vat_amount'), Decimal('0.00')),
        )
        
        # Today's stats
        today_stats = Transaction.objects.filter(
            status='completed',
            created_at__range=(today_start, today_end)
        ).aggregate(
            today_revenue=Coalesce(Sum('total_amount'), Decimal('0.00')),
            today_transactions=Count('id'),
        )
        
        # Member stats - single query
        member_stats = Member.objects.aggregate(
            total_members=Count('id', filter=Q(is_active=True)),
            total_balance=Coalesce(Sum('balance', filter=Q(is_active=True)), Decimal('0.00')),
            avg_balance=Coalesce(Avg('balance', filter=Q(is_active=True)), Decimal('0.00')),
            active_members=Count('id', filter=Q(is_active=True)),
            inactive_members=Count('id', filter=Q(is_active=False)),
        )
        
        # Product stats - single query
        product_stats = Product.objects.filter(is_active=True).aggregate(
            total_products=Count('id'),
            low_stock=Count('id', filter=Q(stock_quantity__lte=F('low_stock_threshold'), stock_quantity__gt=0)),
            out_of_stock=Count('id', filter=Q(stock_quantity=0)),
            total_stock_value=Coalesce(Sum(F('price') * F('stock_quantity')), Decimal('0.00')),
        )
        
        return {
            'total_revenue': stats['total_revenue'],
            'total_transactions': stats['total_transactions'],
            'avg_transaction': stats['avg_transaction'],
            'cash_revenue': stats['cash_revenue'],
            'debit_revenue': stats['debit_revenue'],
            'total_vat': stats['total_vat'],
            'today_revenue': today_stats['today_revenue'],
            'today_transactions': today_stats['today_transactions'],
            'total_members': member_stats['total_members'],
            'active_members': member_stats['active_members'],
            'inactive_members': member_stats['inactive_members'],
            'total_balance': member_stats['total_balance'],
            'total_products': product_stats['total_products'],
            'low_stock': product_stats['low_stock'],
            'out_of_stock': product_stats['out_of_stock'],
            'total_stock_value': product_stats['total_stock_value'],
        }
    
    def get_chart_data(self, range_type: str, start_date: date, end_date: date) -> Dict:
        """Get chart data optimized with efficient date truncation"""
        cache_key = CacheKeys.CHART_DATA.format(
            range=range_type, 
            start=start_date.isoformat(), 
            end=end_date.isoformat()
        )
        
        cached_data = CacheService.get(cache_key)
        if cached_data:
            return cached_data
        
        data = self._compute_chart_data(range_type, start_date, end_date)
        CacheService.set(cache_key, data, CacheService.DASHBOARD_TIMEOUT)
        
        return data
    
    def _compute_chart_data(self, range_type: str, start_date: date, end_date: date) -> Dict:
        """Compute chart data with optimized queries"""
        
        start_datetime = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
        end_datetime = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))
        
        base_qs = Transaction.objects.filter(
            status='completed',
            created_at__range=(start_datetime, end_datetime)
        )
        
        days_count = (end_date - start_date).days + 1
        
        if days_count > 60:  # For large ranges, use monthly aggregation
            sales_data = list(base_qs.annotate(
                period=TruncMonth('created_at')
            ).values('period').annotate(
                total=Coalesce(Sum('total_amount'), Decimal('0.00'))
            ).order_by('period'))
            
            labels = [item['period'].strftime('%b %Y') for item in sales_data if item['period']]
            totals = [float(item['total']) for item in sales_data]
        else:
            # Use dictionary comprehension for daily aggregation - more efficient
            sales_dict = dict(base_qs.annotate(
                day=TruncDate('created_at')
            ).values_list('day').annotate(
                total=Coalesce(Sum('total_amount'), Decimal('0.00'))
            ))
            
            labels = []
            totals = []
            for i in range(days_count):
                day = start_date + timedelta(days=i)
                labels.append(day.strftime('%b %d'))
                totals.append(float(sales_dict.get(day, Decimal('0.00'))))
        
        return {
            'labels': labels,
            'totals': totals,
        }
    
    def get_top_products(self, limit: int = 10, period_days: int = 30, use_cache: bool = True) -> List[Dict]:
        """Get top selling products with caching"""
        
        if use_cache:
            cache_key = CacheKeys.TOP_PRODUCTS.format(limit=limit, period=period_days)
            cached = CacheService.get(cache_key)
            if cached:
                return cached
        
        # Calculate period start
        period_start = timezone.now() - timedelta(days=period_days)
        
        # Optimized query using values and aggregation
        top_products = TransactionItem.objects.filter(
            transaction__status='completed',
            transaction__created_at__gte=period_start
        ).values(
            'product_id', 'product_name', 'product_barcode'
        ).annotate(
            total_sold=Coalesce(
                Sum('quantity'),
                Value(0, output_field=DecimalField(max_digits=14, decimal_places=3)),
                output_field=DecimalField(max_digits=14, decimal_places=3),
            ),
            total_revenue=Coalesce(Sum('total_price'), Decimal('0.00')),
            transaction_count=Count('transaction_id', distinct=True)
        ).order_by('-total_sold')[:limit]
        
        # Get product details in a separate optimized query
        product_ids = [item['product_id'] for item in top_products if item['product_id']]
        product_details = {}
        
        if product_ids:
            products = Product.objects.filter(id__in=product_ids).only(
                'id', 'stock_quantity', 'price', 'name'
            )
            product_details = {p.id: {'stock': p.stock_quantity, 'price': float(p.price)} for p in products}
        
        results = []
        for item in top_products:
            result = {
                'name': item['product_name'],
                'barcode': item['product_barcode'],
                'total_sold': item['total_sold'],
                'total_revenue': float(item['total_revenue']),
                'transaction_count': item['transaction_count'],
            }
            
            if item['product_id'] and item['product_id'] in product_details:
                details = product_details[item['product_id']]
                result['current_stock'] = details['stock']
                result['current_price'] = details['price']
            
            results.append(result)
        
        if use_cache:
            CacheService.set(cache_key, results, CacheService.STATS_TIMEOUT)
        
        return results
    
    def get_payment_breakdown(self, start_date: date, end_date: date) -> Dict:
        """Get payment method breakdown for date range"""
        
        start_datetime = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
        end_datetime = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))
        
        breakdown = Transaction.objects.filter(
            status='completed',
            created_at__range=(start_datetime, end_datetime)
        ).values('payment_method').annotate(
            total=Coalesce(Sum('total_amount'), Decimal('0.00')),
            count=Count('id')
        ).order_by('-total')
        
        payment_labels = dict(Transaction.PAYMENT_METHODS)
        
        return {
            'labels': [payment_labels.get(item['payment_method'], item['payment_method']) for item in breakdown],
            'totals': [float(item['total']) for item in breakdown],
            'counts': [item['count'] for item in breakdown],
        }


# ============================================
# BACKGROUND TASK HANDLER
# ============================================

class BackgroundTaskManager:
    """Manage background tasks for non-blocking operations"""
    
    @staticmethod
    def run_in_background(func, *args, **kwargs):
        """Run a function in background thread"""
        thread = threading.Thread(target=func, args=args, kwargs=kwargs, daemon=True)
        thread.start()
        return thread
    
    @staticmethod
    def send_email_async(subject: str, body: str, recipient_list: List[str], 
                         attachments: List = None, html_body: str = None):
        """Send email asynchronously"""
        from django.core.mail import EmailMultiAlternatives
        
        def _send():
            try:
                if html_body:
                    email = EmailMultiAlternatives(
                        subject=subject,
                        body=body,
                        to=recipient_list,
                    )
                    email.attach_alternative(html_body, "text/html")
                else:
                    from django.core.mail import EmailMessage
                    email = EmailMessage(
                        subject=subject,
                        body=body,
                        to=recipient_list,
                    )
                
                if attachments:
                    for attachment in attachments:
                        if len(attachment) == 3:
                            email.attach(attachment[0], attachment[1], attachment[2])
                        else:
                            email.attach(*attachment)
                
                email.send(fail_silently=False)
                logger.info(f"Async email sent to {recipient_list}")
            except Exception as e:
                logger.error(f"Async email failed: {e}")
        
        BackgroundTaskManager.run_in_background(_send)
    
    @staticmethod
    def generate_report_async(report_type: str, data: Dict, callback=None):
        """Generate report asynchronously"""
        
        def _generate():
            try:
                from reportlab.lib.pagesizes import A4
                from reportlab.platypus import SimpleDocTemplate
                import io
                
                buffer = io.BytesIO()
                doc = SimpleDocTemplate(buffer, pagesize=A4)
                
                # Report generation logic would go here
                # This is a placeholder for your specific report needs
                
                buffer.seek(0)
                
                if callback:
                    callback(buffer)
            except Exception as e:
                logger.error(f"Async report generation failed: {e}")
        
        BackgroundTaskManager.run_in_background(_generate)


# ============================================
# PAGINATION OPTIMIZER
# ============================================

class OptimizedPaginator(Paginator):
    """Enhanced paginator with count caching and efficient slicing for large datasets"""
    
    def __init__(self, object_list, per_page, orphans=0, allow_empty_first_page=True, cache_count=True):
        super().__init__(object_list, per_page, orphans, allow_empty_first_page)
        self._cached_count = None
        self._cache_count = cache_count
        self._cache_key = None
    
    @property
    def count(self):
        """Get count with optional caching for querysets"""
        if self._cached_count is not None:
            return self._cached_count
        
        # For querysets, use exists() for better performance
        if hasattr(self.object_list, 'exists'):
            try:
                if self.object_list.exists():
                    self._cached_count = self.object_list.count()
                else:
                    self._cached_count = 0
            except Exception:
                self._cached_count = super().count
        else:
            self._cached_count = super().count
        
        return self._cached_count
    
    def page(self, number):
        """Override page method to use optimized slicing"""
        number = self.validate_number(number)
        bottom = (number - 1) * self.per_page
        top = bottom + self.per_page
        
        # Use efficient slicing
        if bottom + self.per_page > self.count and self.orphans:
            top = self.count
        
        page_objects = self.object_list[bottom:top]
        
        from django.core.paginator import Page
        return Page(page_objects, number, self)


# ============================================
# BULK OPERATION UTILITIES
# ============================================

class BulkOperationService:
    """Service for bulk database operations to improve performance"""
    
    @staticmethod
    def bulk_create_balance_transactions(transactions_data: List[Dict]) -> int:
        """Bulk create balance transactions"""
        from django.db import transaction as db_transaction

        def _next_txn_number() -> str:
            for _ in range(16):
                candidate = secrets.token_hex(12).upper()
                if not BalanceTransaction.objects.filter(transaction_number=candidate).exists():
                    return candidate
            raise RuntimeError("Could not allocate a unique balance transaction_number")

        if not transactions_data:
            return 0

        with db_transaction.atomic():
            transactions = []
            for data in transactions_data:
                row = dict(data)
                if not row.get("transaction_number"):
                    row["transaction_number"] = _next_txn_number()
                transactions.append(BalanceTransaction(**row))
            created = BalanceTransaction.objects.bulk_create(transactions)
            return len(created)
    
    @staticmethod
    def bulk_update_member_balances(updates: Dict[int, Decimal]) -> int:
        """Bulk update member balances"""
        from django.db import transaction as db_transaction
        
        updated_count = 0
        with db_transaction.atomic():
            for member_id, new_balance in updates.items():
                affected = Member.objects.filter(id=member_id).update(
                    balance=new_balance,
                    updated_at=timezone.now()
                )
                updated_count += affected
                # Invalidate member cache
                CacheService.delete(f'member_balance_{member_id}')
        
        return updated_count
    
    @staticmethod
    def bulk_create_transactions_with_items(transactions_data: List[Dict]) -> int:
        """
        Bulk create transactions with their items in a single transaction
        transactions_data: List of dicts with 'transaction' and 'items' keys
        """
        from django.db import transaction as db_transaction
        
        created_count = 0
        with db_transaction.atomic():
            # Create all transactions first
            transactions = []
            for data in transactions_data:
                txn_data = data.get('transaction', {})
                transactions.append(Transaction(**txn_data))
            
            created_transactions = Transaction.objects.bulk_create(transactions)
            
            # Create all items
            items = []
            for txn, data in zip(created_transactions, transactions_data):
                for item_data in data.get('items', []):
                    items.append(TransactionItem(
                        transaction=txn,
                        **item_data
                    ))
            
            if items:
                TransactionItem.objects.bulk_create(items)
            
            created_count = len(created_transactions)
            
            # Invalidate caches
            CacheService.invalidate_dashboard()
        
        return created_count


# ============================================
# DECORATORS FOR PERFORMANCE
# ============================================

def cache_query(timeout=300, key_prefix=None, vary_on_args=None):
    """
    Decorator to cache function results
    Usage: @cache_query(timeout=60)
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Build cache key
            if key_prefix:
                cache_key = key_prefix
            else:
                cache_key = func.__name__
            
            # Add args to key if needed
            if vary_on_args:
                for arg_name in vary_on_args:
                    if arg_name in kwargs:
                        cache_key += f"_{arg_name}_{kwargs[arg_name]}"
                for i, arg in enumerate(args):
                    if i < len(vary_on_args):
                        cache_key += f"_{vary_on_args[i]}_{arg}"
            else:
                # Use all args for key
                cache_key += str(args) + str(sorted(kwargs.items()))
            
            # Clean key for cache
            cache_key = cache_key.replace(' ', '_').replace("'", "")
            
            # Try cache
            cached_result = CacheService.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # Execute function
            result = func(*args, **kwargs)
            
            # Cache result
            CacheService.set(cache_key, result, timeout)
            
            return result
        return wrapper
    return decorator


def batch_process(batch_size=100):
    """Decorator to process queryset in batches"""
    def decorator(func):
        @wraps(func)
        def wrapper(queryset, *args, **kwargs):
            results = []
            total = queryset.count() if hasattr(queryset, 'count') else len(queryset)
            
            for start in range(0, total, batch_size):
                end = min(start + batch_size, total)
                if hasattr(queryset, '__getitem__'):
                    batch = queryset[start:end]
                else:
                    batch = list(queryset)[start:end]
                result = func(batch, *args, **kwargs)
                results.append(result)
            
            return results
        return wrapper
    return decorator


# ============================================
# PERFORMANCE MONITORING
# ============================================

class PerformanceMonitor:
    """Context manager to monitor and log query performance"""
    
    def __init__(self, name: str = None, threshold_seconds: float = 0.5):
        self.name = name or "Operation"
        self.threshold_seconds = threshold_seconds
        self.start_time = None
        self.start_queries = None
        self.start_queries_time = None
    
    def __enter__(self):
        self.start_time = timezone.now()
        self.start_queries = len(connection.queries)
        # Reset query time tracking if available
        if hasattr(connection, 'queries'):
            self.start_queries_time = sum(float(q.get('time', 0)) for q in connection.queries)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed = (timezone.now() - self.start_time).total_seconds()
        query_count = len(connection.queries) - self.start_queries
        
        query_time = 0
        if hasattr(connection, 'queries') and self.start_queries_time is not None:
            query_time = sum(float(q.get('time', 0)) for q in connection.queries[self.start_queries:])
        
        if elapsed > self.threshold_seconds:
            logger.warning(
                f"⚠️ PerformanceMonitor: {self.name} took {elapsed:.2f}s "
                f"with {query_count} queries ({query_time:.3f}s query time)"
            )
        else:
            logger.debug(
                f"✅ PerformanceMonitor: {self.name} took {elapsed:.2f}s "
                f"with {query_count} queries"
            )
    
    def get_stats(self) -> Dict:
        """Get current performance stats"""
        return {
            'name': self.name,
            'query_count': len(connection.queries),
            'time_elapsed': (timezone.now() - self.start_time).total_seconds() if self.start_time else 0,
        }


# ============================================
# DATABASE HELPER
# ============================================

class DatabaseHelper:
    """Database connection and query optimization helpers"""
    
    @staticmethod
    def close_old_connections():
        """Close old database connections to prevent memory leaks"""
        from django.db import close_old_connections
        close_old_connections()
    
    @staticmethod
    def get_slow_queries(threshold_ms: int = 100) -> List[Dict]:
        """Get queries that exceed the threshold"""
        slow_queries = []
        for query in connection.queries:
            try:
                duration = float(query.get('time', 0))
                if duration > threshold_ms:
                    slow_queries.append({
                        'sql': query['sql'],
                        'duration_ms': duration,
                        'time': query.get('time'),
                    })
            except (ValueError, TypeError):
                pass
        return slow_queries
    
    @staticmethod
    def explain_query(queryset):
        """Get EXPLAIN output for a queryset to analyze performance"""
        try:
            return str(queryset.query.explain(verbose=True, analyze=True))
        except Exception as e:
            return f"Cannot explain query: {e}"


# ============================================
# CACHE WARMING AND INITIALIZATION
# ============================================

class CacheWarmingService:
    """Service to preload frequently accessed data into cache"""
    
    @staticmethod
    def warmup_dashboard_cache():
        """Preload dashboard data for common ranges"""
        service = DashboardDataService()
        
        # Pre-cache common dashboard stats
        for range_type in ['day', 'week', 'month', 'year']:
            service.get_dashboard_stats(range_type)
        
        # Pre-cache top products
        service.get_top_products(10, 7)  # Last 7 days
        service.get_top_products(10, 30)  # Last 30 days
        
        logger.info("Dashboard caches warmed up")
    
    @staticmethod
    def warmup_lookup_cache():
        """Preload common lookup data"""
        
        # Preload all active categories
        categories = list(Category.objects.filter(is_active=True).values('id', 'name'))
        CacheService.set('all_categories', categories, timeout=3600)
        
        # Preload member types
        member_types = list(MemberType.objects.filter(is_active=True).values('id', 'name'))
        CacheService.set('member_types', member_types, timeout=3600)
        
        # Preload payment method choices
        CacheService.set('payment_methods', dict(Transaction.PAYMENT_METHODS), timeout=86400)
        
        # Preload low stock products count (cached)
        low_stock_count = Product.objects.filter(
            is_active=True, 
            stock_quantity__lte=F('low_stock_threshold')
        ).exclude(stock_quantity=0).count()
        CacheService.set(CacheKeys.LOW_STOCK_COUNT, low_stock_count, CacheService.STATS_TIMEOUT)
        
        out_of_stock_count = Product.objects.filter(is_active=True, stock_quantity=0).count()
        CacheService.set(CacheKeys.OUT_OF_STOCK_COUNT, out_of_stock_count, CacheService.STATS_TIMEOUT)
        
        logger.info("Lookup caches warmed up")


# ============================================
# STREAMING EXPORT HELPER
# ============================================

class StreamingCSVExport:
    """Stream large CSV exports to avoid memory issues"""
    
    def __init__(self, queryset, fields: List[str], headers: List[str] = None, field_labels: Dict = None):
        self.queryset = queryset
        self.fields = fields
        self.headers = headers or fields
        self.field_labels = field_labels or {}
    
    def stream(self, response, filename: str = "export.csv"):
        """Stream CSV data to response"""
        import csv
        
        response['Content-Type'] = 'text/csv'
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        writer = csv.writer(response)
        
        # Write headers with labels if available
        display_headers = []
        for header in self.headers:
            display_headers.append(self.field_labels.get(header, header))
        writer.writerow(display_headers)
        
        # Use iterator() to avoid loading all into memory
        for obj in self.queryset.iterator(chunk_size=500):
            row = []
            for field in self.fields:
                # Handle nested fields (e.g., 'member__full_name')
                if '__' in field:
                    value = obj
                    for part in field.split('__'):
                        if hasattr(value, part):
                            value = getattr(value, part)
                        else:
                            value = ''
                            break
                else:
                    value = getattr(obj, field, '')
                
                # Handle callables
                if callable(value):
                    value = value()
                
                # Format correctly
                if value is None:
                    value = ''
                elif isinstance(value, Decimal):
                    value = f"{value:.2f}"
                elif isinstance(value, datetime):
                    value = value.strftime('%Y-%m-%d %H:%M:%S')
                elif isinstance(value, date):
                    value = value.strftime('%Y-%m-%d')
                
                row.append(str(value))
            
            writer.writerow(row)
        
        return response


# ============================================
# SIGNAL HANDLERS FOR CACHE INVALIDATION
# ============================================

def register_cache_invalidation_signals():
    """Register signal handlers for automatic cache invalidation"""
    from django.db.models.signals import post_save, post_delete
    
    def invalidate_on_product_change(sender, instance, **kwargs):
        CacheService.invalidate_product(instance.id)
        CacheService.invalidate_dashboard()
    
    def invalidate_on_member_change(sender, instance, **kwargs):
        CacheService.delete(CacheKeys.MEMBER_BY_RFID.format(rfid=instance.rfid_card_number))
        CacheService.delete(f'member_balance_{instance.id}')
        CacheService.delete_pattern('member_list_*')
    
    def invalidate_on_transaction_change(sender, instance, **kwargs):
        CacheService.invalidate_dashboard()
        CacheService.delete_pattern('dashboard_stats_*')
        CacheService.delete_pattern('chart_data_*')
    
    # Connect signals
    post_save.connect(invalidate_on_product_change, sender=Product)
    post_delete.connect(invalidate_on_product_change, sender=Product)
    post_save.connect(invalidate_on_member_change, sender=Member)
    post_delete.connect(invalidate_on_member_change, sender=Member)
    post_save.connect(invalidate_on_transaction_change, sender=Transaction)
    
    logger.info("Cache invalidation signals registered")


# ============================================
# INITIALIZATION FUNCTION
# ============================================

def initialize_performance_helpers(warmup_cache: bool = True):
    """
    Initialize all performance helpers
    Call this in your AppConfig.ready() or at the end of settings.py
    """
    logger.info("Initializing performance helpers...")
    
    # Register cache invalidation signals
    register_cache_invalidation_signals()
    
    # Warm up caches if requested
    if warmup_cache and not getattr(settings, 'DEBUG', False):
        CacheWarmingService.warmup_lookup_cache()
        CacheWarmingService.warmup_dashboard_cache()
    
    logger.info("Performance helpers initialized successfully")