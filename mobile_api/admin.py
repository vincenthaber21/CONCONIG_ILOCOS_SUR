from django.contrib import admin
from import_export.admin import ExportMixin, ImportExportModelAdmin

from .models import FundTransferOTP, MemberQRCode, QRFeatureSettings
from .resources import (
    FundTransferOTPResource,
    MemberQRCodeResource,
    QRFeatureSettingsResource,
)


@admin.register(FundTransferOTP)
class FundTransferOTPAdmin(ExportMixin, admin.ModelAdmin):
    resource_classes = [FundTransferOTPResource]
    list_display = ['member', 'recipient_rfid', 'amount', 'otp_code', 'is_used', 'created_at', 'expires_at']
    list_filter = ['is_used', 'created_at', 'expires_at']
    search_fields = ['member__first_name', 'member__last_name', 'member__rfid_card_number', 'recipient_rfid', 'otp_code']
    readonly_fields = ['otp_code', 'created_at', 'expires_at', 'verified_at']
    ordering = ['-created_at']

    fieldsets = (
        ('Transfer Information', {
            'fields': ('member', 'recipient_rfid', 'amount', 'notes')
        }),
        ('OTP Information', {
            'fields': ('otp_code', 'is_used', 'created_at', 'expires_at', 'verified_at')
        }),
    )


@admin.register(QRFeatureSettings)
class QRFeatureSettingsAdmin(ImportExportModelAdmin):
    """Singleton admin — only one row is ever created."""
    resource_classes = [QRFeatureSettingsResource]
    list_display = ['is_enabled', 'max_transfer_amount', 'qr_token_regenerate_on_use', 'updated_at']
    readonly_fields = ['created_at', 'updated_at']

    fieldsets = (
        ('Feature Toggle', {
            'fields': ('is_enabled',),
            'description': 'Globally enable or disable the QR Transfer feature across the mobile app.',
        }),
        ('Transfer Limits', {
            'fields': ('max_transfer_amount',),
        }),
        ('Security', {
            'fields': ('qr_token_regenerate_on_use',),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    def has_add_permission(self, request):
        # Only allow adding if no row exists yet (singleton)
        return not QRFeatureSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False  # Never delete the settings row


@admin.register(MemberQRCode)
class MemberQRCodeAdmin(ExportMixin, admin.ModelAdmin):
    resource_classes = [MemberQRCodeResource]
    list_display = [
        'member', 'short_token', 'is_active', 'scan_count', 'last_scanned_at', 'created_at',
    ]
    list_filter = ['is_active', 'created_at']
    search_fields = [
        'member__first_name', 'member__last_name', 'member__rfid_card_number', 'qr_token',
    ]
    readonly_fields = ['qr_token', 'scan_count', 'last_scanned_at', 'created_at', 'updated_at']
    ordering = ['member__first_name', 'member__last_name']
    actions = ['regenerate_tokens', 'activate_qr', 'deactivate_qr']

    fieldsets = (
        ('Member', {
            'fields': ('member', 'is_active'),
        }),
        ('QR Token', {
            'fields': ('qr_token',),
            'description': (
                'This UUID is embedded in the member\'s QR code. '
                'Use the "Regenerate tokens" action to issue a new token, '
                'which invalidates any previously printed QR codes.'
            ),
        }),
        ('Usage Stats', {
            'fields': ('scan_count', 'last_scanned_at'),
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',),
        }),
    )

    @admin.display(description='Token (short)')
    def short_token(self, obj):
        return str(obj.qr_token)[:8] + '…'

    @admin.action(description='Regenerate QR token (invalidates existing QR codes)')
    def regenerate_tokens(self, request, queryset):
        count = 0
        for qr in queryset:
            qr.regenerate_token()
            count += 1
        self.message_user(request, f'{count} QR token(s) regenerated.')

    @admin.action(description='Activate QR transfer for selected members')
    def activate_qr(self, request, queryset):
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} QR code(s) activated.')

    @admin.action(description='Deactivate QR transfer for selected members')
    def deactivate_qr(self, request, queryset):
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} QR code(s) deactivated.')
