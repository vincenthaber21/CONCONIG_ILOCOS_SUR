from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse
from django.contrib import messages
from django import forms
from django.utils.html import format_html
from .models import (
    SentDailyReport,
    ReportScheduleConfig,
    StoreProfile,
    KioskConfig,
    CreditSettings,
    KioskSessionConfig,
    PrinterSettings,
    WebsiteAuditLog,
)


class SecureAdminSite(admin.AdminSite):
    """Custom admin site that enforces authentication and admin user verification"""
    
    def has_permission(self, request):
        """
        Check if the user has permission to access the admin site.
        Only superusers and members with admin role can access Django admin.
        Staff users (is_staff but not superuser) and Member role 'staff' are NOT allowed.
        """
        if not request.user.is_authenticated:
            return False
        
        # Import here to avoid circular imports
        from admin_panel.views import can_access_django_admin
        return can_access_django_admin(request.user)
    
    def admin_view(self, view, cacheable=False):
        """
        Override admin_view to add authentication check and redirect to login if needed.
        """
        def inner(request, *args, **kwargs):
            # Check if user is authenticated
            if not request.user.is_authenticated:
                messages.warning(request, 'Please log in to access the admin panel.')
                login_url = reverse('root_login')
                next_url = request.get_full_path()
                return redirect(f'{login_url}?next={next_url}')
            
            # Check if user has admin permissions
            if not self.has_permission(request):
                messages.error(request, 'You do not have permission to access the admin panel.')
                return redirect('root_login')
            
            # Call the original view
            return view(request, *args, **kwargs)
        
        return inner


# Override the default admin site to add authentication check
class SecureDefaultAdminSite(admin.AdminSite):
    """Wrapper around default admin site that adds authentication verification"""
    
    def has_permission(self, request):
        """Check if user is authenticated and can access Django admin"""
        if not request.user.is_authenticated:
            return False
        
        # Import here to avoid circular imports
        from admin_panel.views import can_access_django_admin
        return can_access_django_admin(request.user)
    
    def admin_view(self, view, cacheable=False):
        """Override admin_view to add authentication check"""
        def inner(request, *args, **kwargs):
            # Check if user is authenticated
            if not request.user.is_authenticated:
                messages.warning(request, 'Please log in to access the admin panel.')
                login_url = reverse('root_login')
                next_url = request.get_full_path()
                return redirect(f'{login_url}?next={next_url}')
            
            # Check if user has admin permissions
            if not self.has_permission(request):
                messages.error(request, 'You do not have permission to access the admin panel.')
                return redirect('root_login')
            
            # Call the original view from default admin site
            return view(request, *args, **kwargs)
        
        return inner


# Create secure admin site instance
secure_admin_site = SecureAdminSite(name='secure_admin')

# Register models with the secure admin site
@admin.register(SentDailyReport, site=secure_admin_site)
class SentDailyReportAdmin(admin.ModelAdmin):
    list_display = ('report_date', 'recipient_email', 'sent_at')
    list_filter = ('report_date', 'recipient_email', 'sent_at')
    search_fields = ('recipient_email',)
    readonly_fields = ('sent_at',)
    date_hierarchy = 'report_date'
    
    def has_add_permission(self, request):
        # Prevent manual creation - reports should only be created when sent
        return False
    
    def has_change_permission(self, request, obj=None):
        # Prevent editing - sent reports should be immutable
        return False


