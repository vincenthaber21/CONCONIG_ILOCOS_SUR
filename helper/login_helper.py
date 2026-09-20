"""
login_helper.py
===============
Centralised helper for all authentication and login logic.

Covers:
    - Role checks  (is_admin, is_staff, is_cashier_or_admin, …)
    - Django-user authentication via username + password
    - RFID-card authentication (session-based for member-only accounts)
    - Session helpers  (store / read / clear member session)
    - Redirect-URL resolution per role
    - Access-control decorators  (admin_required, member_or_login_required, …)

Import this module from views, API endpoints, or any layer that needs
login/auth logic instead of duplicating the code.
"""

from __future__ import annotations

import logging
from functools import wraps
from typing import Optional

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.http import HttpRequest, JsonResponse
from django.shortcuts import redirect

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Lazy model import helper
# ─────────────────────────────────────────────────────────────────────────────

def _get_member_model():
    from members.models import Member  # noqa: PLC0415
    return Member


# ─────────────────────────────────────────────────────────────────────────────
# Role checks
# ─────────────────────────────────────────────────────────────────────────────

def is_admin_user(user: User) -> bool:
    """Return True if *user* is a superuser or a Member with role 'admin'."""
    if not user or not user.is_active:
        return False
    if user.is_superuser:
        return True
    try:
        member = _get_member_model().objects.get(user=user)
        return member.role == "admin" and member.is_active
    except Exception:
        return False


DASHBOARD_STAFF_ROLE_SLUGS = frozenset({"admin", "cashier", "staff"})
LOAN_OFFICER_ROLE_SLUG = "loan_officer"


def is_cashier_or_admin(user: User) -> bool:
    """Return True if *user* has cashier, admin, or staff role (or is superuser / Django staff)."""
    if not user or not user.is_active:
        return False
    if user.is_staff or user.is_superuser:
        return True
    try:
        member = _get_member_model().objects.get(user=user)
        return member.role in DASHBOARD_STAFF_ROLE_SLUGS and member.is_active
    except Exception:
        return False


def is_loan_officer_only_user(user: User) -> bool:
    """True when this login is Loan Officer only (no full admin dashboard)."""
    if not user or not user.is_active or user.is_superuser:
        return False
    try:
        member = _get_member_model().objects.get(user=user)
        return member.role == LOAN_OFFICER_ROLE_SLUG and member.is_active
    except Exception:
        return False


def is_loan_officer_user(user: User) -> bool:
    """Return True for the dedicated Loan Officer role (staff decisions + pipeline)."""
    if not user or not user.is_active:
        return False
    if user.is_superuser:
        return True
    try:
        member = _get_member_model().objects.get(user=user)
        return member.role == LOAN_OFFICER_ROLE_SLUG and member.is_active
    except Exception:
        return False


def is_staff_role(user: User) -> bool:
    """Return True if *user* is a Django-staff user or a Member with role 'staff'."""
    if not user or not user.is_active:
        return False
    if user.is_staff and not user.is_superuser:
        return True
    try:
        member = _get_member_model().objects.get(user=user)
        return member.role == "staff" and member.is_active
    except Exception:
        return False


def is_staff_user(user: User) -> bool:
    """Return True only for Member role 'staff' (not Django staff / superuser)."""
    if not user or not user.is_active:
        return False
    if user.is_staff or user.is_superuser:
        return False
    try:
        member = _get_member_model().objects.get(user=user)
        return member.role == "staff" and member.is_active
    except Exception:
        return False


def is_cashier_user(user: User) -> bool:
    """Return True only for Member role 'cashier' (not Django staff / superuser)."""
    if not user or not user.is_active:
        return False
    if user.is_staff or user.is_superuser:
        return False
    try:
        member = _get_member_model().objects.get(user=user)
        return member.role == "cashier" and member.is_active
    except Exception:
        return False


def is_committee_user(user: User) -> bool:
    """Return True for Member role 'committee' (credit committee approval)."""
    if not user or not user.is_active:
        return False
    try:
        member = _get_member_model().objects.get(user=user)
        return member.role == "committee" and member.is_active
    except Exception:
        return False


