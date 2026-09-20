import re
from urllib.parse import urlencode

from django.shortcuts import redirect
from django.urls import reverse
from django.contrib import messages


_COMMITTEE_UUID = r"[0-9a-fA-F-]{36}"
_LOANS_ONLY_ALLOWED_EXACT = {
    "/dashboard/loans/",
    "/dashboard/loans/steps/",
    "/dashboard/loans/settings/",
    "/admin/logout/",
    "/kiosk/logout/",
}
_LOANS_ONLY_ALLOWED_PREFIXES = ("/static/", "/media/")
_LOANS_ONLY_SKIP_PREFIXES = (
    "/static/",
    "/media/",
    "/.well-known/",
)
_LOANS_ONLY_SKIP_EXACT = {
    "/favicon.ico",
    "/favicon.png",
    "/robots.txt",
    "/apple-touch-icon.png",
    "/apple-touch-icon-precomposed.png",
}
_COMMITTEE_ALLOWED_REGEX = (
    re.compile(rf"^/dashboard/loans/steps/{_COMMITTEE_UUID}/?$"),
    re.compile(rf"^/dashboard/loans/steps/{_COMMITTEE_UUID}/committee-review/?$"),
    re.compile(rf"^/dashboard/loans/steps/{_COMMITTEE_UUID}/payment-option/?$"),
    re.compile(rf"^/dashboard/loans/steps/{_COMMITTEE_UUID}/payments/?$"),
    re.compile(rf"^/dashboard/loans/steps/{_COMMITTEE_UUID}/payments/receipts/?$"),
    re.compile(rf"^/dashboard/loans/steps/{_COMMITTEE_UUID}/payments/\d+/receipt/?$"),
)


def _normalize_path(path: str) -> str:
    if not path.endswith("/"):
        return path + "/"
    return path


def _bypass_loans_guard(path: str) -> bool:
    """Browser chrome and static files must not queue flash messages or hijack the page."""
    if path in _LOANS_ONLY_SKIP_EXACT:
        return True
    if any(path.startswith(prefix) for prefix in _LOANS_ONLY_SKIP_PREFIXES):
        return True
    return False


def _committee_loan_path_allowed(path: str) -> bool:
    normalized = _normalize_path(path)
    if normalized in _LOANS_ONLY_ALLOWED_EXACT or path in _LOANS_ONLY_ALLOWED_EXACT:
        return True
    if any(path.startswith(prefix) for prefix in _LOANS_ONLY_ALLOWED_PREFIXES):
        return True
    return any(pattern.match(path) for pattern in _COMMITTEE_ALLOWED_REGEX)


def _loan_officer_path_allowed(path: str) -> bool:
    normalized = _normalize_path(path)
    if normalized in _LOANS_ONLY_ALLOWED_EXACT or path in _LOANS_ONLY_ALLOWED_EXACT:
        return True
    if path.startswith("/dashboard/loans/"):
        return True
    if any(path.startswith(prefix) for prefix in _LOANS_ONLY_ALLOWED_PREFIXES):
        return True
    return False


class CommitteeLoanOnlyMiddleware:
    """Credit committee and loan officers may only use loan desk URLs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and getattr(user, "is_authenticated", False):
            from helper.login_helper import (
                is_committee_only_user,
                is_loan_officer_only_user,
            )

            path = request.path
            if _bypass_loans_guard(path):
                return self.get_response(request)
            if is_loan_officer_only_user(user) and not _loan_officer_path_allowed(path):
                return redirect("loans_overview")
            if is_committee_only_user(user) and not _committee_loan_path_allowed(path):
                return redirect("loans_overview")
        return self.get_response(request)


class SecureAdminMiddleware:
    """
    Middleware to secure Django admin by requiring authentication and admin permissions.
    This ensures only authenticated admin users can access /admin/
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        # Check if the request is for the admin panel
        # Exclude /admin/login/ and /admin/logout/ as they are handled separately
        excluded_paths = ['/admin/login/', '/admin/logout/']
        if request.path.startswith('/admin/') and request.path not in excluded_paths:
            # Check if user is authenticated
            if not request.user.is_authenticated:
                messages.warning(request, 'Please log in to access the admin panel.')
                login_url = reverse('root_login')
                next_url = request.get_full_path()
                return redirect(f'{login_url}?{urlencode({"next": next_url})}')
            
            # Check if user has admin permissions
            # Import here to avoid circular imports
            from admin_panel.views import can_access_django_admin
            if not can_access_django_admin(request.user):
                messages.error(request, 'You do not have permission to access the admin panel.')
                return redirect('root_login')
        
        response = self.get_response(request)
        return response


class WebsiteAuditMiddleware:
    """Record successful mutating staff/admin actions for the site audit trail.

    Login / logout are handled by auth signals. This middleware logs
    POST / PUT / PATCH / DELETE on dashboard, kiosk, admin, and important
    /api/ paths when the response is successful (status < 400).
    """

    WATCH_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
    WATCH_PREFIXES = (
        "/dashboard/",
        "/kiosk/",
        "/admin/",
        "/process-refund",
        "/api/",
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Capture actor before the view (logout clears request.user).
        user = getattr(request, "user", None)
        actor = user if user is not None and getattr(user, "is_authenticated", False) else None
        response = self.get_response(request)
        try:
            self._maybe_record(request, response, actor)
        except Exception:
            pass
        return response

    def _maybe_record(self, request, response, actor):
        method = getattr(request, "method", "") or ""
        if method not in self.WATCH_METHODS:
            return
        path = getattr(request, "path", "") or ""
        from .audit import (
            classify_path,
            describe_request_action,
            record_audit,
            should_skip_path,
        )

        if should_skip_path(path):
            return
        if not any(path.startswith(prefix) for prefix in self.WATCH_PREFIXES):
            # Root login POST is covered by user_logged_in / user_login_failed.
            return
        status = getattr(response, "status_code", 500) or 500
        if status >= 400:
            return
        # Prefer pre-view actor; fall back to post-view if still authenticated.
        if actor is None:
            user = getattr(request, "user", None)
            if user is not None and getattr(user, "is_authenticated", False):
                actor = user
        if actor is None:
            return
        # Avoid double-logging pure auth endpoints already covered by signals.
        if path in ("/admin/logout/", "/kiosk/logout/") or path.rstrip("/") in (
            "/admin/logout",
            "/kiosk/logout",
        ):
            return
        # Skip if the view already wrote a detailed audit row for this request.
        if getattr(request, "_website_audit_recorded", False):
            return
        action = classify_path(path)
        record_audit(
            action,
            actor=actor,
            description=describe_request_action(request, status),
            request=request,
            metadata={
                "status_code": status,
                "query": (request.META.get("QUERY_STRING") or "")[:200],
            },
        )