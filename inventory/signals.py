"""
Signals for inventory management
"""
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from .models import Product
from .utils import send_out_of_stock_notification, reset_out_of_stock_attempts, send_low_stock_warning


@receiver(pre_save, sender=Product)
def track_stock_before_save(sender, instance, **kwargs):
    """Store the previous stock quantity before save"""
    if instance.pk:
        try:
            old_instance = Product.objects.get(pk=instance.pk)
            instance._previous_stock_quantity = old_instance.stock_quantity
        except Product.DoesNotExist:
            instance._previous_stock_quantity = None
    else:
        instance._previous_stock_quantity = None


@receiver(post_save, sender=Product)
def ensure_giveaway_profile(sender, instance, created, **kwargs):
    """All active products are eligible for staff Record Giveaway."""
    from .utils import ensure_product_giveaway_active

    ensure_product_giveaway_active(instance)


@receiver(post_save, sender=Product)
def check_out_of_stock(sender, instance, created, **kwargs):
    """
    Check if product stock has reached 0 or low stock threshold and send notifications.
    Only sends notification if stock was just reduced to threshold/0 (not if it was already there).
    Also resets attempt counter when stock is added.
    """
    # Only check if product is active
    if not instance.is_active:
        return
    
    # Get previous stock quantity
    previous_stock = getattr(instance, '_previous_stock_quantity', None)
    
    # Check if stock was increased (admin added stock)
    # Reset attempt counter if stock went from 0 to > 0, or from low to higher
    if previous_stock is not None:
        if previous_stock == 0 and instance.stock_quantity > 0:
            # Stock was added from 0 - reset attempts
            reset_out_of_stock_attempts(instance)
        elif previous_stock > 0 and instance.stock_quantity > previous_stock:
            # Stock was increased - reset attempts (admin restocked)
            reset_out_of_stock_attempts(instance)
    
    # Check if stock is at or below the low stock threshold
    # Send warning continuously while stock remains below threshold
    if previous_stock is not None:
        was_above_threshold = previous_stock > instance.low_stock_threshold
        is_at_or_below_threshold = instance.stock_quantity <= instance.low_stock_threshold
        is_above_threshold = instance.stock_quantity > instance.low_stock_threshold
        
        # Send warning if stock is below threshold and product is not out of stock
        if is_at_or_below_threshold and instance.stock_quantity > 0:
            # Send warning every time:
            # 1. Stock just crossed threshold (first time), OR
            # 2. Stock was already below threshold and continues to be reduced
            stock_reduced = previous_stock > instance.stock_quantity
            
            if was_above_threshold or (not was_above_threshold and stock_reduced):
                # Send warning immediately - no cooldown
                send_low_stock_warning(instance)
    
    # Check if stock just reached 0
    # We want to notify if:
    # 1. Current stock is 0
    # 2. Previous stock was > 0 (meaning it just ran out)
    # OR if it's a new product created with 0 stock
    if instance.stock_quantity == 0:
        if created:
            # New product created with 0 stock - notify admin
            send_out_of_stock_notification(instance)
        elif previous_stock is not None and previous_stock > 0:
            # Stock was reduced from > 0 to 0 - notify admin
            send_out_of_stock_notification(instance)