def is_committee_only_user(user: User) -> bool:
    """True when this login is Credit Committee only (no admin/cashier/staff console)."""
    if not user or not user.is_active or user.is_superuser:
        return False
    return is_committee_user(user)


def is_loans_only_user(user: User) -> bool:
    """Credit committee or loan officer — loan features only, no main dashboard."""
    return is_committee_only_user(user) or is_loan_officer_only_user(user)


def is_loan_desk_user(user: User) -> bool:
    """Roles that may open the cooperative loan desk (overview and pipeline)."""
    return (
        is_cashier_or_admin(user)
        or is_loan_officer_only_user(user)
        or is_committee_only_user(user)
    )


def get_linked_member(user: User):
    """
    Resolve the Member row for a Django User: prefer FK link, then Member.username
    matching User.username (covers legacy setups where the row exists but user_id was null).
    """
    if not user or not user.is_active:
        return None
    Member = _get_member_model()
    try:
        return Member.objects.select_related("member_role").get(user=user)
    except Member.DoesNotExist:
        pass
    uname = (getattr(user, "username", None) or "").strip()
    if not uname:
        return None
    return (
        Member.objects.select_related("member_role")
        .filter(username__iexact=uname, is_active=True)
        .first()
    )


def restricts_member_role_to_member_only(user: User) -> bool:
    """
    True if this login may only create or assign the plain 'member' role (dashboard Add/Edit).

    Includes Member roles staff and cashier even when the Django User has is_staff=True
    (that flag alone must not bypass cashier restrictions).
    """
    if not user or not user.is_active or user.is_superuser:
        return False
    m = get_linked_member(user)
    return bool(m and m.is_active and m.role in ("staff", "cashier"))


def can_access_django_admin(user: User) -> bool:
    """Return True only for superusers; blocks regular staff and Member role 'staff'."""
    if not user or not user.is_active:
        return False
    if user.is_superuser:
        return True
    if user.is_staff and not user.is_superuser:
        return False
    try:
        member = _get_member_model().objects.get(user=user)
        return member.role == "admin" and member.is_active
    except Exception:
        return False


def get_user_role(user: User) -> str:
    """
    Return a string describing the user's role:
        'superuser', 'admin', 'cashier', 'staff', 'committee', 'member', or 'unknown'
    """
    if not user or not user.is_active:
        return "unknown"
    if user.is_superuser:
        return "superuser"
    try:
        member = _get_member_model().objects.get(user=user)
        if member.is_active:
            return member.role  # 'admin', 'cashier', 'staff', 'committee', 'member'
    except Exception:
        pass
    return "unknown"


# ─────────────────────────────────────────────────────────────────────────────
# Redirect-URL resolution
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_ADMIN_URL = "/dashboard/"
_DEFAULT_COMMITTEE_URL = "/dashboard/loans/"
_DEFAULT_USER_URL = "/user-choice/"


def _is_safe_next_url(next_url: str) -> bool:
    """True if next_url is an internal path that is not Django admin."""
    return bool(next_url) and next_url.startswith("/") and not next_url.startswith("/admin")


def resolve_redirect_url(user: User, next_url: str = "") -> str:
    """
    Return the URL the user should land on after a successful login.

    Staff / cashier / admin → /dashboard/ (or a safe next_url).
    Loan officer / credit committee → /dashboard/loans/ (or a safe next_url).
    Regular members → /user-choice/ (always show the choice hub after login).
    """
    is_staff_login = is_admin_user(user) or is_cashier_or_admin(user)
    is_loans_only_login = is_loans_only_user(user)

    if is_staff_login:
        if _is_safe_next_url(next_url):
            return next_url
        return _DEFAULT_ADMIN_URL

    if is_loans_only_login:
        if _is_safe_next_url(next_url) and next_url.startswith("/dashboard/loans"):
            return next_url
        return _DEFAULT_COMMITTEE_URL

    return _DEFAULT_USER_URL


