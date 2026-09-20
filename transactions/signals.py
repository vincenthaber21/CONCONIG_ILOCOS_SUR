from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Transaction
from .walk_in_customers import sync_walk_in_customer_discounts


@receiver(post_save, sender=Transaction)
def refresh_walk_in_discount_totals(sender, instance, **kwargs):
    if instance.walk_in_customer_id:
        sync_walk_in_customer_discounts(instance.walk_in_customer)