@admin.register(ReportScheduleConfig, site=secure_admin_site)
class ReportScheduleConfigAdmin(admin.ModelAdmin):
    """
    Singleton admin for configuring the automatic daily report schedule.
    Admins can set the hour/minute and enable or disable the job.
    Saving the form immediately reschedules (or removes) the APScheduler job.
    """

    readonly_fields = ('next_run_display', 'updated_at')

    def get_fieldsets(self, request, obj=None):
        kiosk_url = reverse('admin:admin_panel_kiosksessionconfig_change', args=[1])
        schedule_intro = format_html(
            '<p class="help"><strong>Kiosk idle logout</strong> is not on this page. '
            'Configure minutes until automatic logout on <code>/kiosk/</code> in '
            '<a href="{}">Kiosk Session Config</a> (enable/disable, inactivity minutes, warning seconds).</p>'
            '<p>Set the time for the automatic daily report to be sent every day. '
            'Changes take effect immediately — no server restart required.</p>',
            kiosk_url,
        )
        return (
            ('Schedule Settings', {
                'description': schedule_intro,
                'fields': ('is_enabled', 'send_time'),
            }),
            ('Refund Policy', {
                'description': (
                    'Set how many days after purchase a customer is allowed to request a refund. '
                    'Example: 1 = within 24 hours, 3 = within 3 days.'
                ),
                'fields': ('refund_window_days',),
            }),
            ('Item Return Policy', {
                'description': (
                    'Set how many days a member has to physically return the purchased item(s) after a refund is approved. '
                    'The refund money is only credited once you confirm the item has been received. '
                    'If the item is not returned within this period, the refund is automatically voided. '
                    'Example: 3 = 3 days to return the item.'
                ),
                'fields': ('return_window_days',),
            }),
            ('Status', {
                'fields': ('next_run_display', 'updated_at'),
            }),
        )

    def next_run_display(self, obj):
        """Show the next scheduled run time from APScheduler."""
        try:
            from admin_panel.scheduler import scheduler
            if scheduler is None or not scheduler.running:
                return format_html('<span style="color:red;">Scheduler not running</span>')
            job = scheduler.get_job('send_daily_report')
            if job is None:
                return format_html('<span style="color:orange;">Job not scheduled (report sending is disabled)</span>')
            next_run = job.next_run_time
            if next_run:
                return format_html(
                    '<strong style="color:green;">{}</strong>',
                    next_run.strftime('%Y-%m-%d %H:%M:%S %Z')
                )
            return 'N/A'
        except Exception as e:
            return f'Error: {e}'

    next_run_display.short_description = 'Next Scheduled Run'

    def has_add_permission(self, request):
        # Only one config record should ever exist
        return not ReportScheduleConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        """Redirect the list view straight to the single config object."""
        config = ReportScheduleConfig.get()
        return redirect(
            reverse('admin:admin_panel_reportscheduleconfig_change', args=[config.pk])
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        # Reschedule the APScheduler job immediately after saving
        try:
            from admin_panel.scheduler import scheduler, send_daily_report
            from apscheduler.triggers.cron import CronTrigger

            if scheduler is None or not scheduler.running:
                messages.warning(
                    request,
                    'Config saved, but the scheduler is not running. '
                    'Restart the server to apply the new schedule.'
                )
                return

            if obj.is_enabled:
                scheduler.add_job(
                    send_daily_report,
                    trigger=CronTrigger(hour=obj.send_time.hour, minute=obj.send_time.minute),
                    id='send_daily_report',
                    name=f'Send Daily Report at {obj.send_time.strftime("%I:%M %p")}',
                    replace_existing=True,
                    max_instances=1,
                    misfire_grace_time=3600,
                    coalesce=True,
                )
                messages.success(
                    request,
                    f'Daily report rescheduled to run at {obj.send_time.strftime("%I:%M %p")} every day.'
                )
            else:
                # Remove the job when disabled
                if scheduler.get_job('send_daily_report'):
                    scheduler.remove_job('send_daily_report')
                messages.warning(request, 'Automatic daily report has been DISABLED.')
        except Exception as e:
            messages.error(request, f'Config saved but failed to reschedule: {e}')


# Also register with the default admin.site so it appears at /admin/
admin.site.register(ReportScheduleConfig, ReportScheduleConfigAdmin)
admin.site.register(SentDailyReport, SentDailyReportAdmin)


@admin.register(StoreProfile, site=secure_admin_site)
class StoreProfileAdmin(admin.ModelAdmin):
    fieldsets = (
        ('Store Identity', {
            'description': 'Basic store / business information shown in the mobile app.',
            'fields': ('store_name', 'show_store_name', 'branch_name', 'tagline', 'logo'),
        }),
        ('Location', {
            'fields': ('address_line1', 'address_line2', 'city', 'province', 'zip_code', 'maps_url', 'latitude', 'longitude'),
        }),
        ('Contact Details', {
            'fields': ('contact_number', 'alt_contact_number', 'email', 'website'),
        }),
        ('Operations', {
            'fields': ('business_hours',),
        }),
        ('Metadata', {
            'fields': ('updated_at',),
            'classes': ('collapse',),
        }),
    )
    readonly_fields = ('updated_at', 'latitude', 'longitude')

    def has_add_permission(self, request):
        return not StoreProfile.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        profile = StoreProfile.get()
        return redirect(
            reverse('admin:admin_panel_storeprofile_change', args=[profile.pk])
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if obj.latitude and obj.longitude:
            messages.success(
                request,
                f'Store profile updated. Coordinates auto-extracted: '
                f'lat {obj.latitude}, lng {obj.longitude}.'
            )
        else:
            if obj.maps_url:
                messages.warning(
                    request,
                    'Store profile saved but coordinates could not be extracted from the Maps URL. '
                    'Make sure the URL is a full Google Maps place or directions link.'
                )
            else:
                messages.success(request, 'Store profile updated successfully.')


admin.site.register(StoreProfile, StoreProfileAdmin)


@admin.register(KioskConfig, site=secure_admin_site)
class KioskConfigAdmin(admin.ModelAdmin):
    fieldsets = (
        ('Kiosk Display', {
            'description': 'Configure the name and tagline shown in the kiosk header, page title, and receipts.',
            'fields': ('system_name', 'tagline', 'admin_dashboard_description'),
        }),
        ('Receipt Header', {
            'description': 'Store information printed at the top of every receipt (on-screen and printed).',
            'fields': (
                'receipt_header_store_name',
                'receipt_header_store_description',
                'receipt_header_address',
                'receipt_header_phone',
            ),
        }),
        ('Receipt Content', {
            'description': 'Text printed on every transaction receipt (on-screen, print, and plain-text versions).',
            'fields': ('receipt_subtitle', 'receipt_thank_you', 'receipt_footer_customer_tagline', 'receipt_footer_merchant_note'),
        }),
        ('Tax Settings', {
            'description': (
                'Enable or disable VAT/tax calculation for the entire kiosk. '
                'When disabled, tax is not computed, not displayed on the kiosk, '
                'and not stored on new transactions.'
            ),
            'fields': ('tax_enabled',),
        }),
        ('Metadata', {
            'fields': ('updated_at',),
            'classes': ('collapse',),
        }),
    )
    readonly_fields = ('updated_at',)

    def has_add_permission(self, request):
        return not KioskConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        config = KioskConfig.get()
        return redirect(
            reverse('admin:admin_panel_kioskconfig_change', args=[config.pk])
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        messages.success(request, 'Kiosk configuration updated successfully.')


admin.site.register(KioskConfig, KioskConfigAdmin)


@admin.register(CreditSettings, site=secure_admin_site)
class CreditSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        ('Credit Interest (Utang)', {
            'description': (
                'After the grace period, each unpaid month adds principal × rate. '
                'Example: ₱500 → ₱507.50 (month 1); month 2 adds another ₱7.50 → ₱515. '
                'You can also edit these from Members → Credit Interest Settings.'
            ),
            'fields': ('is_enabled', 'interest_rate', 'grace_period_days'),
        }),
        ('Metadata', {
            'fields': ('updated_at',),
            'classes': ('collapse',),
        }),
    )
    readonly_fields = ('updated_at',)

    def has_add_permission(self, request):
        return not CreditSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        config = CreditSettings.get()
        return redirect(
            reverse('admin:admin_panel_creditsettings_change', args=[config.pk])
        )

    def save_model(self, request, obj, form, change):
        if obj.interest_rate is not None and obj.interest_rate <= 0:
            obj.is_enabled = False
        super().save_model(request, obj, form, change)
        messages.success(request, 'Credit interest settings updated successfully.')


admin.site.register(CreditSettings, CreditSettingsAdmin)


@admin.register(KioskSessionConfig, site=secure_admin_site)
class KioskSessionConfigAdmin(admin.ModelAdmin):
    fieldsets = (
        (
            "Automatic kiosk logout",
            {
                "description": (
                    "Controls idle timeout on the self-checkout page (/kiosk/). "
                    "Activity includes mouse, touch, keyboard, scroll, and clicks."
                ),
                "fields": ("auto_logout_enabled", "inactivity_minutes", "warning_seconds"),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("updated_at",),
                "classes": ("collapse",),
            },
        ),
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not KioskSessionConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        config = KioskSessionConfig.get()
        return redirect(
            reverse("admin:admin_panel_kiosksessionconfig_change", args=[config.pk])
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        messages.success(request, "Kiosk session settings updated. Changes apply on the next kiosk page load.")


admin.site.register(KioskSessionConfig, KioskSessionConfigAdmin)


@admin.register(PrinterSettings, site=secure_admin_site)
class PrinterSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        (
            "Receipt printer",
            {
                "description": (
                    "Configure which Windows printer is used for receipt printing. "
                    "Leave printer name blank to use the Windows default printer."
                ),
                "fields": ("printer_name", "paper_size", "auto_print_on_load"),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("updated_at",),
                "classes": ("collapse",),
            },
        ),
    )
    readonly_fields = ("updated_at",)

    @staticmethod
    def _get_system_printer_choices():
        """Return grouped Windows printers (paired/online vs not paired/offline)."""
        paired_or_online = set()
        not_paired_or_offline = set()
        detection_notes = []

        # Method 1: pywin32 (best signal if available)
        try:
            import win32print

            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            status_offline = getattr(win32print, "PRINTER_STATUS_OFFLINE", 0)
            attr_work_offline = getattr(win32print, "PRINTER_ATTRIBUTE_WORK_OFFLINE", 0)

            printers = win32print.EnumPrinters(flags, None, 2) or []
            for printer in printers:
                name = (printer.get("pPrinterName") or "").strip()
                if not name:
                    continue
                status = int(printer.get("Status") or 0)
                attributes = int(printer.get("Attributes") or 0)
                is_offline = bool(status & status_offline) or bool(attributes & attr_work_offline)
                if is_offline:
                    not_paired_or_offline.add(name)
                else:
                    paired_or_online.add(name)

            if not paired_or_online and not not_paired_or_offline:
                fallback_printers = win32print.EnumPrinters(flags) or []
                for printer in fallback_printers:
                    if len(printer) > 2:
                        name = (printer[2] or "").strip()
                        if name:
                            paired_or_online.add(name)
            detection_notes.append("pywin32")
        except Exception:
            detection_notes.append("pywin32 unavailable")

        # Method 2: PowerShell Get-Printer (works without pywin32)
        if not paired_or_online and not not_paired_or_offline:
            try:
                import json
                import subprocess

                ps_cmd = (
                    "Get-Printer | "
                    "Select-Object Name,PrinterStatus,WorkOffline | "
                    "ConvertTo-Json -Compress"
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_cmd],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                raw = (result.stdout or "").strip()
                parsed = json.loads(raw) if raw else []
                if isinstance(parsed, dict):
                    parsed = [parsed]

                for printer in parsed:
                    name = str(printer.get("Name") or "").strip()
                    if not name:
                        continue
                    status = str(printer.get("PrinterStatus") or "").strip()
                    work_offline = str(printer.get("WorkOffline") or "").strip().lower() == "true"
                    # PrinterStatus 7 = Offline (Win32_Printer)
                    is_offline = work_offline or status == "7"
                    if is_offline:
                        not_paired_or_offline.add(name)
                    else:
                        paired_or_online.add(name)
                detection_notes.append("powershell:Get-Printer")
            except Exception:
                detection_notes.append("powershell:Get-Printer failed")

        # Method 3: WMI fallback list only (no reliable online/offline split)
        if not paired_or_online and not not_paired_or_offline:
            try:
                import subprocess

                ps_cmd = "(Get-CimInstance Win32_Printer | Select-Object -ExpandProperty Name)"
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_cmd],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=8,
                )
                for line in (result.stdout or "").splitlines():
                    name = line.strip()
                    if name:
                        paired_or_online.add(name)
                detection_notes.append("powershell:Win32_Printer")
            except Exception:
                detection_notes.append("powershell:Win32_Printer failed")

        # Blank means: use Windows default printer.
        choices = [("", "Use Windows default printer")]

        if paired_or_online:
            choices.append(
                (
                    "Paired / online printers",
                    [(name, name) for name in sorted(paired_or_online)],
                )
            )
        if not_paired_or_offline:
            choices.append(
                (
                    "Not paired / offline printers",
                    [(name, name) for name in sorted(not_paired_or_offline)],
                )
            )
        return choices, detection_notes

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj=obj, change=change, **kwargs)
        if "printer_name" in form.base_fields:
            choices, detection_notes = self._get_system_printer_choices()
            current_value = (getattr(obj, "printer_name", "") or "").strip()

            def _contains_choice(value):
                for item_value, item_label in choices:
                    if isinstance(item_label, (list, tuple)):
                        for child_value, _ in item_label:
                            if child_value == value:
                                return True
                    elif item_value == value:
                        return True
                return False

            if current_value and not _contains_choice(current_value):
                choices.append(
                    (
                        "Currently saved (not detected on this computer)",
                        [(current_value, current_value)],
                    )
                )

            form.base_fields["printer_name"] = forms.ChoiceField(
                required=False,
                label=form.base_fields["printer_name"].label,
                help_text=(
                    "The list is grouped into Paired/online and Not paired/offline "
                    "printers detected on this Windows computer. If your printer is "
                    "missing, check Windows printer setup/pairing and refresh this page."
                ),
                choices=choices,
            )
            if len(choices) == 1:
                if detection_notes:
                    form.base_fields["printer_name"].help_text += (
                        f" Detection methods tried: {', '.join(detection_notes)}."
                    )
        return form

    def has_add_permission(self, request):
        return not PrinterSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        config = PrinterSettings.get()
        return redirect(
            reverse("admin:admin_panel_printersettings_change", args=[config.pk])
        )

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        target = obj.printer_name or "Windows default printer"
        messages.success(request, f"Printer settings updated. Active printer: {target}.")


admin.site.register(PrinterSettings, PrinterSettingsAdmin)

# Custom admin home with Export / Import all data banner
admin.site.index_template = 'admin/custom_index.html'


@admin.register(WebsiteAuditLog, site=secure_admin_site)
class WebsiteAuditLogAdmin(admin.ModelAdmin):
    """Append-only site activity log — viewable in Django admin for super-admins."""

    list_display = (
        'created_at',
        'action',
        'actor_label',
        'request_method',
        'request_path',
        'ip_address',
    )
    list_filter = ('action', 'created_at')
    search_fields = ('actor_label', 'description', 'request_path', 'actor__username', 'ip_address')
    readonly_fields = (
        'action',
        'actor',
        'actor_label',
        'description',
        'request_method',
        'request_path',
        'object_type',
        'object_id',
        'metadata',
        'ip_address',
        'created_at',
    )
    date_hierarchy = 'created_at'
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


admin.site.register(WebsiteAuditLog, WebsiteAuditLogAdmin)
