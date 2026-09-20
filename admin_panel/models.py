import re
from datetime import time
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class ReportScheduleConfig(models.Model):
    """
    Singleton model to configure when the automatic daily report is sent.
    Only one record (pk=1) should ever exist.
    """
    send_time = models.TimeField(
        default=time(0, 0),
        help_text="Time to send the daily report (e.g. 12:00 AM = 00:00, 8:00 PM = 20:00).",
    )
    is_enabled = models.BooleanField(
        default=True,
        help_text="Uncheck to pause automatic report sending.",
    )
    refund_window_days = models.PositiveIntegerField(
        default=1,
        help_text="Number of days after purchase that a customer is allowed to request a refund (e.g. 1 = within 24 hours, 3 = within 3 days).",
    )
    return_window_days = models.PositiveIntegerField(
        default=3,
        help_text="Number of days the member has to physically return the item after a refund is approved (e.g. 3 = 3 days to return). If not returned in time, the refund is automatically voided.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Report Schedule Config"
        verbose_name_plural = "Report Schedule Config"

    def __str__(self):
        status = "Enabled" if self.is_enabled else "Disabled"
        return f"Daily Report at {self.send_time.strftime('%I:%M %p')} ({status})"

    def save(self, *args, **kwargs):
        # Force singleton — always save as pk=1
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        # Prevent deletion; reset to defaults instead
        pass

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"send_time": time(0, 0), "is_enabled": True, "refund_window_days": 1, "return_window_days": 3})
        return obj


class SentDailyReport(models.Model):
    """Track sent daily reports to prevent duplicates"""
    report_date = models.DateField(help_text="Date of the report")
    recipient_email = models.EmailField(help_text="Email address that received the report")
    sent_at = models.DateTimeField(auto_now_add=True, help_text="When the report was sent")
    
    class Meta:
        unique_together = [['report_date', 'recipient_email']]
        ordering = ['-report_date', '-sent_at']
        verbose_name = "Sent Daily Report"
        verbose_name_plural = "Sent Daily Reports"
    
    def __str__(self):
        return f"Report for {self.report_date} sent to {self.recipient_email} on {self.sent_at}"


class StoreProfile(models.Model):
    """
    Singleton model holding store/branch information shown in the mobile app
    Settings screen and used site-wide for identification.
    Only one record (pk=1) should ever exist.
    """
    store_name = models.CharField(
        max_length=120,
        default='BAGNOS MPC',
        help_text="Official store / business name.",
    )
    show_store_name = models.BooleanField(
        default=True,
        help_text="When enabled, the store name appears on the member login page and in the mobile app (with kiosk system name). When disabled, only the kiosk system name is shown where applicable.",
    )
    branch_name = models.CharField(
        max_length=120,
        blank=True,
        help_text="Branch label, e.g. 'Main Branch' or 'SM Pampanga Branch'.",
    )
    address_line1 = models.CharField(
        max_length=200,
        blank=True,
        help_text="Street / building address.",
    )
    address_line2 = models.CharField(
        max_length=200,
        blank=True,
        help_text="Barangay, subdivision, or unit number (optional).",
    )
    city = models.CharField(max_length=100, blank=True, help_text="City or municipality.")
    province = models.CharField(max_length=100, blank=True, help_text="Province or region.")
    zip_code = models.CharField(max_length=20, blank=True, help_text="Postal / ZIP code.")
    contact_number = models.CharField(
        max_length=30,
        blank=True,
        help_text="Primary contact number (e.g. 0917-123-4567).",
    )
    alt_contact_number = models.CharField(
        max_length=30,
        blank=True,
        help_text="Alternative / landline number (optional).",
    )
    email = models.EmailField(blank=True, help_text="Store email address (optional).")
    website = models.URLField(blank=True, help_text="Store website URL (optional).")
    business_hours = models.CharField(
        max_length=200,
        blank=True,
        help_text="Operating hours, e.g. 'Mon–Sat 8 AM – 6 PM'.",
    )
    maps_url = models.URLField(
        max_length=2000,
        blank=True,
        help_text="Paste the full Google Maps URL. Latitude and Longitude will be extracted automatically on save.",
    )
    latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        help_text="Auto-filled from the Maps URL when you save. Do not edit manually.",
    )
    longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        null=True,
        blank=True,
        help_text="Auto-filled from the Maps URL when you save. Do not edit manually.",
    )
    tagline = models.CharField(
        max_length=200,
        blank=True,
        help_text="Short tagline or slogan shown in the app (optional).",
    )
    logo = models.ImageField(
        upload_to='store_logos/',
        blank=True,
        null=True,
        help_text="Store logo image (displayed in the mobile app).",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Store Profile"
        verbose_name_plural = "Store Profile"

    def __str__(self):
        parts = [self.store_name]
        if self.branch_name:
            parts.append(self.branch_name)
        return ' — '.join(parts)

    @staticmethod
    def _parse_coords(url):
        """
        Extract (latitude, longitude) from a Google Maps URL.
        Handles common formats:
          - /@lat,lng,zoom  (standard place URL)
          - !3d<lat>!4d<lng>  (encoded data parameter)
          - ?q=lat,lng  (simple query)
          - /dir/.../@lat,lng,zoom
        Returns (lat_str, lng_str) or (None, None).
        """
        if not url:
            return None, None
        # Pattern 1 (highest priority): !3d<lat>!4d<lng> — actual pin coordinates
        lat_m = re.search(r'!3d(-?\d+\.\d+)', url)
        lng_m = re.search(r'!4d(-?\d+\.\d+)', url)
        if lat_m and lng_m:
            return lat_m.group(1), lng_m.group(1)
        # Pattern 2: /@lat,lng,zoom — map viewport center
        m = re.search(r'/@(-?\d+\.\d+),(-?\d+\.\d+)', url)
        if m:
            return m.group(1), m.group(2)
        # Pattern 3: ?q=lat,lng or &q=lat,lng
        m = re.search(r'[?&]q=(-?\d+\.\d+),(-?\d+\.\d+)', url)
        if m:
            return m.group(1), m.group(2)
        return None, None

    def save(self, *args, **kwargs):
        self.pk = 1
        # Auto-extract coordinates from maps_url whenever it is set
        if self.maps_url:
            lat, lng = self._parse_coords(self.maps_url)
            if lat and lng:
                from decimal import Decimal
                self.latitude = Decimal(lat)
                self.longitude = Decimal(lng)
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # Prevent deletion

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={'store_name': 'BAGNOS MPC'},
        )
        return obj


