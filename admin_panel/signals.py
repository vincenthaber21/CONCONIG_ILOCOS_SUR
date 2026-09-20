"""Auth signals that feed the site-wide website audit trail."""

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .audit import actor_label, record_audit


@receiver(user_logged_in)
def audit_user_logged_in(sender, request, user, **kwargs):
    record_audit(
        "LOGIN",
        actor=user,
        description=f"{actor_label(user)} signed in",
        request=request,
        metadata={"username": getattr(user, "username", "")},
    )


@receiver(user_logged_out)
def audit_user_logged_out(sender, request, user, **kwargs):
    record_audit(
        "LOGOUT",
        actor=user,
        description=f"{actor_label(user)} signed out",
        request=request,
        metadata={"username": getattr(user, "username", "") if user else ""},
    )


@receiver(user_login_failed)
def audit_user_login_failed(sender, credentials, request, **kwargs):
    username = ""
    if isinstance(credentials, dict):
        username = credentials.get("username") or credentials.get("rfid") or ""
    record_audit(
        "LOGIN_FAILED",
        actor=None,
        description=f"Failed login attempt for '{username or 'unknown'}'",
        request=request,
        metadata={"username": username},
    )
