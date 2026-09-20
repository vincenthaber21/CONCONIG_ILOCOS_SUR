from django.urls import path
from . import views

app_name = 'mobile_api'

urlpatterns = [
    path('health/', views.health_check, name='health_check'),
    path('login/', views.mobile_login, name='mobile_login'),
    path('logout/', views.mobile_logout, name='mobile_logout'),
    path('account/', views.account_info, name='account_info'),
    path('account/summary/', views.account_summary, name='account_summary'),
    path('transactions/', views.transaction_history, name='transaction_history'),
    path('balance-transactions/', views.balance_transactions, name='balance_transactions'),
    path('search-member/', views.search_member, name='search_member'),
    path('fund-transfer/request-otp/', views.request_transfer_otp, name='request_transfer_otp'),
    path('fund-transfer/verify-otp/', views.verify_transfer_otp, name='verify_transfer_otp'),
    path('biometric/request-otp/', views.request_biometric_otp, name='request_biometric_otp'),
    path('biometric/verify-otp/', views.verify_biometric_otp, name='verify_biometric_otp'),
    path('admin/reset-pin-lockout/', views.reset_pin_lockout, name='reset_pin_lockout'),
    path('products/', views.product_list, name='product_list'),
    path('store-info/', views.store_info, name='store_info'),
    path('admin/important-details/', views.admin_important_details, name='admin_important_details'),
    path('admin/checkout-queue-status/', views.admin_checkout_queue_status, name='admin_checkout_queue_status'),
    path('admin/operational-watchlist/', views.admin_operational_watchlist, name='admin_operational_watchlist'),
    # QR Transfer
    path('qr/my-code/', views.my_qr_code, name='my_qr_code'),
    path('qr/scan/', views.scan_qr_code, name='scan_qr_code'),
    path('qr/regenerate/', views.regenerate_my_qr, name='regenerate_my_qr'),
    # Refund
    path('transactions/request-refund/', views.request_refund, name='request_refund'),
]

