from django.db import models
from django.utils import timezone
from datetime import timedelta
import random
import string
import uuid


class FundTransferOTP(models.Model):
    """Temporary OTP storage for fund transfer verification"""
    member = models.ForeignKey('members.Member', on_delete=models.CASCADE, related_name='transfer_otps')
    recipient_rfid = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    notes = models.TextField(blank=True)
    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = "Fund Transfer OTP"
        verbose_name_plural = "Fund Transfer OTPs"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['member', 'otp_code', 'is_used']),
            models.Index(fields=['expires_at']),
        ]
    
    @classmethod
    def generate_otp(cls):
        """Generate a 6-digit OTP code"""
        return ''.join(random.choices(string.digits, k=6))
    
    @classmethod
    def create_otp(cls, member, recipient_rfid, amount, notes=''):
        """Create a new OTP for fund transfer"""
        # Delete any existing unused OTPs for this member
        cls.objects.filter(member=member, is_used=False).delete()
        
        # Generate OTP
        otp_code = cls.generate_otp()
        
        # Set expiration to 10 minutes from now
        expires_at = timezone.now() + timedelta(minutes=10)
        
        # Create OTP record
        otp = cls.objects.create(
            member=member,
            recipient_rfid=recipient_rfid,
            amount=amount,
            notes=notes,
            otp_code=otp_code,
            expires_at=expires_at
        )
        
        return otp
    
    def is_valid(self):
        """Check if OTP is still valid (not used and not expired)"""
        if self.is_used:
            return False
        if timezone.now() > self.expires_at:
            return False
        return True
    
    def mark_as_used(self):
        """Mark OTP as used"""
        self.is_used = True
        self.verified_at = timezone.now()
        self.save(update_fields=['is_used', 'verified_at'])


class BiometricEnrollOTP(models.Model):
    """Temporary OTP storage for fingerprint/biometric login enrollment"""
    member = models.ForeignKey('members.Member', on_delete=models.CASCADE, related_name='biometric_otps')
    otp_code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Biometric Enroll OTP"
        verbose_name_plural = "Biometric Enroll OTPs"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['member', 'otp_code', 'is_used']),
            models.Index(fields=['expires_at']),
        ]

    @classmethod
    def create_otp(cls, member):
        """Create a new OTP for biometric enrollment. Deletes previous unused ones."""
        cls.objects.filter(member=member, is_used=False).delete()
        otp_code = ''.join(random.choices(string.digits, k=6))
        expires_at = timezone.now() + timedelta(minutes=10)
        return cls.objects.create(
            member=member,
            otp_code=otp_code,
            expires_at=expires_at,
        )

    def is_valid(self):
        if self.is_used:
            return False
        if timezone.now() > self.expires_at:
            return False
        return True

    def mark_as_used(self):
        self.is_used = True
        self.verified_at = timezone.now()
        self.save(update_fields=['is_used', 'verified_at'])


# ─── QR Code Feature ──────────────────────────────────────────────────────────

class QRFeatureSettings(models.Model):
    """
    Singleton model that controls global QR transfer feature settings.
    Only one row should exist (enforced via save()).
    """
    is_enabled = models.BooleanField(
        default=True,
        verbose_name="Enable QR Transfer Feature",
        help_text="Globally enable or disable QR code fund transfers.",
    )
    max_transfer_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=50000.00,
        verbose_name="Max Transfer Amount via QR (₱)",
        help_text="Maximum single transfer allowed when using a QR code scan. 0 = no limit.",
    )
    qr_token_regenerate_on_use = models.BooleanField(
        default=False,
        verbose_name="Regenerate QR Token After Each Transfer",
        help_text="If enabled, each member's QR token changes after a successful QR transfer.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "QR Feature Settings"
        verbose_name_plural = "QR Feature Settings"

    def __str__(self):
        status = "Enabled" if self.is_enabled else "Disabled"
        return f"QR Feature Settings ({status})"

    def save(self, *args, **kwargs):
        # Enforce singleton: update if exists
        if not self.pk and QRFeatureSettings.objects.exists():
            existing = QRFeatureSettings.objects.first()
            self.pk = existing.pk
        super().save(*args, **kwargs)

    @classmethod
    def get_settings(cls):
        """Return the singleton settings row, creating defaults if absent."""
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class MemberQRCode(models.Model):
    """
    Stores a unique scannable QR token for each member used in fund transfers.
    The QR code encodes the token, not the raw RFID, for an extra layer of indirection.
    The token resolves back to the member's RFID on the backend.
    """
    member = models.OneToOneField(
        'members.Member',
        on_delete=models.CASCADE,
        related_name='qr_code',
        verbose_name="Member",
    )
    qr_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        verbose_name="QR Token",
        help_text="Unique token embedded in the member's QR code.",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Active",
        help_text="Disable to temporarily block QR transfers for this member.",
    )
    scan_count = models.PositiveIntegerField(
        default=0,
        editable=False,
        verbose_name="Total Scans",
    )
    last_scanned_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Last Scanned",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Member QR Code"
        verbose_name_plural = "Member QR Codes"
        ordering = ['member__first_name', 'member__last_name']

    def __str__(self):
        return f"QR for {self.member.full_name} ({'active' if self.is_active else 'inactive'})"

    def regenerate_token(self):
        """Issue a new UUID token (invalidates old QR codes for this member)."""
        self.qr_token = uuid.uuid4()
        self.save(update_fields=['qr_token', 'updated_at'])

    def record_scan(self):
        """Increment scan counter and timestamp."""
        self.scan_count += 1
        self.last_scanned_at = timezone.now()
        self.save(update_fields=['scan_count', 'last_scanned_at'])

    @classmethod
    def get_or_create_for_member(cls, member):
        """Return existing QR record or create one for the given member."""
        obj, _ = cls.objects.get_or_create(member=member)
        return obj
