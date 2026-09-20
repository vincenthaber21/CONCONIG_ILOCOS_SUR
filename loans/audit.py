"""Immutable audit logging for loan applications (security / compliance).

Logging must never break loan workflows — failures are swallowed and logged.
"""

import logging

from helper.login_helper import get_linked_member

logger = logging.getLogger(__name__)


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


def record_loan_audit(
    application,
    action,
    *,
    actor=None,
    description="",
    metadata=None,
    request=None,
):
    """Persist one audit row for a loan application."""
    from .models import LoanApplicationAuditLog

    try:
        LoanApplicationAuditLog.objects.create(
            application=application,
            action=action,
            actor=actor,
            actor_label=actor_label(actor),
            description=description,
            metadata=metadata or {},
            ip_address=client_ip(request),
        )
    except Exception:
        logger.exception(
            "Failed to record loan audit for application %s (action=%s)",
            getattr(application, "pk", "?"),
            action,
        )

    # Also write a high-level site security trail entry for admins.
    try:
        from admin_panel.audit import record_audit as record_website_audit

        record_website_audit(
            "LOAN",
            actor=actor,
            description=description or f"Loan action: {action}",
            request=request,
            object_type="LoanApplication",
            object_id=getattr(application, "pk", ""),
            metadata={
                "loan_action": action,
                "application_id": str(getattr(application, "pk", "")),
                **(metadata or {}),
            },
        )
    except Exception:
        logger.exception("Failed to mirror loan audit to website trail")