def resolve_redirect_url_for_member_only(next_url: str = "") -> str:
    """
    Member-only sessions (no Django User) always go to /user-choice/ after login.
    """
    return _DEFAULT_USER_URL


# ─────────────────────────────────────────────────────────────────────────────
# Session helpers for member-only accounts
# ─────────────────────────────────────────────────────────────────────────────

def store_member_session(request: HttpRequest, member) -> None:
    """Persist a member-only session (no Django User linked)."""
    request.session["member_id"] = member.id
    request.session["member_rfid"] = member.rfid_card_number
    request.session["member_role"] = member.role


def clear_member_session(request: HttpRequest) -> None:
    """Remove the member-only session keys."""
    for key in ("member_id", "member_rfid", "member_role"):
        request.session.pop(key, None)


def get_session_member(request: HttpRequest):
    """
    Return the Member from session if a valid member-only session exists,
    otherwise return None.
    """
    member_id = request.session.get("member_id")
    if not member_id:
        return None
    try:
        Member = _get_member_model()
        member = Member.objects.get(id=member_id, is_active=True)
        # Only honour sessions for plain 'member' role without a linked Django user
        if member.role == "member" and (member.user is None or not getattr(member.user, "username", None)):
            return member
    except Exception:
        pass
    return None


def is_member_session_valid(request: HttpRequest) -> bool:
    """Return True if a valid member-only session is active."""
    return get_session_member(request) is not None


# ─────────────────────────────────────────────────────────────────────────────
# Username + password login
# ─────────────────────────────────────────────────────────────────────────────

def login_with_credentials(
    request: HttpRequest,
    username: str,
    password: str,
    next_url: str = "",
) -> dict:
    """
    Authenticate *username* + *password* and log the user in.

    Returns a dict:
        {
            'success': True,
            'redirect_url': '/dashboard/',
            'user': <User instance>,
            'message': 'Welcome back, …',
        }
    or
        {
            'success': False,
            'error': '<reason>',
        }
    """
    if not username or not password:
        return {"success": False, "error": "Username and password are required."}

    # ── Standard Django password auth ────────────────────────────────────────
    user = authenticate(request, username=username, password=password)
    if user is not None:
        login(request, user)
        redirect_url = resolve_redirect_url(user, next_url)
        return {
            "success": True,
            "redirect_url": redirect_url,
            "user": user,
            "message": f"Welcome back, {user.get_full_name() or user.username}!",
        }

    # ── PIN fallbacks (only when exactly 4 digits supplied) ──────────────────
    if password.isdigit() and len(password) == 4:
        pin = password
        Member = _get_member_model()

        # Helper: attempt PIN check with lockout guard
        def _try_pin(member):
            if not member.is_active:
                return False
            if getattr(member, "is_pin_locked", False):
                return None  # signals "locked"
            if not member.pin_hash:
                return False
            ok = member.check_pin(pin)
            if not ok:
                member.pin_attempts = getattr(member, "pin_attempts", 0) + 1
                if member.pin_attempts >= 5:
                    member.is_pin_locked = True
                member.save(update_fields=["pin_attempts", "is_pin_locked"])
            else:
                if getattr(member, "pin_attempts", 0) > 0:
                    member.pin_attempts = 0
                    member.save(update_fields=["pin_attempts"])
            return ok

        def _login_member_with_pin_result(member, result):
            """
            After a successful PIN check: if the member has no linked Django User
            but has a privileged role (staff/admin/cashier), auto-create and link
            a Django User so the standard auth machinery can redirect them correctly.
            Returns a result dict on success, or None to continue falling through.
            """
            if not result:
                return None
            if member.user and member.user.is_active:
                login(request, member.user)
                redirect_url = resolve_redirect_url(member.user, next_url)
                return {
                    "success": True, "redirect_url": redirect_url,
                    "user": member.user,
                    "message": f"Welcome back, {member.full_name}!",
                }
            # No linked Django User — auto-create one for privileged roles
            if member.role in _PRIVILEGED_MEMBER_SLUGS:
                new_user = _create_linked_user_for_privileged_member(member)
                login(request, new_user)
                redirect_url = resolve_redirect_url(new_user, next_url)
                return {
                    "success": True, "redirect_url": redirect_url,
                    "user": new_user,
                    "message": f"Welcome back, {member.full_name}!",
                }
            # Plain member — keep member-only session
            store_member_session(request, member)
            return {
                "success": True,
                "redirect_url": resolve_redirect_url_for_member_only(next_url),
                "member_only": True,
                "message": f"Welcome back, {member.full_name}!",
            }

        # Fallback A: RFID used as username (member-only account)
        try:
            member = Member.objects.select_related("user").get(
                rfid_card_number=username, is_active=True
            )
            result = _try_pin(member)
            if result is None:
                return {"success": False, "error": "Account locked due to too many failed PIN attempts."}
            outcome = _login_member_with_pin_result(member, result)
            if outcome:
                return outcome
        except Member.DoesNotExist:
            pass

        # Fallback B: Member.username CharField used as login username
        try:
            member = Member.objects.select_related("user").get(
                username=username, is_active=True
            )
            result = _try_pin(member)
            if result is None:
                return {"success": False, "error": "Account locked due to too many failed PIN attempts."}
            outcome = _login_member_with_pin_result(member, result)
            if outcome:
                return outcome
        except Member.DoesNotExist:
            pass

        # Fallback C: Django User.username → linked Member PIN
        try:
            django_user = User.objects.get(username=username, is_active=True)
            member = Member.objects.get(user=django_user, is_active=True)
            result = _try_pin(member)
            if result is None:
                return {"success": False, "error": "Account locked due to too many failed PIN attempts."}
            if result:
                login(request, django_user)
                redirect_url = resolve_redirect_url(django_user, next_url)
                return {
                    "success": True, "redirect_url": redirect_url,
                    "user": django_user,
                    "message": f"Welcome back, {django_user.get_full_name() or django_user.username}!",
                }
        except (User.DoesNotExist, Member.DoesNotExist):
            pass

    return {"success": False, "error": "Invalid username or password. Please try again."}