class KioskConfig(models.Model):
    """
    Singleton model to configure the kiosk system name and tagline
    displayed on the kiosk page header and receipts.
    Only one record (pk=1) should ever exist.
    """
    system_name = models.CharField(
        max_length=200,
        default='BAGNOS MPC - Self Checkout',
        help_text="System name shown in the kiosk header, page title, and receipts.",
    )
    tagline = models.CharField(
        max_length=200,
        default='Quick, Easy, and Convenient Shopping',
        help_text="Short tagline shown below the system name in the kiosk header.",
    )
    admin_dashboard_description = models.TextField(
        default='Monitor real-time performance of BAGNOS MPC. Track sales, members, inventory and member standing from a single super admin console.',
        help_text="Description text shown in the Super Admin dashboard hero section.",
    )
    receipt_subtitle = models.CharField(
        max_length=200,
        default='Self-Checkout Receipt',
        help_text="Subtitle printed on every receipt copy, e.g. 'Self-Checkout Receipt'.",
    )
    receipt_thank_you = models.CharField(
        max_length=200,
        default='Thank you for your purchase!',
        help_text="Thank-you line printed at the bottom of every receipt.",
    )
    receipt_header_store_name = models.CharField(
        max_length=200,
        default='SHOP NAME',
        help_text="Store / business name printed at the top of every receipt.",
    )
    receipt_header_store_description = models.TextField(
        blank=True,
        help_text=(
            "Short description of the store printed under the store name on receipts "
            "(e.g. cooperative type, services offered, or branch note)."
        ),
    )
    receipt_header_address = models.CharField(
        max_length=300,
        blank=True,
        help_text="Address line printed under the store name on receipts.",
    )
    receipt_header_phone = models.CharField(
        max_length=50,
        blank=True,
        help_text="Phone / contact number printed on the receipt header.",
    )
    receipt_footer_customer_tagline = models.CharField(
        max_length=200,
        default='We appreciate your business.',
        help_text="Tagline printed at the bottom of the customer copy.",
    )
    receipt_footer_merchant_note = models.CharField(
        max_length=200,
        default='Merchant copy — retain for records.',
        help_text="Note printed at the bottom of the merchant copy.",
    )
    member_max_credit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        help_text=(
            "Maximum total outstanding credit (utang) allowed per member. "
            "Set to 0 for no limit. Credit purchases are blocked when "
            "outstanding credit plus the new sale would exceed this amount."
        ),
    )
    tax_enabled = models.BooleanField(
        default=True,
        help_text=(
            "Enable or disable tax (VAT) calculation system-wide. "
            "When disabled, no tax is computed or displayed on the kiosk, "
            "receipts, or stored on transactions."
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Kiosk Config"
        verbose_name_plural = "Kiosk Config"

    def __str__(self):
        return self.system_name

    def brand_title_short(self):
        """Short label for subjects and UI: text before ' - ' if present, else full system_name."""
        full = (self.system_name or '').strip()
        if not full:
            return 'Self Checkout'
        if ' - ' in full:
            part = full.split(' - ', 1)[0].strip()
            return part or full
        return full

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # Prevent deletion

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                'system_name': 'BAGNOS MPC - Self Checkout',
                'tagline': 'Quick, Easy, and Convenient Shopping',
                'admin_dashboard_description': 'Monitor real-time performance of BAGNOS MPC. Track sales, members, inventory and member standing from a single super admin console.',
                'receipt_subtitle': 'Self-Checkout Receipt',
                'receipt_thank_you': 'Thank you for your purchase!',
                'receipt_header_store_name': 'SHOP NAME',
                'receipt_header_store_description': '',
                'receipt_header_address': '',
                'receipt_header_phone': '',
                'receipt_footer_customer_tagline': 'We appreciate your business.',
                'receipt_footer_merchant_note': 'Merchant copy — retain for records.',
                'member_max_credit': 0,
                'tax_enabled': True,
            },
        )
        return obj


