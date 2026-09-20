"""Import/export resources for admin_panel config models (store logo, kiosk, etc.)."""

from import_export import resources

from .models import (
    KioskConfig,
    KioskSessionConfig,
    PrinterSettings,
    ReportScheduleConfig,
    SentDailyReport,
    StoreProfile,
)


class StoreProfileResource(resources.ModelResource):
    """Includes logo path; binary file is packed under media/ in the ZIP."""

    class Meta:
        model = StoreProfile
        fields = (
            'id',
            'store_name',
            'show_store_name',
            'branch_name',
            'address_line1',
            'address_line2',
            'city',
            'province',
            'zip_code',
            'contact_number',
            'alt_contact_number',
            'email',
            'website',
            'business_hours',
            'maps_url',
            'latitude',
            'longitude',
            'tagline',
            'logo',
        )
        export_order = fields
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True

    def before_import_row(self, row, **kwargs):
        for key in (
            'logo',
            'maps_url',
            'branch_name',
            'tagline',
            'email',
            'website',
            'address_line1',
            'address_line2',
            'city',
            'province',
            'zip_code',
            'contact_number',
            'alt_contact_number',
            'business_hours',
        ):
            if key in row and row[key] is None:
                row[key] = ''
        for key in ('latitude', 'longitude'):
            if key in row and (row[key] is None or str(row[key]).strip() == ''):
                row[key] = None


class KioskConfigResource(resources.ModelResource):
    class Meta:
        model = KioskConfig
        exclude = ('updated_at',)
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True


class KioskSessionConfigResource(resources.ModelResource):
    class Meta:
        model = KioskSessionConfig
        exclude = ('updated_at',)
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True


class PrinterSettingsResource(resources.ModelResource):
    class Meta:
        model = PrinterSettings
        exclude = ('updated_at',)
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True


class ReportScheduleConfigResource(resources.ModelResource):
    class Meta:
        model = ReportScheduleConfig
        fields = (
            'id',
            'send_time',
            'is_enabled',
            'refund_window_days',
            'return_window_days',
        )
        export_order = fields
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True


class SentDailyReportResource(resources.ModelResource):
    class Meta:
        model = SentDailyReport
        fields = ('id', 'report_date', 'recipient_email', 'sent_at')
        export_order = fields
        import_id_fields = ('id',)
        skip_unchanged = True
        report_skipped = True
