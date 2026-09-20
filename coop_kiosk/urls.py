"""
URL configuration for coop_kiosk project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import render
from django.views.generic import RedirectView
from kiosk import views as kiosk_views
from admin_panel import views as admin_panel_views
from admin_panel.data_transfer_views import get_data_transfer_urls
from members import views as members_views
from loans.views import LoanSettingsView


def handler404(request, exception=None):
    """Custom 404 error handler"""
    return render(request, '404.html', status=404)


def catchall_404(request, **kwargs):
    """Wrapper function for catch-all route that accepts any path parameter"""
    return handler404(request)

urlpatterns = [
    # Custom admin URLs must come before admin.site.urls to take precedence
    path('admin/login/', admin_panel_views.redirect_to_root_login, name='admin_login'),
    path('admin/logout/', admin_panel_views.admin_logout, name='admin_logout'),
    *get_data_transfer_urls(),
    path('admin/', admin.site.urls),
    path('', admin_panel_views.root_login, name='root_login'),
    path('kiosk/', kiosk_views.kiosk_home, name='kiosk_home'),
    path('kiosk/browse/', kiosk_views.kiosk_browse_products, name='kiosk_browse_products'),
    path('api/scan-product/', kiosk_views.scan_product, name='scan_product'),
    path('api/search-products/', kiosk_views.search_products, name='search_products'),
    path('api/products/', kiosk_views.get_all_products, name='get_all_products'),
    path('api/kiosk/quote-cart/', kiosk_views.api_quote_cart_lines, name='api_quote_cart_lines'),
    path(
        'api/kiosk/product-sale-units/',
        kiosk_views.api_kiosk_product_sale_units,
        name='api_kiosk_product_sale_units',
    ),
    path(
        'api/kiosk/select-sale-unit/',
        kiosk_views.api_kiosk_select_sale_unit,
        name='api_kiosk_select_sale_unit',
    ),
    path(
        'api/kiosk/update-cart-quantity/',
        kiosk_views.api_kiosk_update_cart_quantity,
        name='api_kiosk_update_cart_quantity',
    ),
    path('api/scan-rfid/', kiosk_views.scan_rfid, name='scan_rfid'),
    path('api/kiosk/search-members/', kiosk_views.api_kiosk_search_members, name='api_kiosk_search_members'),
    path('api/kiosk/attach-member/', kiosk_views.api_kiosk_attach_member, name='api_kiosk_attach_member'),
    path('api/member-credit/', kiosk_views.api_member_credit, name='api_member_credit'),
    path(
        'api/walk-in-customer-names/',
        kiosk_views.api_walk_in_customer_names,
        name='api_walk_in_customer_names',
    ),
    path('api/process-payment/', kiosk_views.process_payment, name='process_payment'),
    path('api/print-receipt-local/', kiosk_views.print_receipt_local, name='print_receipt_local'),
    path('api/kiosk/toggle-tax/', kiosk_views.api_kiosk_toggle_tax, name='api_kiosk_toggle_tax'),
    path('api/kiosk/tax-rate/', kiosk_views.api_kiosk_tax_rate, name='api_kiosk_tax_rate'),
    # RFID pre-login gate
    path('rfid-gate/', members_views.rfid_gate, name='rfid_gate'),
    path('api/rfid-validate-login/', members_views.api_validate_rfid_login, name='api_rfid_validate_login'),
    path('kiosk/logout/', admin_panel_views.kiosk_logout, name='kiosk_logout'),
    path('dashboard/', admin_panel_views.dashboard, name='dashboard'),
    path('dashboard/loans/', admin_panel_views.loans_overview, name='loans_overview'),
    path('dashboard/loans/settings/', LoanSettingsView.as_view(), name='loan_settings'),
    path('dashboard/savings/', include('savings.urls')),
    path('dashboard/share-capital/', include('share_capital.urls')),
    path('dashboard/palay/', include('palay_trade.urls')),
    path('api/dashboard/period-data/', admin_panel_views.api_dashboard_period_data, name='api_dashboard_period_data'),
    path(
        'admin/inventory/',
        RedirectView.as_view(url='/dashboard/inventory/', permanent=False),
        name='admin_inventory_redirect',
    ),
    path('dashboard/inventory/', admin_panel_views.inventory_management, name='inventory_management'),
    path(
        'api/inventory/send-stock-alerts/',
        admin_panel_views.api_send_inventory_stock_alerts,
        name='api_send_inventory_stock_alerts',
    ),
    # Per-product stock change history (old/new stock, sold qty) for the History modal
    path(
        'api/inventory/product/<int:product_id>/stock-history/',
        admin_panel_views.api_product_stock_history,
        name='api_product_stock_history',
    ),
    # Product buying/selling price inventory report (PDF + Excel)
    path(
        'dashboard/inventory/export-price-report/',
        admin_panel_views.export_inventory_price_report,
        name='export_inventory_price_report',
    ),
    # Purchase / restock history split by buying price (all products)
    path(
        'dashboard/inventory/export-purchase-history/',
        admin_panel_views.export_inventory_purchase_history,
        name='export_inventory_purchase_history',
    ),
    # Per-product purchase history download (History modal)
    path(
        'dashboard/inventory/product/<int:product_id>/export-purchase-history/',
        admin_panel_views.export_product_purchase_history,
        name='export_product_purchase_history',
    ),
    path(
        'dashboard/inventory/discounts/',
        admin_panel_views.inventory_discount_dashboard,
        name='inventory_discount_dashboard',
    ),
    path(
        'api/inventory/manual-discount-period/',
        admin_panel_views.api_inventory_manual_discount_period,
        name='api_inventory_manual_discount_period',
    ),
    path(
        'dashboard/inventory/discounts/export/',
        admin_panel_views.export_inventory_manual_discount_report,
        name='export_inventory_manual_discount_report',
    ),
    path('dashboard/members/', admin_panel_views.member_management, name='member_management'),
    path('dashboard/members/credit-history/', admin_panel_views.credit_unpaid_history, name='credit_unpaid_history'),
    path('dashboard/members/backup/', admin_panel_views.backup_members_data, name='backup_members_data'),
    path('dashboard/members/restore/', admin_panel_views.restore_members_data, name='restore_members_data'),
    path('dashboard/transactions/', admin_panel_views.transaction_history, name='transaction_history'),
    path(
        'dashboard/transactions/export/',
        admin_panel_views.export_transaction_history,
        name='export_transaction_history',
    ),
    path(
        'api/mark-balance-refills-seen/',
        admin_panel_views.api_mark_balance_refills_seen,
        name='api_mark_balance_refills_seen',
    ),
    path('api/search-members/', admin_panel_views.api_search_members, name='api_search_members'),
    path('api/members/generate-username/', admin_panel_views.api_generate_username, name='api_generate_username'),
    path('api/members/create/', admin_panel_views.api_create_member, name='api_create_member'),
    path('api/members/update/', admin_panel_views.api_update_member, name='api_update_member'),
    path('api/members/verify-edit-pin/', admin_panel_views.api_verify_member_edit_pin, name='api_verify_member_edit_pin'),
    path('api/members/reset-pin-attempts/', admin_panel_views.api_reset_pin_attempts, name='api_reset_pin_attempts'),
    path('api/members/last-edit/', admin_panel_views.api_get_member_last_edit, name='api_get_member_last_edit'),
    path('api/members/restore-last-edit/', admin_panel_views.api_restore_member_last_edit, name='api_restore_member_last_edit'),
    path('api/members/restore-all-last-edit/', admin_panel_views.api_restore_all_last_edit, name='api_restore_all_last_edit'),
    path('api/member-types/create/', admin_panel_views.api_create_member_type, name='api_create_member_type'),
    path('api/member-types/update/', admin_panel_views.api_update_member_type, name='api_update_member_type'),
    path('api/products/generate-barcode/', admin_panel_views.api_generate_barcode, name='api_generate_barcode'),
    path(
        'api/products/generate-wholesale-barcode/',
        admin_panel_views.api_generate_wholesale_barcode,
        name='api_generate_wholesale_barcode',
    ),
    path('api/products/create/', admin_panel_views.api_create_product, name='api_create_product'),
    path('api/products/update/', admin_panel_views.api_update_product, name='api_update_product'),
    path('api/products/delete/', admin_panel_views.api_delete_product, name='api_delete_product'),
    path('api/products/search-giveaway/', admin_panel_views.api_search_giveaway_products, name='api_search_giveaway_products'),
    path('api/products/record-giveaway/', admin_panel_views.api_record_giveaway, name='api_record_giveaway'),
    path('api/giveaways/list/', admin_panel_views.api_list_giveaways, name='api_list_giveaways'),
    path('api/giveaways/update/', admin_panel_views.api_update_giveaway, name='api_update_giveaway'),
    path('api/giveaways/delete/', admin_panel_views.api_delete_giveaway, name='api_delete_giveaway'),
    path('api/categories/create/', admin_panel_views.api_create_category, name='api_create_category'),
    path('api/categories/update/', admin_panel_views.api_update_category, name='api_update_category'),
    path('api/refill-balance/', admin_panel_views.api_refill_balance, name='api_refill_balance'),
    path('api/kiosk/credit-limit/', admin_panel_views.api_kiosk_credit_limit, name='api_kiosk_credit_limit'),
    path('api/credit/settings/', admin_panel_views.api_credit_settings, name='api_credit_settings'),
    path('api/members/credit-details/', admin_panel_views.api_member_credit_details, name='api_member_credit_details'),
    path('api/members/pay-credit/', admin_panel_views.api_pay_member_credit, name='api_pay_member_credit'),
    path(
        'api/reverse-balance-refill/',
        admin_panel_views.api_reverse_balance_refill,
        name='api_reverse_balance_refill',
    ),
    path('api/rfid-login/', admin_panel_views.api_rfid_login, name='api_rfid_login'),
    path('user-choice/', admin_panel_views.user_choice, name='user_choice'),
    path('user-transactions/', admin_panel_views.user_transactions, name='user_transactions'),
    path('member/loans/', include('loans.member_urls')),
    path('member/savings/', include('savings.member_urls')),
    path('member/palay/', include('palay_trade.member_urls')),
    path('process-refund/', admin_panel_views.process_refund, name='process_refund'),
    path('api/search-transactions-for-refund/', admin_panel_views.api_search_transactions_for_refund, name='api_search_transactions_for_refund'),
    path('api/process-refund/', admin_panel_views.api_process_refund, name='api_process_refund'),
    path('api/search-transactions/', admin_panel_views.api_search_transactions, name='api_search_transactions'),
    path('api/get-transaction/<int:transaction_id>/', admin_panel_views.api_get_transaction, name='api_get_transaction'),
    path('api/void-transaction-item/', admin_panel_views.api_void_transaction_item, name='api_void_transaction_item'),
    path('api/update-transaction/', admin_panel_views.api_update_transaction, name='api_update_transaction'),
    path('api/delete-transaction/', admin_panel_views.api_delete_transaction, name='api_delete_transaction'),
    path('api/confirm-return/', admin_panel_views.api_confirm_return, name='api_confirm_return'),
    path('api/expire-return-window/', admin_panel_views.api_expire_return_window, name='api_expire_return_window'),
    path('refund-receipt/<int:transaction_id>/', admin_panel_views.view_refund_receipt, name='view_refund_receipt'),
    path('cash-receipt/<int:transaction_id>/', admin_panel_views.view_cash_receipt, name='view_cash_receipt'),
    path('debit-credit-receipt/<int:transaction_id>/', admin_panel_views.view_debit_credit_receipt, name='view_debit_credit_receipt'),
    path('credit-receipt/<int:transaction_id>/', admin_panel_views.view_credit_receipt, name='view_credit_receipt'),
    path(
        'credit-payment-receipt/<int:payment_id>/',
        admin_panel_views.view_credit_payment_receipt,
        name='view_credit_payment_receipt',
    ),
    path('dashboard/staff-sales/', admin_panel_views.staff_sales_report, name='staff_sales_report'),
    path('dashboard/staff-sales/export/', admin_panel_views.export_staff_sales_overview, name='export_staff_sales_overview'),
    path('dashboard/staff-sales/<int:member_id>/', admin_panel_views.staff_sales_detail, name='staff_sales_detail'),
    path(
        'dashboard/staff-sales/<int:member_id>/export/',
        admin_panel_views.export_staff_sales_detail,
        name='export_staff_sales_detail',
    ),
    path('dashboard/audit/', admin_panel_views.website_audit_trail, name='website_audit_trail'),
    path('dashboard/generate-report/', admin_panel_views.generate_daily_report_pdf, name='generate_daily_report_pdf'),
    path('dashboard/inventory/download-barcodes/', admin_panel_views.download_product_barcodes_pdf, name='download_product_barcodes_pdf'),
    # Mobile API endpoints
    path('api/mobile/', include('mobile_api.urls')),
    # High-throughput ingestion pipeline
    path('api/ingest/', include('ingestion.urls')),
    # Cooperative loan pipeline (13-step credit workflow + official receipts)
    path('dashboard/loans/steps/', include('loans.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # Catch-all route for 404 errors in DEBUG mode
    # This ensures custom 404.html is shown even when DEBUG=True
    urlpatterns += [
        path('<path:path>', catchall_404, name='404_catchall'),
    ]

# Custom 404 handler - Django will automatically use this
# The handler404 variable must be defined at the module level