class CreditSettings(models.Model):
    """
    Singleton settings for store credit (utang) interest.
    After the grace period, each unpaid month adds principal × rate.

    Example (rate 0.015, principal ₱500):
      Month 1: (500 × 0.015) + 500 = 507.50
      Month 2: 507.50 + 7.50 = 515.00
    """

    interest_rate = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=0,
        help_text=(
            "Monthly interest rate on unpaid credit (utang) after grace. "
            "Enter a decimal (0.015 = 1.5%) or a percent greater than 1 (1.5 = 1.5%). "
            "Each unpaid month: interest = remaining principal × rate "
            "(same ₱ amount each month). "
            "Example: ₱500 → ₱507.50 after month 1; month 2 adds another ₱7.50 → ₱515. "
            "Set to 0 to disable."
        ),
    )
    grace_period_days = models.PositiveIntegerField(
        default=3,
        help_text=(
            "Days after a credit sale before interest starts. "
            "Example: 3 means the member can pay within 3 days with no interest; "
            "after that, principal × rate is added every unpaid month. "
            "Set to 0 to start charging from the day of the sale."
        ),
    )
    is_enabled = models.BooleanField(
        default=False,
        help_text="When enabled, interest is applied to overdue credit (utang) balances.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Credit Settings"
        verbose_name_plural = "Credit Settings"

    def __str__(self):
        if not self.is_enabled:
            return "Credit settings — interest disabled"
        rate = self.interest_rate or 0
        days = int(self.grace_period_days or 0)
        return f"Credit settings — {rate}/month after {days} day grace"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # Prevent deletion

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "interest_rate": 0,
                "grace_period_days": 3,
                "is_enabled": False,
            },
        )
        return obj


class KioskSessionConfig(models.Model):
    """
    Singleton model for idle auto-logout on /kiosk/.
    Only one record (pk=1) should ever exist.
    """

    auto_logout_enabled = models.BooleanField(
        default=True,
        help_text="When enabled, regular members are logged out after inactivity on /kiosk/. "
        "Admin, staff, and cashier sessions are never auto-logged out from idle.",
    )
    inactivity_minutes = models.PositiveIntegerField(
        default=50,
        help_text="Minutes without keyboard, mouse, touch, or scroll activity before logout.",
    )
    warning_seconds = models.PositiveIntegerField(
        default=30,
        help_text="How many seconds before logout to show the inactivity warning.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Kiosk Session Config"
        verbose_name_plural = "Kiosk Session Config"

    def __str__(self):
        if not self.auto_logout_enabled:
            return "Kiosk auto-logout disabled"
        return f"Auto-logout after {self.inactivity_minutes} min (warn {self.warning_seconds}s before)"

    def clean(self):
        super().clean()
        total_sec = int(self.inactivity_minutes) * 60
        ws = int(self.warning_seconds)
        if ws >= total_sec:
            raise ValidationError(
                {
                    "warning_seconds": "Warning time must be shorter than the full inactivity period "
                    f"(currently {total_sec} seconds).",
                }
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "auto_logout_enabled": True,
                "inactivity_minutes": 50,
                "warning_seconds": 30,
            },
        )
        return obj