# Role slugs that require a Django User for dashboard / staff flows (PIN + RFID).
_PRIVILEGED_MEMBER_SLUGS = frozenset({"admin", "cashier", "staff", "loan_officer", "committee"})


def _member_has_active_django_user(member) -> bool:
    """True when Member links to an active Django User with a non-empty username."""
    user = getattr(member, "user", None)
    if user is None or not user.is_active:
        return False
    return bool((getattr(user, "username", None) or "").strip())


def _create_linked_user_for_privileged_member(member):
    """
    Create a Django User, attach to *member*, and return the user.
    Mirrors the PIN-login auto-provision path for staff/cashier/admin.
    """
    django_username = (getattr(member, "username", None) or "").strip() or f"member_{member.pk}"
    base_username = django_username
    counter = 1
    while User.objects.filter(username=django_username).exists():
        django_username = f"{base_username}_{counter}"
        counter += 1
    role_slug = member.role
    new_user = User.objects.create_user(
        username=django_username,
        first_name=member.first_name,
        last_name=member.last_name,
        email=member.email or "",
        password=None,
    )
    new_user.is_staff = role_slug == "admin"
    new_user.save(update_fields=["is_staff"])
    member.user = new_user
    member.save(update_fields=["user"])
    return new_user


# ─────────────────────────────────────────────────────────────────────────────
# RFID login
# ─────────────────────────────────────────────────────────────────────────────

