"""
mobile_api_helper.py
====================
Django server-side helper for the mobile_api app.

Works directly against the database via Django ORM — no HTTP requests.
Use this from views, management commands, tasks, or the Django shell.

Usage examples
--------------
    from helper.mobile_api_helper import (
        authenticate_member,
        get_account_info,
        get_account_summary,
        get_transaction_history,
        get_balance_transactions,
        get_product_list,
        search_member,
        request_fund_transfer_otp,
        verify_fund_transfer_otp,
        request_biometric_otp,
        verify_biometric_otp,
        get_or_create_qr_code,
        scan_qr_code,
        regenerate_qr_code,
        get_store_info,
        check_health,
        reset_pin_lockout,
    )

    # --- Auth ---
    member = authenticate_member(username="john_doe", pin="1234")
    member = authenticate_member(rfid="ABC123", pin="5678")

    # --- Account ---
    info    = get_account_info(member)
    summary = get_account_summary(member, year=2026, month=4)

    # --- Transactions ---
    txns  = get_transaction_history(member, page=1, limit=20)
    btxns = get_balance_transactions(member, page=1, limit=20)

    # --- Products ---
    products = get_product_list(search="milk", category="Dairy")

    # --- Fund Transfer (OTP flow) ---
    request_fund_transfer_otp(member, recipient_rfid="XYZ789", amount="500.00", notes="Lunch")
    result = verify_fund_transfer_otp(member, otp_code="123456")

    # --- Biometric Enrollment ---
    request_biometric_otp(member)
    verify_biometric_otp(member, otp_code="654321")

    # --- QR Code ---
    qr      = get_or_create_qr_code(member)
    scanned = scan_qr_code(token="<uuid>")
    regen   = regenerate_qr_code(member)

    # --- Member Search ---
    results = search_member(query="Maria Santos")

    # --- Admin ---
    reset_pin_lockout(username="john_doe")

    # --- Utilities ---
    health = check_health()
    store  = get_store_info()
"""

from __future__ import annotations

import logging
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from django.conf import settings
from django.contrib.auth.models import User as DjangoUser
from django.db import connection, transaction as db_transaction
from django.db.models import Q, Sum
from django.utils import timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy model imports (avoids AppRegistryNotReady on import)
# ---------------------------------------------------------------------------

def _get_models():
    from members.models import Member, BalanceTransaction
    from transactions.models import Transaction, TransactionItem
    from inventory.models import Product, Category
    from mobile_api.models import FundTransferOTP, BiometricEnrollOTP, MemberQRCode, QRFeatureSettings
    from admin_panel.models import StoreProfile
    return (
        Member, BalanceTransaction, Transaction, TransactionItem,
        Product, Category, FundTransferOTP, BiometricEnrollOTP,
        MemberQRCode, QRFeatureSettings, StoreProfile,
    )


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class MobileAPIError(Exception):
    """Base error for mobile API helper operations."""


class AuthenticationError(MobileAPIError):
    """Wrong credentials, locked account, or permission denied."""


class NotFoundError(MobileAPIError):
    """Requested resource does not exist."""


class ValidationError(MobileAPIError):
    """Input data is invalid or a business rule was violated."""


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PIN_MAX_ATTEMPTS: int = 5
MAX_MEMBER_SEARCH_RESULTS: int = 10


# ===========================================================================
# Authentication
# ===========================================================================

