from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from .models import Member
from .role_permissions import sync_member_loan_permissions


@receiver(pre_save, sender=Member)
def stamp_member_registration_date(sender, instance, **kwargs):
    """Persist registration time on first save (loan eligibility waiting period)."""
    if instance.pk is None and not instance.date_joined:
        instance.date_joined = timezone.now()


@receiver(post_save, sender=Member)
def ensure_primary_role_is_assigned(sender, instance, **kwargs):
    """Keep the primary role inside the list of roles the person can open."""
    if not instance.member_role_id:
        return
    if instance.roles.filter(pk=instance.member_role_id).exists():
        return
    instance.roles.add(instance.member_role_id)
    instance.clear_assigned_role_cache()


@receiver(post_save, sender=Member)
def sync_loan_permissions_on_member_save(sender, instance, **kwargs):
    sync_member_loan_permissions(instance)
