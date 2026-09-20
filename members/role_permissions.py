"""Sync Django permissions when a Member's dashboard role changes."""

from django.contrib.auth.models import Permission

COMMITTEE_ROLE_SLUG = "committee"
LOAN_COMMITTEE_PERMISSION = ("loans", "can_approve")


def _loan_committee_permission():
    app_label, codename = LOAN_COMMITTEE_PERMISSION
    return Permission.objects.filter(
        content_type__app_label=app_label,
        codename=codename,
    ).first()


def sync_member_loan_permissions(member):
    """Grant or revoke loan committee approval permission for the linked User."""
    user = getattr(member, "user", None)
    if user is None or not user.pk:
        return

    perm = _loan_committee_permission()
    if perm is None:
        return

    if member.role == COMMITTEE_ROLE_SLUG:
        user.user_permissions.add(perm)
    else:
        user.user_permissions.remove(perm)