def authenticate_member(
    username: str = "",
    pin: str = "",
    rfid: str = "",
) -> Any:
    """
    Verify credentials and return the authenticated Member instance.

    Provide either ``username + pin`` or ``rfid + pin``.

    Raises
    ------
    ValidationError
        If required fields are missing or the PIN format is invalid.
    AuthenticationError
        If credentials are wrong or the account is locked.
    NotFoundError
        If no matching member is found.
    """
    (
        Member, BalanceTransaction, Transaction, _TI,
        _P, _C, _FOTP, _BOTP, _QR, _QRS, _SP,
    ) = _get_models()

    if not pin:
        raise ValidationError("PIN is required.")
    if not pin.isdigit() or len(pin) != 4:
        raise ValidationError("PIN must be exactly 4 digits.")
    if not username and not rfid:
        raise ValidationError("Either username or RFID is required.")

    member = None

    if username:
        # Try Django User → Member
        user = None
        try:
            user = DjangoUser.objects.get(username=username, is_active=True)
        except DjangoUser.DoesNotExist:
            pass
        except DjangoUser.MultipleObjectsReturned:
            user = DjangoUser.objects.filter(username=username, is_active=True).first()

        if user:
            try:
                member = Member.objects.get(user=user, is_active=True)
            except Member.DoesNotExist:
                member = None
            except Member.MultipleObjectsReturned:
                member = Member.objects.filter(user=user, is_active=True).first()

        # Fall back to Member.username field
        if member is None:
            try:
                member = Member.objects.get(username=username, is_active=True)
            except Member.DoesNotExist:
                member = None
            except Member.MultipleObjectsReturned:
                member = Member.objects.filter(username=username, is_active=True).first()

        if member is None:
            raise AuthenticationError(
                "Invalid username or PIN. Please check your credentials and try again."
            )

    elif rfid:
        try:
            member = Member.objects.get(rfid_card_number=rfid, is_active=True)
        except Member.DoesNotExist:
            raise NotFoundError("Member not found or account is inactive.")

        if member.role != "member":
            raise AuthenticationError("RFID login is only allowed for members with role 'member'.")
        if member.user is not None and getattr(member.user, "username", None):
            raise ValidationError("Please use your username to log in.")

    # Locked account check
    if member.is_pin_locked:
        raise AuthenticationError(
            "Account locked due to too many failed PIN attempts. "
            "Please contact the administrator to unlock your account."
        )

    # PIN verification
    try:
        if not member.check_pin(pin):
            member.pin_attempts = (member.pin_attempts or 0) + 1
            remaining = PIN_MAX_ATTEMPTS - member.pin_attempts
            if member.pin_attempts >= PIN_MAX_ATTEMPTS:
                member.is_pin_locked = True
                member.save(update_fields=["pin_attempts", "is_pin_locked"])
                _notify_admins_lockout(member)
                raise AuthenticationError(
                    "Account locked due to too many failed PIN attempts. "
                    "Please contact the administrator to unlock your account."
                )
            member.save(update_fields=["pin_attempts"])
            raise AuthenticationError(
                f"Invalid PIN. {remaining} attempt{'s' if remaining != 1 else ''} remaining."
            )
    except AttributeError:
        raise ValidationError("PIN not set for this account. Please contact the administrator.")

    # Reset failed attempts on success
    if member.pin_attempts:
        member.pin_attempts = 0
        member.save(update_fields=["pin_attempts"])

    return member


def _notify_admins_lockout(member) -> None:
    """Send a lockout notification email to all staff users (fire-and-forget)."""
    try:
        from django.core.mail import send_mail
        admin_emails = list(
            DjangoUser.objects.filter(is_staff=True, is_active=True)
            .exclude(email="")
            .values_list("email", flat=True)
        )
        if admin_emails:
            from admin_panel.models import KioskConfig

            send_mail(
                subject=(
                    f"[{KioskConfig.get().brand_title_short()}] "
                    f"Account Locked: {member.full_name}"
                ),
                message=(
                    f"The account for {member.full_name} "
                    f"({getattr(member.user, 'username', None) or member.rfid_card_number}) "
                    f"has been locked after {PIN_MAX_ATTEMPTS} failed PIN attempts.\n\n"
                    "Please log in to the admin panel to reset their PIN and unlock the account."
                ),
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "BAGNOS MPC <noreply@bagnosmpc.local>"),
                recipient_list=admin_emails,
                fail_silently=True,
            )
    except Exception:
        logger.exception("Failed to send lockout notification email.")


# ===========================================================================
# Account
# ===========================================================================

def get_account_info(member) -> Dict[str, Any]:
    """
    Return a dict with the member's profile data.
    """
    return _serialize_member(member)


