"""Import/export for mobile API admin models."""

from import_export import resources

from .models import FundTransferOTP, MemberQRCode, QRFeatureSettings


class FundTransferOTPResource(resources.ModelResource):
    class Meta:
        model = FundTransferOTP
        fields = (
            'id',
            'member',
            'recipient_rfid',
            'amount',
            'otp_code',
            'is_used',
            'created_at',
            'expires_at',
            'verified_at',
        )
        export_order = fields
        import_id_fields = ('id',)


class MemberQRCodeResource(resources.ModelResource):
    class Meta:
        model = MemberQRCode
        fields = (
            'id',
            'member',
            'qr_token',
            'is_active',
            'scan_count',
            'last_scanned_at',
            'created_at',
        )
        export_order = fields
        import_id_fields = ('id',)


class QRFeatureSettingsResource(resources.ModelResource):
    class Meta:
        model = QRFeatureSettings
        fields = (
            'id',
            'is_enabled',
            'max_transfer_amount',
            'qr_token_regenerate_on_use',
            'updated_at',
        )
        export_order = fields
        import_id_fields = ('id',)