def login_with_rfid(
    request: HttpRequest,
    rfid: str,
    next_url: str = "",
) -> dict:
    """
    Log in using an RFID card number only (no PIN required).
    Used by the quick-scan RFID login endpoint.

    Returns the same dict shape as :func:`login_with_credentials`.
    """
    rfid = (rfid or "").strip()
    if not rfid:
        return {"success": False, "error": "RFID is required."}

    Member = _get_member_model()
    member = (
        Member.objects.select_related("user", "member_role")
        .filter(rfid_card_number__iexact=rfid, is_active=True)
        .first()
    )
    if not member:
        return {"success": False, "error": "Member not found or inactive."}

    slug = member.role
    has_user = _member_has_active_django_user(member)

    # Kiosk session: plain members (and custom / reseller roles) without Django login
    if slug == "member" and not has_user:
        store_member_session(request, member)
        redirect_url = resolve_redirect_url_for_member_only(next_url)
        return {
            "success": True,
            "redirect_url": redirect_url,
            "member_only": True,
            "member": member,
            "message": f"Welcome back, {member.full_name}!",
        }

    if slug not in _PRIVILEGED_MEMBER_SLUGS and not has_user:
        store_member_session(request, member)
        redirect_url = resolve_redirect_url_for_member_only(next_url)
        return {
            "success": True,
            "redirect_url": redirect_url,
            "member_only": True,
            "member": member,
            "message": f"Welcome back, {member.full_name}!",
        }

    # Staff / cashier / admin must use Django auth — auto-create user if missing (same as PIN flow)
    if slug in _PRIVILEGED_MEMBER_SLUGS:
        if not has_user:
            new_user = _create_linked_user_for_privileged_member(member)
            login(request, new_user)
            redirect_url = resolve_redirect_url(new_user, next_url)
            return {
                "success": True,
                "redirect_url": redirect_url,
                "member_only": False,
                "user": new_user,
                "member": member,
                "message": f"Welcome back, {member.full_name}!",
            }
        login(request, member.user)
        redirect_url = resolve_redirect_url(member.user, next_url)
        return {
            "success": True,
            "redirect_url": redirect_url,
            "member_only": False,
            "user": member.user,
            "member": member,
            "message": f"Welcome back, {member.user.get_full_name() or member.user.username}!",
        }

    if not has_user:
        return {"success": False, "error": "No active user account linked to this RFID card."}

    login(request, member.user)
    redirect_url = resolve_redirect_url(member.user, next_url)
    return {
        "success": True,
        "redirect_url": redirect_url,
        "member_only": False,
        "user": member.user,
        "member": member,
        "message": f"Welcome back, {member.user.get_full_name() or member.user.username}!",
    }


def login_member_only_with_pin(
    request: HttpRequest,
    rfid: str,
    pin: str,
    next_url: str = "",
) -> dict:
    """
    Authenticate a member-only account using RFID + PIN and create a session.
    Only applies to members with role='member' and no linked Django User.
    """
    rfid = (rfid or "").strip()
    if not rfid or not pin:
        return {"success": False, "error": "RFID and PIN are required."}

    try:
        Member = _get_member_model()
        member = Member.objects.get(
            rfid_card_number__iexact=rfid,
            is_active=True,
            member_role__slug="member",
        )
    except Member.DoesNotExist:
        return {"success": False, "error": "Member not found or inactive."}

    # Only for accounts without a Django user
    if member.user is not None and getattr(member.user, "username", None):
        return {"success": False, "error": "Please use your username to log in."}

    if not member.check_pin(pin):
        return {"success": False, "error": "Incorrect PIN. Please try again."}

    store_member_session(request, member)
    redirect_url = resolve_redirect_url_for_member_only(next_url)
    return {
        "success": True,
        "redirect_url": redirect_url,
        "member_only": True,
        "member": member,
        "message": f"Welcome back, {member.full_name}!",
    }