def get_account_summary(
    member,
    year: Optional[int] = None,
    month: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Return an account summary dict including recent transactions and monthly totals.

    Parameters
    ----------
    member : Member
    year : int, optional   – defaults to the current year
    month : int, optional  – 1–12, defaults to the current month
    """
    (
        _M, BalanceTransaction, Transaction, _TI,
        _P, _C, _FOTP, _BOTP, _QR, _QRS, _SP,
    ) = _get_models()

    now = timezone.now()
    year = year or now.year
    month = month or now.month
    if not (1 <= month <= 12):
        month = now.month

    tz = timezone.get_current_timezone()
    start = timezone.datetime(year, month, 1, tzinfo=tz)
    end = (
        timezone.datetime(year + 1, 1, 1, tzinfo=tz)
        if month == 12
        else timezone.datetime(year, month + 1, 1, tzinfo=tz)
    )

    recent_transactions = (
        Transaction.objects.filter(member=member, status="completed")
        .select_related("member")
        .prefetch_related("items")
        .order_by("-created_at")[:10]
    )

    recent_balance_transactions = (
        member.balance_transactions.all().order_by("-created_at")[:10]
    )

    monthly_transactions = Transaction.objects.filter(
        member=member,
        status="completed",
        created_at__gte=start,
        created_at__lt=end,
    )
    total_spent = sum(t.total_amount for t in monthly_transactions)

    return {
        "member": _serialize_member(member),
        "recent_transactions": [_serialize_transaction(t) for t in recent_transactions],
        "recent_balance_transactions": [
            _serialize_balance_transaction(bt) for bt in recent_balance_transactions
        ],
        "total_spent_this_month": str(total_spent),
        "selected_year": year,
        "selected_month": month,
    }


# ===========================================================================
# Transactions
# ===========================================================================

def get_transaction_history(
    member,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Return a paginated dict of completed purchase transactions for ``member``.
    """
    (
        _M, _BT, Transaction, _TI,
        _P, _C, _FOTP, _BOTP, _QR, _QRS, _SP,
    ) = _get_models()

    offset = (page - 1) * limit
    qs = (
        Transaction.objects.filter(member=member, status="completed")
        .select_related("member")
        .prefetch_related("items")
        .order_by("-created_at")
    )
    total = qs.count()
    transactions = qs[offset: offset + limit]

    return {
        "transactions": [_serialize_transaction(t) for t in transactions],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "has_next": offset + limit < total,
            "has_previous": page > 1,
        },
    }


