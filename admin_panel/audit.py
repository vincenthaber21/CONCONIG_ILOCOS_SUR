"""Immutable site-wide activity log for security monitoring.

Records important actions by admin, staff, cashiers, and loan officers
(purchases, refills, fund transfers, QR, refunds, loans, etc.).

Logging must never break workflows — failures are swallowed and logged.
"""

import logging
import re

from helper.login_helper import get_linked_member

logger = logging.getLogger(__name__)

# Paths that should never create audit noise (polling, static, viewing the trail).
_SKIP_PREFIXES = (
    "/static/",
    "/media/",
    "/favicon",
    "/.well-known/",
    "/api/dashboard/period-data/",
    "/api/mark-balance-refills-seen/",
    "/api/mobile/",  # mobile auth polling handled selectively below
)
_SKIP_EXACT = {
    "/favicon.ico",
    "/favicon.png",
    "/robots.txt",
    "/dashboard/audit/",
}

# Mobile endpoints that ARE security-relevant (override the /api/mobile/ skip).
_MOBILE_WATCH_SUFFIXES = (
    "/qr/",
    "/transfer/",
    "/fund-transfer/",
    "/otp/",
)

_PATH_ACTION_RULES = (
    (re.compile(r"/process-payment|/api/process-payment", re.I), "PURCHASE"),
    (re.compile(r"/refill-balance|/api/refill-balance", re.I), "BALANCE_REFILL"),
    (re.compile(r"/pay-member-credit|/api/.*credit", re.I), "CREDIT_PAYMENT"),
    (re.compile(r"/fund-transfer|/transfer", re.I), "FUND_TRANSFER"),
    (re.compile(r"/qr/", re.I), "QR"),
    (re.compile(r"/process-refund|/api/process-refund|/refund", re.I), "REFUND"),
    (re.compile(r"^/dashboard/members|/api/members"), "MEMBER"),
    (re.compile(r"^/dashboard/inventory|/api/products|/api/categories"), "INVENTORY"),
    (re.compile(r"^/dashboard/transactions"), "TRANSACTION"),
    (re.compile(r"/api/delete-transaction|/api/update-transaction|/api/void-transaction", re.I), "TRANSACTION"),
    (re.compile(r"^/dashboard/loans|/loans/"), "LOAN"),
    (re.compile(r"^/dashboard/savings"), "SAVINGS"),
    (re.compile(r"^/dashboard/share-capital"), "SHARE_CAPITAL"),
    (re.compile(r"^/dashboard/palay"), "PALAY"),
    (re.compile(r"^/dashboard/staff-sales|/generate-report|/export"), "REPORT"),
    (re.compile(r"^/admin/"), "ADMIN"),
    (re.compile(r"^/kiosk|/api/scan|/api/kiosk"), "KIOSK"),
    (re.compile(r"^/dashboard"), "PAGE_ACTION"),
)

_PATH_DESCRIPTIONS = (
    (re.compile(r"/process-payment", re.I), "Completed a kiosk purchase / sale"),
    (re.compile(r"/refill-balance", re.I), "Refilled a member card balance"),
    (re.compile(r"/reverse.*refill|refill.*reverse", re.I), "Reversed a balance refill"),
    (re.compile(r"/pay-member-credit", re.I), "Recorded a member credit payment"),
    (re.compile(r"/process-refund", re.I), "Processed a refund"),
    (re.compile(r"/fund-transfer|/transfer", re.I), "Transferred funds between members"),
    (re.compile(r"/qr/", re.I), "Used QR code feature"),
    (re.compile(r"/api/members/create", re.I), "Created a member account"),
    (re.compile(r"/api/members/update", re.I), "Updated a member account"),
    (re.compile(r"/api/products/create", re.I), "Created a product"),
    (re.compile(r"/api/products/update", re.I), "Updated a product"),
    (re.compile(r"/api/products/delete", re.I), "Deleted a product"),
    (re.compile(r"/api/delete-transaction", re.I), "Deleted a transaction"),
    (re.compile(r"/dashboard/loans/steps/.+/delete", re.I), "Deleted a loan application"),
    (re.compile(r"/dashboard/savings/accounts/.+/delete", re.I), "Deleted a savings account"),
    (re.compile(r"/dashboard/palay/trades/.+/delete", re.I), "Deleted a palay trade"),
    (re.compile(r"/generate-barcode", re.I), "Generated a product barcode"),
    (re.compile(r"/disburs", re.I), "Disbursed a loan"),
    (re.compile(r"/dashboard/loans", re.I), "Performed a loan desk action"),
    (re.compile(r"/dashboard/inventory", re.I), "Changed inventory"),
    (re.compile(r"/dashboard/members", re.I), "Managed members"),
    (re.compile(r"/kiosk", re.I), "Used the kiosk"),
)