def validate_rfid(rfid: str) -> dict:
    """
    Validate an RFID card and return the linked username (if any) without
    actually logging the user in. Useful for the pre-login gate page.

    Returns:
        ok(username=...) — linked active Django user → continue to password login
        ok(member_only=True, name=...) — member without Django user
        err(...) — not found / inactive / misconfigured
    """
    rfid = (rfid or "").strip()
    if not rfid:
        return {"success": False, "error": "RFID is required.", "code": "rfid_missing"}

    Member = _get_member_model()
    member = (
        Member.objects.select_related("user", "member_role")
        .filter(rfid_card_number__iexact=rfid, is_active=True)
        .first()
    )
    if not member:
        return {"success": False, "error": "Member not found or inactive.", "code": "member_not_found"}

    slug = member.role
    has_user = _member_has_active_django_user(member)

    if slug == "member" and not has_user:
        return {"success": True, "member_only": True, "name": member.full_name}

    if slug not in _PRIVILEGED_MEMBER_SLUGS and not has_user:
        return {"success": True, "member_only": True, "name": member.full_name}

    if slug in _PRIVILEGED_MEMBER_SLUGS and not has_user:
        proposed = (member.username or "").strip() or f"member_{member.pk}"
        return {"success": True, "username": proposed, "name": member.full_name}

    if not has_user:
        return {"success": False, "error": "No active user linked to this RFID.", "code": "no_user_linked"}

    return {"success": True, "username": member.user.username, "name": member.full_name}


# ─────────────────────────────────────────────────────────────────────────────
# Logout
# ─────────────────────────────────────────────────────────────────────────────

def logout_user(request: HttpRequest) -> None:
    """Log out the Django user and clear any member-only session data."""
    clear_member_session(request)
    logout(request)


# ─────────────────────────────────────────────────────────────────────────────
# Access-control decorators
# ─────────────────────────────────────────────────────────────────────────────

def admin_required(view_func):
    """Decorator: only allows users with admin role (or superuser)."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.user.is_authenticated and is_admin_user(request.user):
            return view_func(request, *args, **kwargs)
        messages.warning(request, "You do not have permission to access this page.")
        return redirect("root_login")
    return _wrapped


def cashier_or_admin_required(view_func):
    """Decorator: allows cashier or admin roles."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.user.is_authenticated and is_cashier_or_admin(request.user):
            return view_func(request, *args, **kwargs)
        messages.warning(request, "You do not have permission to access this page.")
        return redirect("root_login")
    return _wrapped


def member_or_login_required(view_func):
    """
    Decorator: allows access if the user is authenticated via Django auth
    OR has a valid member-only session.
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.user.is_authenticated:
            return view_func(request, *args, **kwargs)
        if is_member_session_valid(request):
            return view_func(request, *args, **kwargs)
        messages.warning(request, "Please log in to access this page.")
        return redirect("root_login")
    return _wrapped


def staff_or_above_required(view_func):
    """Decorator: allows staff, cashier, admin, committee, and superuser roles."""
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if request.user.is_authenticated:
            role = get_user_role(request.user)
            if role in ("staff", "cashier", "admin", "committee", "superuser"):
                return view_func(request, *args, **kwargs)
        messages.warning(request, "You do not have permission to access this page.")
        return redirect("root_login")
    return _wrapped


# ─────────────────────────────────────────────────────────────────────────────
# JSON-API helpers (for AJAX / fetch endpoints)
# ─────────────────────────────────────────────────────────────────────────────

def rfid_login_json_response(request: HttpRequest, rfid: str, next_url: str = "") -> JsonResponse:
    """
    Full RFID-card login that returns a JsonResponse.
    Drop-in replacement for the inline api_rfid_login logic.
    """
    result = login_with_rfid(request, rfid, next_url)

    if not result["success"]:
        return JsonResponse({"success": False, "error": result["error"]})

    member = result.get("member")
    response_data: dict = {
        "success": True,
        "message": result["message"],
        "redirect_url": result["redirect_url"],
    }

    if result.get("member_only"):
        response_data["member_only"] = True
        if member:
            from members.utils import mask_rfid
            response_data["member"] = {
                "id": member.id,
                "name": member.full_name,
                "rfid": mask_rfid(member.rfid_card_number),
            }
    else:
        user = result.get("user")
        if user:
            response_data["user"] = {
                "username": user.username,
                "name": user.get_full_name() or user.username,
            }

    return JsonResponse(response_data)


def rfid_validate_json_response(rfid: str) -> JsonResponse:
    """
    RFID pre-login validation that returns a JsonResponse.
    Drop-in replacement for the inline api_validate_rfid_login logic.
    """
    result = validate_rfid(rfid)
    return JsonResponse(result)