class PrinterSettings(models.Model):
    """
    Singleton model that stores receipt printer preferences.
    """

    PAPER_SIZE_57MM = "57mm"
    PAPER_SIZE_58MM = "58mm"
    PAPER_SIZE_80MM = "80mm"
    PAPER_SIZE_A4 = "A4"
    PAPER_SIZE_CHOICES = [
        (PAPER_SIZE_57MM, "57 mm (narrow roll)"),
        (PAPER_SIZE_58MM, "58 mm (narrow roll)"),
        (PAPER_SIZE_80MM, "80 mm (standard roll)"),
        (PAPER_SIZE_A4, "A4 (full page)"),
    ]

    printer_name = models.CharField(
        max_length=120,
        blank=True,
        default="",
        help_text=(
            "Exact printer name in Windows (for example: XP-58 or EPSON TM-T88V). "
            "Leave blank to use the Windows default printer."
        ),
    )
    paper_size = models.CharField(
        max_length=10,
        choices=PAPER_SIZE_CHOICES,
        default=PAPER_SIZE_57MM,
        help_text="Paper size loaded in the receipt printer.",
    )
    auto_print_on_load = models.BooleanField(
        default=True,
        help_text=(
            "When enabled, receipt pages auto-open the print dialog so staff can print faster."
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Printer Settings"
        verbose_name_plural = "Printer Settings"

    def __str__(self):
        name = self.printer_name or "Windows default printer"
        return f"{name} ({self.get_paper_size_display()})"

    def save(self, *args, **kwargs):
        self.pk = 1
        self.printer_name = (self.printer_name or "").strip()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "printer_name": "",
                "paper_size": cls.PAPER_SIZE_57MM,
                "auto_print_on_load": True,
            },
        )
        return obj


class WebsiteAuditLog(models.Model):
    """Immutable site-wide audit trail for admin monitoring.

    Records who did what on the website (login, logout, and mutating actions
    on dashboard / kiosk / admin). Rows are append-only.
    """

    class Action(models.TextChoices):
        LOGIN = "LOGIN", "Login"
        LOGOUT = "LOGOUT", "Logout"
        LOGIN_FAILED = "LOGIN_FAILED", "Login Failed"
        PAGE_ACTION = "PAGE_ACTION", "Page Action"
        MEMBER = "MEMBER", "Members"
        INVENTORY = "INVENTORY", "Inventory"
        TRANSACTION = "TRANSACTION", "Transactions"
        PURCHASE = "PURCHASE", "Purchase / Sale"
        REFUND = "REFUND", "Refund"
        BALANCE_REFILL = "BALANCE_REFILL", "Balance Refill"
        FUND_TRANSFER = "FUND_TRANSFER", "Fund Transfer"
        QR = "QR", "QR Code"
        CREDIT_PAYMENT = "CREDIT_PAYMENT", "Credit Payment"
        LOAN = "LOAN", "Loans"
        SAVINGS = "SAVINGS", "Savings"
        SHARE_CAPITAL = "SHARE_CAPITAL", "Share Capital"
        PALAY = "PALAY", "Palay Trade"
        SETTINGS = "SETTINGS", "Settings"
        REPORT = "REPORT", "Report / Export"
        KIOSK = "KIOSK", "Kiosk"
        ADMIN = "ADMIN", "Django Admin"
        OTHER = "OTHER", "Other"

    action = models.CharField(max_length=40, choices=Action.choices, db_index=True)
    actor = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="website_audit_entries",
    )
    actor_label = models.CharField(max_length=200)
    description = models.TextField()
    request_method = models.CharField(max_length=10, blank=True, default="")
    request_path = models.CharField(max_length=500, blank=True, default="")
    object_type = models.CharField(max_length=80, blank=True, default="")
    object_id = models.CharField(max_length=64, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Website Audit Log"
        verbose_name_plural = "Website Audit Logs"
        indexes = [
            models.Index(fields=["action", "-created_at"]),
            models.Index(fields=["actor", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.get_action_display()} by {self.actor_label} at {self.created_at}"