def get_balance_transactions(
    member,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Return a paginated dict of balance transactions (deposits / deductions).
    """
    offset = (page - 1) * limit
    qs = member.balance_transactions.all().order_by("-created_at")
    total = qs.count()
    items = qs[offset: offset + limit]

    return {
        "balance_transactions": [_serialize_balance_transaction(bt) for bt in items],
        "pagination": {
            "page": page,
            "limit": limit,
            "total": total,
            "has_next": offset + limit < total,
            "has_previous": page > 1,
        },
    }


# ===========================================================================
# Products
# ===========================================================================

def get_product_list(
    search: str = "",
    category: str = "",
) -> List[Dict[str, Any]]:
    """
    Return a list of active products, optionally filtered by name/barcode
    and/or comma-separated category names.
    """
    (
        _M, _BT, _T, _TI,
        Product, Category, _FOTP, _BOTP, _QR, _QRS, _SP,
    ) = _get_models()

    qs = Product.objects.filter(is_active=True).select_related("category")

    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(barcode__icontains=search))

    if category:
        cat_names = [c.strip() for c in category.split(",") if c.strip()]
        if cat_names:
            qs = qs.filter(category__name__in=cat_names)

    return [_serialize_product(p) for p in qs.order_by("name")]


# ===========================================================================
# Member search
# ===========================================================================

def search_member(
    query: str = "",
    rfid: str = "",
    exclude_member=None,
) -> Dict[str, Any]:
    """
    Search for a member by exact RFID or by name tokens.

    Returns
    -------
    dict
        ``{"member": {...}}``  for an exact RFID match.
        ``{"members": [...]}`` for a name search.

    Raises
    ------
    ValidationError
        If neither ``query`` nor ``rfid`` is provided.
    NotFoundError
        If no member is found.
    """
    (Member, *_) = _get_models()

    search_term = (rfid or query or "").strip()
    if not search_term:
        raise ValidationError("Either query or rfid is required.")

    # Exact RFID match
    try:
        recipient = Member.objects.get(rfid_card_number=search_term, is_active=True)
        if exclude_member and recipient.id == exclude_member.id:
            raise ValidationError("Cannot select yourself.")
        return {"member": _serialize_member(recipient)}
    except Member.DoesNotExist:
        pass

    # If caller used rfid= and no match, stop here
    if rfid:
        raise NotFoundError("Member not found with the provided RFID card number.")

    # Name search
    tokens = search_term.split()
    name_filter = Q()
    for token in tokens:
        name_filter &= Q(first_name__icontains=token) | Q(last_name__icontains=token)

    qs = Member.objects.filter(name_filter, is_active=True)
    if exclude_member:
        qs = qs.exclude(id=exclude_member.id)
    qs = qs.order_by("first_name", "last_name")[:MAX_MEMBER_SEARCH_RESULTS]

    if not qs.exists():
        raise NotFoundError("No member found matching your search.")

    return {"members": [_serialize_member(m) for m in qs]}


# ===========================================================================
# Fund Transfer (OTP flow)
# ===========================================================================

def request_fund_transfer_otp(
    member,
    recipient_rfid: str,
    amount,
    notes: str = "",
) -> Dict[str, Any]:
    """
    Step 1 – create an OTP record and send it to the member's email.

    Returns a dict with ``message`` and ``expires_in`` (seconds).

    Raises
    ------
    ValidationError
        Insufficient balance, missing email, or transfer-to-self.
    NotFoundError
        Recipient RFID not found.
    """
    (
        Member, BalanceTransaction, _T, _TI,
        _P, _C, FundTransferOTP, _BOTP, _QR, _QRS, _SP,
    ) = _get_models()

    amount = Decimal(str(amount))
    if amount <= 0:
        raise ValidationError("Transfer amount must be greater than zero.")
    if member.balance < amount:
        raise ValidationError("Insufficient balance.")
    if not member.email:
        raise ValidationError(
            "Email address is required for OTP verification. Please update your profile."
        )

    try:
        recipient = Member.objects.get(rfid_card_number=recipient_rfid, is_active=True)
    except Member.DoesNotExist:
        raise NotFoundError("Recipient member not found.")

    if recipient.id == member.id:
        raise ValidationError("Cannot transfer funds to yourself.")

    otp = FundTransferOTP.create_otp(member, recipient_rfid, amount, notes)

    # Send OTP email asynchronously (non-blocking)
    from mobile_api.email_utils import send_otp_email
    send_otp_email(member, recipient, otp.otp_code, amount, notes)

    return {
        "message": f"OTP has been sent to your email ({member.email}). Please check your inbox.",
        "expires_in": 600,
    }


def verify_fund_transfer_otp(
    member,
    otp_code: str,
) -> Dict[str, Any]:
    """
    Step 2 – verify the OTP and atomically complete the fund transfer.

    Returns a dict with transfer details and updated balances.

    Raises
    ------
    ValidationError
        Invalid / expired OTP or insufficient balance.
    NotFoundError
        Recipient no longer exists.
    """
    (
        Member, BalanceTransaction, _T, _TI,
        _P, _C, FundTransferOTP, _BOTP, _QR, _QRS, _SP,
    ) = _get_models()

    otp_code = (otp_code or "").strip()
    if not otp_code:
        raise ValidationError("OTP code is required.")

    try:
        otp = FundTransferOTP.objects.get(member=member, otp_code=otp_code, is_used=False)
    except FundTransferOTP.DoesNotExist:
        raise ValidationError("Invalid or expired OTP code.")

    if not otp.is_valid():
        raise ValidationError("OTP code has expired. Please request a new one.")

    amount = Decimal(str(otp.amount))
    if member.balance < amount:
        raise ValidationError("Insufficient balance.")

    try:
        recipient = Member.objects.get(rfid_card_number=otp.recipient_rfid, is_active=True)
    except Member.DoesNotExist:
        raise NotFoundError("Recipient member not found.")

    if recipient.id == member.id:
        raise ValidationError("Cannot transfer funds to yourself.")

    with db_transaction.atomic():
        otp.mark_as_used()

        # Deduct from sender
        cents = Decimal("0.01")
        sender_before = Decimal(str(member.balance)).quantize(cents)
        member.balance = (sender_before - amount).quantize(cents)
        member.save(update_fields=["balance"])
        member.refresh_from_db()
        sender_after = Decimal(str(member.balance)).quantize(cents)

        BalanceTransaction.objects.create(
            member=member,
            transaction_type="deduction",
            amount=amount,
            balance_before=sender_before,
            balance_after=sender_after,
            notes=(
                f"Fund transfer to {recipient.full_name} ({recipient.rfid_card_number})"
                + (f" - {otp.notes}" if otp.notes else "")
            ),
        )

        # Credit recipient
        recipient_before = Decimal(str(recipient.balance)).quantize(cents)
        recipient.balance = (recipient_before + amount).quantize(cents)
        recipient.save(update_fields=["balance"])
        recipient.refresh_from_db()
        recipient_after = Decimal(str(recipient.balance)).quantize(cents)

        BalanceTransaction.objects.create(
            member=recipient,
            transaction_type="deposit",
            amount=amount,
            balance_before=recipient_before,
            balance_after=recipient_after,
            notes=(
                f"Fund transfer from {member.full_name} ({member.rfid_card_number})"
                + (f" - {otp.notes}" if otp.notes else "")
            ),
        )

    # Send completion emails asynchronously
    try:
        from mobile_api.email_utils import send_transfer_completion_emails
        send_transfer_completion_emails(member, recipient, amount, otp.notes)
    except Exception:
        logger.exception("Failed to send transfer completion emails.")

    return {
        "message": "Fund transfer completed successfully.",
        "amount": str(amount),
        "sender_balance": str(sender_after),
        "recipient_name": recipient.full_name,
        "recipient_rfid": recipient.rfid_card_number,
        "notes": otp.notes,
    }


# ===========================================================================
# Biometric Enrollment (OTP flow)
# ===========================================================================

def request_biometric_otp(member) -> Dict[str, Any]:
    """
    Create a biometric enrollment OTP and send it to the member's email.

    Raises
    ------
    ValidationError
        If the member has no email address.
    """
    (
        _M, _BT, _T, _TI,
        _P, _C, _FOTP, BiometricEnrollOTP, _QR, _QRS, _SP,
    ) = _get_models()

    if not member.email:
        raise ValidationError(
            "Email address is required for biometric enrollment. Please update your profile."
        )

    otp = BiometricEnrollOTP.create_otp(member)

    from mobile_api.email_utils import send_biometric_otp_email
    send_biometric_otp_email(member, otp.otp_code)

    return {
        "message": f"OTP sent to {member.email}.",
        "expires_in": 600,
    }


def verify_biometric_otp(member, otp_code: str) -> Dict[str, Any]:
    """
    Verify a biometric enrollment OTP.

    Returns a dict with ``{"verified": True}`` on success.

    Raises
    ------
    ValidationError
        If the OTP is invalid or expired.
    """
    (
        _M, _BT, _T, _TI,
        _P, _C, _FOTP, BiometricEnrollOTP, _QR, _QRS, _SP,
    ) = _get_models()

    otp_code = (otp_code or "").strip()
    if not otp_code:
        raise ValidationError("OTP code is required.")

    try:
        otp = BiometricEnrollOTP.objects.get(member=member, otp_code=otp_code, is_used=False)
    except BiometricEnrollOTP.DoesNotExist:
        raise ValidationError("Invalid or expired OTP code.")

    if not otp.is_valid():
        raise ValidationError("OTP code has expired. Please request a new one.")

    otp.mark_as_used()
    return {"verified": True, "message": "Identity verified. You may now enroll your fingerprint."}


# ===========================================================================
# QR Code
# ===========================================================================

def get_or_create_qr_code(member) -> Dict[str, Any]:
    """
    Return the member's QR code token, creating it lazily if absent.

    Raises
    ------
    ValidationError
        If the QR feature is disabled globally.
    """
    (
        _M, _BT, _T, _TI,
        _P, _C, _FOTP, _BOTP, MemberQRCode, QRFeatureSettings, _SP,
    ) = _get_models()

    qr_settings = QRFeatureSettings.get_settings()
    if not qr_settings.is_enabled:
        raise ValidationError("QR code transfers are currently disabled.")

    qr, _ = MemberQRCode.objects.get_or_create(member=member)
    return {
        "qr_token": str(qr.qr_token),
        "is_active": qr.is_active,
        "scan_count": qr.scan_count,
        "last_scanned_at": qr.last_scanned_at.isoformat() if qr.last_scanned_at else None,
    }


def scan_qr_code(token: str) -> Dict[str, Any]:
    """
    Resolve a scanned QR token to its member.

    Parameters
    ----------
    token : str
        UUID string embedded in the QR image.

    Raises
    ------
    NotFoundError
        If the token does not match any active QR record.
    ValidationError
        If the QR feature is disabled or the code is inactive.
    """
    (
        _M, _BT, _T, _TI,
        _P, _C, _FOTP, _BOTP, MemberQRCode, QRFeatureSettings, _SP,
    ) = _get_models()

    qr_settings = QRFeatureSettings.get_settings()
    if not qr_settings.is_enabled:
        raise ValidationError("QR code transfers are currently disabled.")

    token = (token or "").strip()
    if not token:
        raise ValidationError("QR token is required.")

    try:
        qr = MemberQRCode.objects.select_related("member").get(qr_token=token)
    except MemberQRCode.DoesNotExist:
        raise NotFoundError("QR code not found or has been invalidated.")

    if not qr.is_active:
        raise ValidationError("This QR code is disabled.")

    if not qr.member.is_active:
        raise ValidationError("Member account is inactive.")

    # Update scan stats
    qr.scan_count += 1
    qr.last_scanned_at = timezone.now()
    qr.save(update_fields=["scan_count", "last_scanned_at"])

    return {"member": _serialize_member(qr.member)}


def regenerate_qr_code(member) -> Dict[str, Any]:
    """
    Invalidate the existing QR token and generate a fresh one for ``member``.
    """
    (
        _M, _BT, _T, _TI,
        _P, _C, _FOTP, _BOTP, MemberQRCode, QRFeatureSettings, _SP,
    ) = _get_models()

    import uuid
    qr, _ = MemberQRCode.objects.get_or_create(member=member)
    qr.qr_token = uuid.uuid4()
    qr.is_active = True
    qr.scan_count = 0
    qr.last_scanned_at = None
    qr.save(update_fields=["qr_token", "is_active", "scan_count", "last_scanned_at"])

    return {
        "qr_token": str(qr.qr_token),
        "message": "QR code regenerated successfully.",
    }


# ===========================================================================
# Utilities
# ===========================================================================

def get_store_info() -> Dict[str, Any]:
    """
    Return the store profile configured via Django admin (StoreProfile model).
    """
    from admin_panel.models import KioskConfig

    (
        _M, _BT, _T, _TI,
        _P, _C, _FOTP, _BOTP, _QR, _QRS, StoreProfile,
    ) = _get_models()

    profile = StoreProfile.get()
    kiosk = KioskConfig.get()
    return {
        "store_name": profile.store_name,
        "show_store_name": profile.show_store_name,
        "branch_name": profile.branch_name,
        "address_line1": profile.address_line1,
        "address_line2": profile.address_line2,
        "city": profile.city,
        "province": profile.province,
        "zip_code": profile.zip_code,
        "contact_number": profile.contact_number,
        "alt_contact_number": profile.alt_contact_number,
        "email": profile.email,
        "website": profile.website,
        "business_hours": profile.business_hours,
        "tagline": profile.tagline,
        "maps_url": profile.maps_url,
        "latitude": float(profile.latitude) if profile.latitude is not None else None,
        "longitude": float(profile.longitude) if profile.longitude is not None else None,
        "system_name": kiosk.system_name,
        "kiosk_tagline": kiosk.tagline,
    }


def check_health() -> Dict[str, Any]:
    """
    Verify the database is reachable and return a status dict.
    """
    import time as _time
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return {
            "status": "healthy",
            "timestamp": timezone.now().isoformat(),
            "server_time": int(_time.time()),
            "message": "Server is running and database is accessible",
        }
    except Exception as exc:
        return {
            "status": "unhealthy",
            "error": str(exc),
            "timestamp": timezone.now().isoformat(),
        }


# ===========================================================================
# Admin
# ===========================================================================

def reset_pin_lockout(
    username: str = "",
    member_id: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Reset a member's PIN lockout (admin operation).

    Raises
    ------
    ValidationError
        If neither ``username`` nor ``member_id`` is supplied.
    NotFoundError
        If no matching member is found.
    """
    (Member, *_) = _get_models()

    if member_id is not None:
        try:
            member = Member.objects.get(id=member_id)
        except Member.DoesNotExist:
            raise NotFoundError(f"No member found with id={member_id}.")
    elif username:
        try:
            member = Member.objects.get(username=username)
        except Member.DoesNotExist:
            # Try via linked Django user
            try:
                user = DjangoUser.objects.get(username=username)
                member = Member.objects.get(user=user)
            except (DjangoUser.DoesNotExist, Member.DoesNotExist):
                raise NotFoundError(f"No member found with username='{username}'.")
    else:
        raise ValidationError("Either username or member_id is required.")

    member.is_pin_locked = False
    member.pin_attempts = 0
    member.save(update_fields=["is_pin_locked", "pin_attempts"])

    return {
        "message": f"PIN lockout reset for {member.full_name}.",
        "member_id": member.id,
    }


# ===========================================================================
# Private serialisation helpers
# ===========================================================================

def _serialize_member(member) -> Dict[str, Any]:
    return {
        "id": member.id,
        "rfid_card_number": member.rfid_card_number or "N/A",
        "first_name": member.first_name,
        "last_name": member.last_name,
        "full_name": member.full_name,
        "email": member.email,
        "phone": getattr(member, "phone", None),
        "member_type_name": member.member_type.name if member.member_type else None,
        "balance": str(member.balance),
        "is_active": member.is_active,
        "date_joined": member.date_joined.isoformat() if member.date_joined else None,
        "last_transaction": (
            member.last_transaction.isoformat() if member.last_transaction else None
        ),
    }


def _serialize_transaction(txn) -> Dict[str, Any]:
    return {
        "id": txn.id,
        "transaction_number": txn.transaction_number,
        "subtotal": str(txn.subtotal),
        "total_amount": str(txn.total_amount),
        "payment_method": txn.payment_method,
        "payment_method_display": txn.get_payment_method_display(),
        "amount_paid": str(txn.amount_paid),
        "amount_from_balance": str(getattr(txn, "amount_from_balance", 0)),
        "status": txn.status,
        "status_display": txn.get_status_display(),
        "notes": txn.notes,
        "created_at": txn.created_at.isoformat(),
        "items": [
            {
                "id": item.id,
                "product_name": item.product_name,
                "product_barcode": item.product_barcode,
                "unit_price": str(item.unit_price),
                "quantity": item.quantity,
                "total_price": str(item.total_price),
            }
            for item in txn.items.all()
        ],
    }


def _serialize_balance_transaction(bt) -> Dict[str, Any]:
    return {
        "id": bt.id,
        "transaction_type": bt.transaction_type,
        "transaction_type_display": bt.get_transaction_type_display(),
        "amount": str(bt.amount),
        "balance_before": str(bt.balance_before),
        "balance_after": str(bt.balance_after),
        "notes": bt.notes,
        "created_at": bt.created_at.isoformat(),
    }


def _serialize_product(product) -> Dict[str, Any]:
    return {
        "id": product.id,
        "name": product.name,
        "barcode": product.barcode,
        "price": str(product.price),
        "stock_quantity": product.stock_quantity,
        "category": product.category.name if product.category else None,
        "description": getattr(product, "description", ""),
        "is_active": product.is_active,
    }