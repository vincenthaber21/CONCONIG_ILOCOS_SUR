"""Session role chosen after login when a person has more than one role."""

from __future__ import annotations

import threading

SESSION_ROLE = "active_role"
SESSION_MEMBER_ID = "active_role_member_id"
POST_LOGIN_NEXT = "post_login_next"

_state = threading.local()

_EXEMPT_EXACT = {
    "/choose-role/",
    "/switch-role/",
    "/admin/logout/",
    "/kiosk/logout/",
}
_EXEMPT_PREFIXES = (
    "/static/",
    "/media/",
    "/api/mobile/",
    "/api/ingest/",
)

ROLE_CHOICES = (
    ("member", "bi-person", "Member services: loans, savings, and palay"),
    ("cashier", "bi-cash-coin", "Cashier desk and point of sale"),
    ("staff", "bi-person-badge", "Staff dashboard"),
    ("admin", "bi-shield-lock", "Full cooperative dashboard"),
    ("loan_officer", "bi-journal-text", "Loan desk"),
    ("committee", "bi-people", "Credit committee reviews"),
)


def current_request():
    return getattr(_state, "request", None)


def role_choice_meta(slug):
    for key, icon, blurb in ROLE_CHOICES:
        if key == slug:
            return icon, blurb
    return "bi-person-badge", "Open this role"


class ActiveRoleMiddleware:
    """Remember the current request and send multi-role logins to the role picker."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _state.request = request
        try:
            redirect_to = self._role_choice_redirect(request)
            if redirect_to is not None:
                from django.shortcuts import redirect

                return redirect(redirect_to)
            return self.get_response(request)
        finally:
            _state.request = None

    def _role_choice_redirect(self, request):
        path = request.path or "/"
        if not path.endswith("/"):
            path = path + "/"
        if path in _EXEMPT_EXACT or any(path.startswith(prefix) for prefix in _EXEMPT_PREFIXES):
            return None
        member = member_for_request(request)
        if member is None or not member.is_active:
            return None
        status = ensure_active_role(request, member)
        if status == "choose":
            return "choose_role"
        return None


def member_for_request(request):
    """Member whose login role this request should use."""
    user = getattr(request, "user", None)
    if user is not None and getattr(user, "is_authenticated", False):
        from helper.login_helper import get_linked_member

        return get_linked_member(user)
    member_id = request.session.get("member_id")
    if not member_id:
        return None
    from members.models import Member

    return Member.objects.filter(pk=member_id, is_active=True).select_related("member_role").first()


def ensure_active_role(request, member):
    """
    Set the session role when there is only one choice.

    Returns ``ok`` or ``choose``.
    """
    slugs = member.assigned_role_slugs()
    active = (request.session.get(SESSION_ROLE) or "").strip().lower()
    member_id = request.session.get(SESSION_MEMBER_ID)
    try:
        same_member = int(member_id) == int(member.pk)
    except (TypeError, ValueError):
        same_member = False
    if active in slugs and same_member:
        return "ok"
    if len(slugs) <= 1:
        request.session[SESSION_ROLE] = next(iter(slugs), "member")
        request.session[SESSION_MEMBER_ID] = member.pk
        return "ok"
    request.session.pop(SESSION_ROLE, None)
    request.session[SESSION_MEMBER_ID] = member.pk
    return "choose"


def clear_chosen_role(request):
    request.session.pop(SESSION_ROLE, None)


def activate_chosen_role(request, member, slug):
    request.session[SESSION_ROLE] = slug
    request.session[SESSION_MEMBER_ID] = member.pk


def normalize_role_slugs(data, fallback_slugs=None):
    """Read ``roles`` (list or comma string) or a single ``role`` from an API payload."""
    if not isinstance(data, dict):
        slugs = [str(item).strip().lower() for item in (fallback_slugs or ["member"]) if str(item).strip()]
        return slugs or ["member"]

    if "roles" in data:
        raw = data.get("roles")
        slugs = []
        if isinstance(raw, (list, tuple)):
            slugs = [str(item).strip().lower() for item in raw if str(item).strip()]
        elif isinstance(raw, str):
            slugs = [part.strip().lower() for part in raw.split(",") if part.strip()]
        unique = []
        for slug in slugs:
            if slug not in unique:
                unique.append(slug)
        return unique

    if data.get("role"):
        one = str(data.get("role") or "").strip().lower()
        if one:
            return [one]
    slugs = [str(item).strip().lower() for item in (fallback_slugs or ["member"]) if str(item).strip()]
    return slugs or ["member"]


def resolve_active_roles(slugs):
    """Return ``(role_objects, error)`` for active Role rows."""
    from members.models import Role

    found = []
    missing = []
    for slug in slugs:
        role = Role.objects.filter(slug__iexact=slug, is_active=True).first()
        if role is None:
            missing.append(slug)
        elif all(role.pk != existing.pk for existing in found):
            found.append(role)
    if missing:
        return None, "Unknown role: " + ", ".join(missing)
    if not found:
        return None, "Select at least one role."
    return found, None