def actor_label(user):
    """Human-readable label for who performed an action."""
    if not user:
        return "System"
    member = get_linked_member(user)
    if member:
        return member.full_name
    getter = getattr(user, "get_full_name", None)
    if callable(getter):
        name = (getter() or "").strip()
        if name:
            return name
    return getattr(user, "username", None) or str(user)


def client_ip(request):
    if not request:
        return None
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def classify_path(path: str) -> str:
    """Map a URL path to a WebsiteAuditLog.Action value."""
    for pattern, action in _PATH_ACTION_RULES:
        if pattern.search(path or ""):
            return action
    return "OTHER"


def human_description(path: str, method: str = "", status_code=None) -> str:
    """Friendly description for middleware-captured requests."""
    for pattern, text in _PATH_DESCRIPTIONS:
        if pattern.search(path or ""):
            status_bit = f" (HTTP {status_code})" if status_code is not None else ""
            return f"{text}{status_bit}"
    status_bit = f" (HTTP {status_code})" if status_code is not None else ""
    return f"{method} {path}{status_bit}".strip()


def should_skip_path(path: str) -> bool:
    if not path:
        return True
    if path in _SKIP_EXACT:
        return True
    normalized = path if path.endswith("/") else path + "/"
    if normalized in _SKIP_EXACT:
        return True
    # Allow important mobile endpoints even though /api/mobile/ is skipped.
    if path.startswith("/api/mobile/") and any(s in path for s in _MOBILE_WATCH_SUFFIXES):
        return False
    return any(path.startswith(prefix) for prefix in _SKIP_PREFIXES)


def record_audit(
    action,
    *,
    actor=None,
    description="",
    request=None,
    request_method="",
    request_path="",
    object_type="",
    object_id="",
    metadata=None,
):
    """Persist one site-wide audit row. Never raises to callers."""
    from .models import WebsiteAuditLog

    try:
        path = request_path or (getattr(request, "path", "") if request else "")
        method = request_method or (getattr(request, "method", "") if request else "")
        WebsiteAuditLog.objects.create(
            action=action,
            actor=actor if getattr(actor, "is_authenticated", False) else None,
            actor_label=actor_label(actor),
            description=description or human_description(path, method),
            request_method=(method or "")[:10],
            request_path=(path or "")[:500],
            object_type=(object_type or "")[:80],
            object_id=str(object_id or "")[:64],
            metadata=metadata or {},
            ip_address=client_ip(request),
        )
    except Exception:
        logger.exception(
            "Failed to record website audit (action=%s path=%s)",
            action,
            request_path or getattr(request, "path", "?"),
        )


def describe_request_action(request, status_code=None) -> str:
    """Short human description for a mutating HTTP request."""
    method = getattr(request, "method", "") or ""
    path = getattr(request, "path", "") or ""
    return human_description(path, method, status_code)


def mark_audit_recorded(request):
    """Prevent middleware from double-logging when a view already recorded detail."""
    if request is not None:
        try:
            request._website_audit_recorded = True
        except Exception:
            pass
