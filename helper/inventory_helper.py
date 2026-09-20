"""
inventory_helpers.py

Unified helper layer for inventory stock operations.
Wraps Product model methods with atomic transactions, deduplication guards,
notification triggering, and structured result objects — so views, signals,
and management commands all share the same safe path.

Usage:
    from inventory.inventory_helpers import StockManager

    result = StockManager.add_stock(product, quantity=10, notes="Supplier restock")
    if result.success:
        print(result.message)

    result = StockManager.reduce_stock(product, quantity=2, notes="POS sale")
    if not result.success:
        print(result.error)   # e.g. "Insufficient stock"
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from django.core.cache import cache
from django.db import transaction

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result objects
# ---------------------------------------------------------------------------

class StockEventType(str, Enum):
    RESTOCKED        = "restocked"
    REDUCED          = "reduced"
    ADJUSTED         = "adjusted"
    LOW_STOCK        = "low_stock"
    OUT_OF_STOCK     = "out_of_stock"
    ACCESS_TRACKED   = "access_tracked"
    NOTIFICATION_SENT = "notification_sent"


@dataclass
class StockResult:
    """
    Structured return value from every StockManager operation.

    Attributes:
        success        True if the core operation completed without error.
        message        Human-readable summary (suitable for log lines or API responses).
        error          Non-empty string when success=False; empty otherwise.
        stock_before   Stock level before the operation.
        stock_after    Stock level after the operation.
        events         List of StockEventType values that were triggered.
        notification_sent  True if at least one email notification was dispatched.
        attempt_count  Populated by track_failed_access(); 0 otherwise.
    """
    success: bool
    message: str = ""
    error: str = ""
    stock_before: int = 0
    stock_after: int = 0
    events: list = field(default_factory=list)
    notification_sent: bool = False
    attempt_count: int = 0

    # Convenience properties
    @property
    def went_out_of_stock(self) -> bool:
        return StockEventType.OUT_OF_STOCK in self.events

    @property
    def went_low_stock(self) -> bool:
        return StockEventType.LOW_STOCK in self.events


# ---------------------------------------------------------------------------
# Notification deduplication helpers
# ---------------------------------------------------------------------------

_DEDUP_TIMEOUT = 300   # seconds — suppress duplicate notifications within 5 min


def _dedup_key(product_id: int, event: str) -> str:
    return f"inv_notif_dedup_{event}_{product_id}"


def _should_notify(product_id: int, event: str) -> bool:
    """Return True only if no notification for this event was sent recently."""
    key = _dedup_key(product_id, event)
    if cache.get(key):
        return False
    cache.set(key, 1, _DEDUP_TIMEOUT)
    return True


def _clear_dedup(product_id: int, event: str) -> None:
    cache.delete(_dedup_key(product_id, event))


# ---------------------------------------------------------------------------
# StockTransaction recorder (avoids repeating this in every method)
# ---------------------------------------------------------------------------

def _record_transaction(product, tx_type: str, quantity: int,
                        before: int, after: int, notes: str = "") -> None:
    """Create a StockTransaction row.  Silently skips if the model is absent."""
    try:
        from inventory.models import StockTransaction  # adjust app label if needed
        StockTransaction.objects.create(
            product=product,
            transaction_type=tx_type,
            quantity=quantity,
            stock_before=before,
            stock_after=after,
            notes=notes,
        )
    except Exception as exc:
        logger.warning("Could not record StockTransaction for product %s: %s",
                       product.id, exc)


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _trigger_low_stock_notification(product) -> bool:
    """Send low-stock warning email with deduplication guard."""
    from inventory.utils import send_low_stock_warning   # your existing util
    if _should_notify(product.id, "low_stock"):
        sent = send_low_stock_warning(product)
        if not sent:
            _clear_dedup(product.id, "low_stock")   # allow retry next time
        return sent
    return False


def _trigger_out_of_stock_notification(product) -> bool:
    """Send out-of-stock alert email with deduplication guard."""
    from inventory.utils import send_out_of_stock_notification
    if _should_notify(product.id, "out_of_stock"):
        sent = send_out_of_stock_notification(product)
        if not sent:
            _clear_dedup(product.id, "out_of_stock")
        return sent
    return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class StockManager:
    """
    Thread-safe, atomic stock operations with automatic notification triggering.

    All public methods accept:
        product  – Product model instance
        quantity – Non-negative integer
        notes    – Optional string stored on the StockTransaction record

    All public methods return a StockResult.
    """

    # ------------------------------------------------------------------
    # add_stock
    # ------------------------------------------------------------------

    @staticmethod
    def add_stock(product, quantity: int, notes: str = "") -> StockResult:
        """
        Increase stock by *quantity*.

        Side-effects:
        - Creates a StockTransaction('in') record.
        - Resets out-of-stock attempt counter so the next depletion fires
          a fresh notification.
        - Clears deduplication flags so the next low/out-of-stock event
          sends a new email.
        """
        if quantity <= 0:
            return StockResult(
                success=False,
                error=f"quantity must be positive (got {quantity})",
            )

        events: list[StockEventType] = []

        try:
            with transaction.atomic():
                # Re-fetch with a row-level lock to prevent race conditions
                from inventory.models import Product
                locked = Product.objects.select_for_update().get(pk=product.pk)
                before = locked.stock_quantity
                after  = before + quantity

                locked.stock_quantity = after
                locked.save(update_fields=["stock_quantity", "updated_at"])

                _record_transaction(locked, "in", quantity, before, after, notes)
                events.append(StockEventType.RESTOCKED)

            # Reset counters/dedup now that stock is back
            _clear_dedup(product.id, "low_stock")
            _clear_dedup(product.id, "out_of_stock")

            from inventory.utils import reset_out_of_stock_attempts
            reset_out_of_stock_attempts(product)

            # Refresh the in-memory product so callers see updated values
            product.refresh_from_db()

            return StockResult(
                success=True,
                message=f"Added {quantity} units to '{product.name}'. "
                        f"Stock: {before} → {after}.",
                stock_before=before,
                stock_after=after,
                events=events,
            )

        except Exception as exc:
            logger.exception("add_stock failed for product %s: %s", product.id, exc)
            return StockResult(
                success=False,
                error=str(exc),
                events=events,
            )

    # ------------------------------------------------------------------
    # reduce_stock
    # ------------------------------------------------------------------

    @staticmethod
    def reduce_stock(product, quantity: int, notes: str = "") -> StockResult:
        """
        Decrease stock by *quantity*.

        Side-effects:
        - Refuses the operation (success=False) if stock would go negative.
        - Creates a StockTransaction('out') record.
        - Sends low-stock or out-of-stock email notifications as needed.
        """
        if quantity <= 0:
            return StockResult(
                success=False,
                error=f"quantity must be positive (got {quantity})",
            )

        events: list[StockEventType] = []
        notification_sent = False

        try:
            with transaction.atomic():
                from inventory.models import Product
                locked = Product.objects.select_for_update().get(pk=product.pk)
                before = locked.stock_quantity

                if before < quantity:
                    return StockResult(
                        success=False,
                        error=(f"Insufficient stock for '{locked.name}'. "
                               f"Requested: {quantity}, available: {before}."),
                        stock_before=before,
                        stock_after=before,
                    )

                after = before - quantity
                locked.stock_quantity = after
                locked.save(update_fields=["stock_quantity", "updated_at"])
                _record_transaction(locked, "out", quantity, before, after, notes)
                events.append(StockEventType.REDUCED)

            # Refresh so property checks below use fresh values
            product.refresh_from_db()

            # --- Notifications (outside the transaction to avoid long locks) ---
            if product.is_out_of_stock:
                events.append(StockEventType.OUT_OF_STOCK)
                notification_sent = _trigger_out_of_stock_notification(product)
            elif product.is_low_stock:
                events.append(StockEventType.LOW_STOCK)
                notification_sent = _trigger_low_stock_notification(product)

            if notification_sent:
                events.append(StockEventType.NOTIFICATION_SENT)

            return StockResult(
                success=True,
                message=(f"Reduced '{product.name}' by {quantity} units. "
                         f"Stock: {before} → {after}."),
                stock_before=before,
                stock_after=after,
                events=events,
                notification_sent=notification_sent,
            )

        except Exception as exc:
            logger.exception("reduce_stock failed for product %s: %s", product.id, exc)
            return StockResult(
                success=False,
                error=str(exc),
                events=events,
            )

    # ------------------------------------------------------------------
    # adjust_stock  (absolute set)
    # ------------------------------------------------------------------

    @staticmethod
    def adjust_stock(product, new_quantity: int, notes: str = "") -> StockResult:
        """
        Set stock to an absolute value (inventory count / correction).

        Side-effects:
        - Creates a StockTransaction('adjustment') record.
        - Triggers appropriate notifications based on the new level.
        - Resets dedup counters if the new quantity is above the low-stock threshold.
        """
        if new_quantity < 0:
            return StockResult(
                success=False,
                error=f"new_quantity cannot be negative (got {new_quantity})",
            )

        events: list[StockEventType] = []
        notification_sent = False

        try:
            with transaction.atomic():
                from inventory.models import Product
                locked = Product.objects.select_for_update().get(pk=product.pk)
                before = locked.stock_quantity
                delta  = new_quantity - before

                locked.stock_quantity = new_quantity
                locked.save(update_fields=["stock_quantity", "updated_at"])
                _record_transaction(locked, "adjustment", abs(delta),
                                    before, new_quantity, notes)
                events.append(StockEventType.ADJUSTED)

            product.refresh_from_db()

            # Reset dedup only when moving back above threshold
            if new_quantity > product.low_stock_threshold:
                _clear_dedup(product.id, "low_stock")
                _clear_dedup(product.id, "out_of_stock")
                from inventory.utils import reset_out_of_stock_attempts
                reset_out_of_stock_attempts(product)
            elif product.is_out_of_stock:
                events.append(StockEventType.OUT_OF_STOCK)
                notification_sent = _trigger_out_of_stock_notification(product)
            elif product.is_low_stock:
                events.append(StockEventType.LOW_STOCK)
                notification_sent = _trigger_low_stock_notification(product)

            if notification_sent:
                events.append(StockEventType.NOTIFICATION_SENT)

            return StockResult(
                success=True,
                message=(f"Adjusted '{product.name}' stock: {before} → {new_quantity} "
                         f"(Δ{delta:+d})."),
                stock_before=before,
                stock_after=new_quantity,
                events=events,
                notification_sent=notification_sent,
            )

        except Exception as exc:
            logger.exception("adjust_stock failed for product %s: %s", product.id, exc)
            return StockResult(
                success=False,
                error=str(exc),
                events=events,
            )

    # ------------------------------------------------------------------
    # track_failed_access
    # ------------------------------------------------------------------

    @staticmethod
    def track_failed_access(product) -> StockResult:
        """
        Record a customer's failed attempt to access an out-of-stock product.
        Delegates counter logic and notification to track_out_of_stock_attempt().

        Returns a StockResult with attempt_count populated.
        """
        events: list[StockEventType] = [StockEventType.ACCESS_TRACKED]
        notification_sent = False

        try:
            from inventory.utils import track_out_of_stock_attempt
            attempt_count, notification_sent = track_out_of_stock_attempt(product)

            if notification_sent:
                events.append(StockEventType.NOTIFICATION_SENT)

            return StockResult(
                success=True,
                message=(f"Access attempt #{attempt_count} recorded for "
                         f"'{product.name}'."),
                stock_before=product.stock_quantity,
                stock_after=product.stock_quantity,
                events=events,
                notification_sent=notification_sent,
                attempt_count=attempt_count,
            )

        except Exception as exc:
            logger.exception("track_failed_access failed for product %s: %s",
                             product.id, exc)
            return StockResult(
                success=False,
                error=str(exc),
                events=events,
            )

    # ------------------------------------------------------------------
    # bulk_reduce  (e.g. after a multi-item POS sale)
    # ------------------------------------------------------------------

    @staticmethod
    def bulk_reduce(items: list[tuple], notes: str = "") -> dict:
        """
        Reduce stock for multiple products in a single atomic transaction.

        All reductions are validated first; if any would fail (e.g. insufficient
        stock or invalid quantity) the entire operation is aborted before any
        write occurs.  Notifications are fired after the transaction commits.

        Args:
            items: List of (product, quantity) tuples.
            notes: Shared notes string for all transactions.

        Returns a dict:
            {
                "success": bool,            # True only if ALL reductions succeeded
                "results": [StockResult],   # One per item, in input order
                "errors":  [str],           # Non-empty strings for failed items
            }
        """
        from inventory.models import Product

        results = []
        errors  = []

        # --- Pre-flight validation (no DB writes yet) ---
        for product, quantity in items:
            if quantity <= 0:
                errors.append(
                    f"{product.name}: quantity must be positive (got {quantity})"
                )

        if errors:
            for product, quantity in items:
                results.append(StockResult(
                    success=False,
                    error=f"bulk_reduce aborted before any write: {errors[0]}",
                    stock_before=product.stock_quantity,
                    stock_after=product.stock_quantity,
                ))
            return {"success": False, "results": results, "errors": errors}

        # --- Single atomic block for all writes ---
        snapshots = []   # (product, quantity, before, after) for post-commit work
        try:
            with transaction.atomic():
                for product, quantity in items:
                    locked = Product.objects.select_for_update().get(pk=product.pk)
                    before = locked.stock_quantity

                    if before < quantity:
                        # Raising here rolls back all previous writes in this block
                        raise ValueError(
                            f"Insufficient stock for '{locked.name}'. "
                            f"Requested: {quantity}, available: {before}."
                        )

                    after = before - quantity
                    locked.stock_quantity = after
                    locked.save(update_fields=["stock_quantity", "updated_at"])
                    _record_transaction(locked, "out", quantity, before, after, notes)
                    snapshots.append((product, quantity, before, after))

        except Exception as exc:
            error_msg = str(exc)
            logger.exception("bulk_reduce failed, all changes rolled back: %s", error_msg)
            errors.append(error_msg)
            for product, quantity in items:
                results.append(StockResult(
                    success=False,
                    error=error_msg,
                    stock_before=product.stock_quantity,
                    stock_after=product.stock_quantity,
                ))
            return {"success": False, "results": results, "errors": errors}

        # --- Post-commit: refresh, build results, fire notifications ---
        for product, quantity, before, after in snapshots:
            product.refresh_from_db()
            events = [StockEventType.REDUCED]
            notification_sent = False

            if product.is_out_of_stock:
                events.append(StockEventType.OUT_OF_STOCK)
                notification_sent = _trigger_out_of_stock_notification(product)
            elif product.is_low_stock:
                events.append(StockEventType.LOW_STOCK)
                notification_sent = _trigger_low_stock_notification(product)

            if notification_sent:
                events.append(StockEventType.NOTIFICATION_SENT)

            results.append(StockResult(
                success=True,
                message=(f"Reduced '{product.name}' by {quantity} units. "
                         f"Stock: {before} → {after}."),
                stock_before=before,
                stock_after=after,
                events=events,
                notification_sent=notification_sent,
            ))

        return {"success": True, "results": results, "errors": []}

    # ------------------------------------------------------------------
    # stock_status  (read-only summary, no side-effects)
    # ------------------------------------------------------------------

    @staticmethod
    def stock_status(product) -> dict:
        """
        Return a plain dict summarising the current stock state.
        Safe to call at any time — no writes, no notifications.
        """
        product.refresh_from_db()
        return {
            "product_id":         product.pk,
            "product_name":       product.name,
            "stock_quantity":     product.stock_quantity,
            "low_stock_threshold": product.low_stock_threshold,
            "is_low_stock":       product.is_low_stock,
            "is_out_of_stock":    product.is_out_of_stock,
            "stock_deficit":      product.stock_deficit,
        }