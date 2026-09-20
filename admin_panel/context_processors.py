"""Inject kiosk branding into all Django templates (system name from Kiosk Config)."""


def kiosk_branding(request):
    try:
        from admin_panel.models import KioskConfig

        name = (KioskConfig.get().system_name or '').strip() or 'Self Checkout'
    except Exception:
        name = 'Self Checkout'
    return {'kiosk_system_name': name}


def pending_loan_requests(request):
    """Badge count of loan applications waiting for staff action."""
    count = 0
    try:
        user = getattr(request, "user", None)
        if user is None or not getattr(user, "is_authenticated", False):
            return {"pending_loan_request_count": 0}

        from helper.login_helper import (
            is_cashier_or_admin,
            is_committee_only_user,
            is_loan_officer_only_user,
            is_loans_only_user,
        )

        if not (
            is_cashier_or_admin(user)
            or is_loans_only_user(user)
        ):
            return {"pending_loan_request_count": 0}

        from loans.models import LoanApplication

        Status = LoanApplication.Status
        # Open requests / in-pipeline — not acquired, closed, or failed.
        count = (
            LoanApplication.objects.exclude(
                status__in=(
                    Status.DISBURSED,
                    Status.ACTIVE,
                    Status.FULLY_PAID,
                    Status.CLOSED,
                    Status.REJECTED,
                    Status.VERIFICATION_FAILED,
                    Status.DRAFT,
                )
            ).count()
        )
    except Exception:
        count = 0
    return {"pending_loan_request_count": count}


def committee_access(request):
    """Flags for templates: restricted loan-desk roles hide the main dashboard nav."""
    try:
        from helper.login_helper import (
            is_admin_user,
            is_cashier_or_admin,
            is_committee_only_user,
            is_loan_officer_only_user,
            is_loans_only_user,
        )

        user = getattr(request, "user", None)
        authenticated = bool(user and getattr(user, "is_authenticated", False))
        return {
            "is_committee_only": authenticated and is_committee_only_user(user),
            "is_loan_officer_only": authenticated and is_loan_officer_only_user(user),
            "is_loans_only": authenticated and is_loans_only_user(user),
            # Needed by Manage menu (Audit Trail) on every admin page.
            "is_admin_user": authenticated and is_admin_user(user),
            "is_admin": authenticated and is_cashier_or_admin(user),
        }
    except Exception:
        return {
            "is_committee_only": False,
            "is_loan_officer_only": False,
            "is_loans_only": False,
            "is_admin_user": False,
            "is_admin": False,
        }
