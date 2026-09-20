"""
database_helper.py
==================
Centralised helper layer for safe, atomic database operations across all apps.

Covers:
    - Transaction creation & completion  (transactions app)
    - TransactionItem saving             (transactions app)
    - Member balance deduction / credit  (members app)
    - Product stock deduction            (inventory app)
    - OTP creation / validation          (mobile_api app)
    - Generic safe-get / get-or-create   (shared utilities)
    - Bulk-save with rollback            (shared utilities)

All public functions return a plain ``DBResult`` dataclass so callers never
need to catch exceptions directly — check ``result.success`` instead.

Usage::

    from helper.database_helper import (
        save_transaction,
        complete_transaction,
        deduct_member_balance,
        deduct_product_stock,
        safe_get,
        bulk_save,
    )

    result = save_transaction(member=member, payment_method='debit', items=cart)
    if result.success:
        txn = result.data['transaction']
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional

from django.db import transaction, IntegrityError, DatabaseError
from django.utils import timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared result object
# ---------------------------------------------------------------------------

@dataclass
class DBResult:
    """
    Unified return value from every database_helper operation.

    Attributes:
        success   True when the operation completed without error.
        data      Dict containing any returned objects or computed values.
        error     Non-empty string describing what went wrong (success=False).
        code      Short machine-readable error key (e.g. ``"insufficient_balance"``).
    """
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    code: str = ""

    # Convenience factory methods
    @classmethod
    def ok(cls, **kwargs) -> "DBResult":
        return cls(success=True, data=kwargs)

    @classmethod
    def fail(cls, error: str, code: str = "") -> "DBResult":
        return cls(success=False, error=error, code=code)


# ---------------------------------------------------------------------------
# Generic utilities
# ---------------------------------------------------------------------------

def safe_get(model, **kwargs) -> DBResult:
    """
    Fetch a single model instance without raising exceptions.

    Returns DBResult with ``data['instance']`` set on success,
    or a failure with code ``"not_found"`` / ``"multiple_objects"``.

    Example::

        result = safe_get(Member, rfid_card_number='0012345678', is_active=True)
        if result.success:
            member = result.data['instance']
    """
    try:
        instance = model.objects.get(**kwargs)
        return DBResult.ok(instance=instance)
    except model.DoesNotExist:
        return DBResult.fail(
            f"{model.__name__} not found with {kwargs}",
            code="not_found",
        )
    except model.MultipleObjectsReturned:
        return DBResult.fail(
            f"Multiple {model.__name__} objects returned for {kwargs}",
            code="multiple_objects",
        )
    except DatabaseError as exc:
        logger.exception("safe_get failed for %s %s", model.__name__, kwargs)
        return DBResult.fail(str(exc), code="db_error")


def safe_get_or_create(model, defaults: Optional[dict] = None, **kwargs) -> DBResult:
    """
    Wraps ``Model.objects.get_or_create`` with error handling.

    Returns DBResult with ``data['instance']`` and ``data['created']``.
    """
    try:
        instance, created = model.objects.get_or_create(defaults=defaults or {}, **kwargs)
        return DBResult.ok(instance=instance, created=created)
    except IntegrityError as exc:
        logger.warning("safe_get_or_create IntegrityError for %s: %s", model.__name__, exc)
        return DBResult.fail(str(exc), code="integrity_error")
    except DatabaseError as exc:
        logger.exception("safe_get_or_create DB error for %s", model.__name__)
        return DBResult.fail(str(exc), code="db_error")


def bulk_save(instances: List[Any], update_fields: Optional[List[str]] = None) -> DBResult:
    """
    Save a list of model instances inside a single atomic block.

    If ``update_fields`` is provided every instance is saved with those
    fields only (faster for partial updates). Otherwise a full ``save()``
    is called on each.

    Returns DBResult with ``data['saved_count']``.

    Example::

        result = bulk_save([item1, item2, item3])
        if result.success:
            print(result.data['saved_count'])  # 3
    """
    if not instances:
        return DBResult.ok(saved_count=0)

    try:
        with transaction.atomic():
            for obj in instances:
                if update_fields:
                    obj.save(update_fields=update_fields)
                else:
                    obj.save()
        return DBResult.ok(saved_count=len(instances))
    except IntegrityError as exc:
        logger.warning("bulk_save IntegrityError: %s", exc)
        return DBResult.fail(str(exc), code="integrity_error")
    except DatabaseError as exc:
        logger.exception("bulk_save DB error")
        return DBResult.fail(str(exc), code="db_error")


def atomic_operation(fn: Callable, *args, **kwargs) -> DBResult:
    """
    Run any callable inside an atomic block and wrap the outcome in DBResult.

    The callable must return a DBResult (or raise on failure).

    Example::

        result = atomic_operation(my_complex_function, arg1, kwarg=val)
    """
    try:
        with transaction.atomic():
            return fn(*args, **kwargs)
    except Exception as exc:
        logger.exception("atomic_operation failed: %s", exc)
        return DBResult.fail(str(exc), code="db_error")


# ---------------------------------------------------------------------------
# Member balance helpers
# ---------------------------------------------------------------------------

def deduct_member_balance(member_id: int, amount: Decimal) -> DBResult:
    """
    Atomically deduct ``amount`` from a Member's balance.

    Uses ``select_for_update()`` to prevent concurrent overdrafts.

    Returns DBResult with ``data['balance_before']`` and ``data['balance_after']``.
    """
    from members.models import Member  # local import avoids circular deps

    amount = Decimal(str(amount))
    if amount <= 0:
        return DBResult.fail("Deduction amount must be positive.", code="invalid_amount")

    try:
        with transaction.atomic():
            member = Member.objects.select_for_update().get(pk=member_id, is_active=True)
            balance_before = member.balance
            if member.balance < amount:
                return DBResult.fail(
                    f"Insufficient balance. Has ₱{member.balance}, needs ₱{amount}.",
                    code="insufficient_balance",
                )
            member.balance -= amount
            member.last_transaction = timezone.now()
            member.save(update_fields=["balance", "last_transaction", "updated_at"])
            logger.info(
                "Deducted ₱%s from Member #%d. Balance: ₱%s → ₱%s",
                amount, member_id, balance_before, member.balance,
            )
            return DBResult.ok(
                member=member,
                balance_before=balance_before,
                balance_after=member.balance,
            )
    except Member.DoesNotExist:
        return DBResult.fail(f"Active member #{member_id} not found.", code="not_found")
    except DatabaseError as exc:
        logger.exception("deduct_member_balance DB error for member #%d", member_id)
        return DBResult.fail(str(exc), code="db_error")


def credit_member_balance(member_id: int, amount: Decimal, update_last_transaction: bool = False) -> DBResult:
    """
    Atomically add ``amount`` to a Member's balance.

    Returns DBResult with ``data['balance_before']`` and ``data['balance_after']``.
    """
    from members.models import Member

    amount = Decimal(str(amount))
    if amount <= 0:
        return DBResult.fail("Credit amount must be positive.", code="invalid_amount")

    try:
        with transaction.atomic():
            member = Member.objects.select_for_update().get(pk=member_id, is_active=True)
            balance_before = member.balance
            member.balance += amount
            save_fields = ["balance", "updated_at"]
            if update_last_transaction:
                member.last_transaction = timezone.now()
                save_fields.append("last_transaction")
            member.save(update_fields=save_fields)
            logger.info(
                "Credited ₱%s to Member #%d. Balance: ₱%s → ₱%s",
                amount, member_id, balance_before, member.balance,
            )
            return DBResult.ok(
                member=member,
                balance_before=balance_before,
                balance_after=member.balance,
            )
    except Member.DoesNotExist:
        return DBResult.fail(f"Active member #{member_id} not found.", code="not_found")
    except DatabaseError as exc:
        logger.exception("credit_member_balance DB error for member #%d", member_id)
        return DBResult.fail(str(exc), code="db_error")


# ---------------------------------------------------------------------------
# Product stock helpers
# ---------------------------------------------------------------------------

def deduct_product_stock(product_id: int, quantity: int) -> DBResult:
    """
    Atomically deduct ``quantity`` units from a Product's ``stock_quantity``.

    Uses ``select_for_update()`` to prevent overselling.

    Returns DBResult with ``data['stock_before']`` and ``data['stock_after']``.
    """
    from inventory.models import Product

    if quantity <= 0:
        return DBResult.fail("Quantity must be positive.", code="invalid_quantity")

    try:
        with transaction.atomic():
            product = Product.objects.select_for_update().get(pk=product_id, is_active=True)
            stock_before = product.stock_quantity
            if product.stock_quantity < quantity:
                return DBResult.fail(
                    f"Not enough stock for '{product.name}'. "
                    f"Available: {product.stock_quantity}, requested: {quantity}.",
                    code="insufficient_stock",
                )
            product.stock_quantity -= quantity
            product.save(update_fields=["stock_quantity", "updated_at"])
            logger.info(
                "Deducted %d units from Product #%d (%s). Stock: %d → %d",
                quantity, product_id, product.name, stock_before, product.stock_quantity,
            )
            return DBResult.ok(
                product=product,
                stock_before=stock_before,
                stock_after=product.stock_quantity,
                is_low_stock=product.is_low_stock,
                is_out_of_stock=product.is_out_of_stock,
            )
    except Product.DoesNotExist:
        return DBResult.fail(f"Active product #{product_id} not found.", code="not_found")
    except DatabaseError as exc:
        logger.exception("deduct_product_stock DB error for product #%d", product_id)
        return DBResult.fail(str(exc), code="db_error")


def restock_product(product_id: int, quantity: int) -> DBResult:
    """
    Atomically add ``quantity`` units to a Product's ``stock_quantity``.

    Returns DBResult with ``data['stock_before']`` and ``data['stock_after']``.
    """
    from inventory.models import Product

    if quantity <= 0:
        return DBResult.fail("Quantity must be positive.", code="invalid_quantity")

    try:
        with transaction.atomic():
            product = Product.objects.select_for_update().get(pk=product_id)
            stock_before = product.stock_quantity
            product.stock_quantity += quantity
            product.save(update_fields=["stock_quantity", "updated_at"])
            logger.info(
                "Restocked Product #%d (%s) by %d. Stock: %d → %d",
                product_id, product.name, quantity, stock_before, product.stock_quantity,
            )
            return DBResult.ok(
                product=product,
                stock_before=stock_before,
                stock_after=product.stock_quantity,
            )
    except Product.DoesNotExist:
        return DBResult.fail(f"Product #{product_id} not found.", code="not_found")
    except DatabaseError as exc:
        logger.exception("restock_product DB error for product #%d", product_id)
        return DBResult.fail(str(exc), code="db_error")


# ---------------------------------------------------------------------------
# Transaction helpers
# ---------------------------------------------------------------------------

def save_transaction(
    payment_method: str,
    items: List[Dict],
    member_id: Optional[int] = None,
    amount_paid: Decimal = Decimal("0.00"),
    notes: str = "",
) -> DBResult:
    """
    Create a Transaction and its TransactionItems atomically.

    ``items`` is a list of dicts::

        {
            "product_id": int,
            "product_name": str,
            "product_barcode": str,
            "unit_price": Decimal,
            "quantity": int,
            "total_price": Decimal,
            "vat_amount": Decimal,
            "vatable_sale": Decimal,
        }

    On success, calls ``transaction.calculate_totals()`` and returns
    ``data['transaction']``, ``data['items']``, and ``data['transaction_number']``.
    """
    from transactions.models import Transaction as Txn, TransactionItem
    from members.models import Member
    from helper.kiosk_helper import generate_transaction_number  # reuse existing helper

    if not items:
        return DBResult.fail("Cannot save a transaction with no items.", code="empty_cart")

    try:
        with transaction.atomic():
            member = None
            if member_id:
                try:
                    member = Member.objects.get(pk=member_id, is_active=True)
                except Member.DoesNotExist:
                    return DBResult.fail(f"Active member #{member_id} not found.", code="not_found")

            txn_number = generate_transaction_number()
            txn = Txn.objects.create(
                transaction_number=txn_number,
                member=member,
                payment_method=payment_method,
                amount_paid=Decimal(str(amount_paid)),
                status="pending",
                notes=notes,
            )

            saved_items = []
            for item_data in items:
                ti = TransactionItem.objects.create(
                    transaction=txn,
                    product_id=item_data.get("product_id"),
                    product_name=item_data["product_name"],
                    product_barcode=item_data["product_barcode"],
                    unit_price=Decimal(str(item_data["unit_price"])),
                    quantity=Decimal(str(item_data["quantity"])),
                    total_price=Decimal(str(item_data["total_price"])),
                    vat_amount=Decimal(str(item_data.get("vat_amount", "0.00"))),
                    vatable_sale=Decimal(str(item_data.get("vatable_sale", "0.00"))),
                )
                saved_items.append(ti)

            # Recalculate totals from saved items
            txn.calculate_totals()

            logger.info("Saved Transaction %s with %d items.", txn_number, len(saved_items))
            return DBResult.ok(
                transaction=txn,
                items=saved_items,
                transaction_number=txn_number,
            )
    except IntegrityError as exc:
        logger.warning("save_transaction IntegrityError: %s", exc)
        return DBResult.fail(str(exc), code="integrity_error")
    except DatabaseError as exc:
        logger.exception("save_transaction DB error")
        return DBResult.fail(str(exc), code="db_error")


def complete_transaction(transaction_id: int, status: str = "completed") -> DBResult:
    """
    Mark a Transaction as completed (or any valid status).

    Valid statuses: ``pending``, ``completed``, ``cancelled``,
    ``refund_requested``, ``refunded``.

    Returns DBResult with ``data['transaction']``.
    """
    from transactions.models import Transaction as Txn

    VALID_STATUSES = {"pending", "completed", "cancelled", "refund_requested", "refunded"}
    if status not in VALID_STATUSES:
        return DBResult.fail(f"Invalid status '{status}'.", code="invalid_status")

    try:
        with transaction.atomic():
            txn = Txn.objects.select_for_update().get(pk=transaction_id)
            txn.status = status
            txn.save(update_fields=["status", "updated_at"])
            logger.info("Transaction #%d status set to '%s'.", transaction_id, status)
            return DBResult.ok(transaction=txn)
    except Txn.DoesNotExist:
        return DBResult.fail(f"Transaction #{transaction_id} not found.", code="not_found")
    except DatabaseError as exc:
        logger.exception("complete_transaction DB error for txn #%d", transaction_id)
        return DBResult.fail(str(exc), code="db_error")


def process_debit_checkout(
    transaction_id: int,
    member_id: int,
    total_amount: Decimal,
) -> DBResult:
    """
    Complete a debit-payment checkout in one atomic step:

    1. Deduct member balance.
    2. Update ``amount_from_balance`` on the Transaction.
    3. Mark Transaction as ``completed``.

    Returns DBResult with ``data['transaction']``, ``data['balance_after']``.
    """
    from transactions.models import Transaction as Txn
    from members.models import Member

    total_amount = Decimal(str(total_amount))

    try:
        with transaction.atomic():
            # Lock both rows
            member = Member.objects.select_for_update().get(pk=member_id, is_active=True)
            txn = Txn.objects.select_for_update().get(pk=transaction_id)

            if member.balance < total_amount:
                return DBResult.fail(
                    f"Insufficient balance. Has ₱{member.balance}, needs ₱{total_amount}.",
                    code="insufficient_balance",
                )

            balance_before = member.balance
            member.balance -= total_amount
            member.last_transaction = timezone.now()
            member.save(update_fields=["balance", "last_transaction", "updated_at"])

            txn.amount_from_balance = total_amount
            txn.status = "completed"
            txn.save(update_fields=["amount_from_balance", "status", "updated_at"])

            logger.info(
                "Debit checkout: Txn #%d, Member #%d, ₱%s deducted. Balance: ₱%s → ₱%s",
                transaction_id, member_id, total_amount, balance_before, member.balance,
            )
            return DBResult.ok(
                transaction=txn,
                member=member,
                balance_before=balance_before,
                balance_after=member.balance,
            )
    except Member.DoesNotExist:
        return DBResult.fail(f"Active member #{member_id} not found.", code="not_found")
    except Txn.DoesNotExist:
        return DBResult.fail(f"Transaction #{transaction_id} not found.", code="not_found")
    except DatabaseError as exc:
        logger.exception("process_debit_checkout DB error")
        return DBResult.fail(str(exc), code="db_error")


# ---------------------------------------------------------------------------
# OTP helpers (mobile_api)
# ---------------------------------------------------------------------------

def create_fund_transfer_otp(member_id: int, recipient_rfid: str, amount: Decimal, notes: str = "") -> DBResult:
    """
    Create a FundTransferOTP for the given member, invalidating any
    existing unused OTPs first.

    Returns DBResult with ``data['otp']`` and ``data['otp_code']``.
    """
    from mobile_api.models import FundTransferOTP
    from members.models import Member

    try:
        with transaction.atomic():
            member = Member.objects.get(pk=member_id, is_active=True)
            otp = FundTransferOTP.create_otp(
                member=member,
                recipient_rfid=recipient_rfid.strip(),
                amount=Decimal(str(amount)),
                notes=notes,
            )
            logger.info("Created FundTransferOTP for Member #%d.", member_id)
            return DBResult.ok(otp=otp, otp_code=otp.otp_code)
    except Member.DoesNotExist:
        return DBResult.fail(f"Active member #{member_id} not found.", code="not_found")
    except DatabaseError as exc:
        logger.exception("create_fund_transfer_otp DB error")
        return DBResult.fail(str(exc), code="db_error")


def verify_and_consume_otp(otp_id: int, provided_code: str) -> DBResult:
    """
    Verify a FundTransferOTP and mark it as used atomically.

    Returns DBResult with ``data['otp']`` on success.
    Error codes: ``"not_found"``, ``"already_used"``, ``"expired"``, ``"invalid_code"``.
    """
    from mobile_api.models import FundTransferOTP

    try:
        with transaction.atomic():
            otp = FundTransferOTP.objects.select_for_update().get(pk=otp_id)
            if otp.is_used:
                return DBResult.fail("OTP has already been used.", code="already_used")
            if timezone.now() > otp.expires_at:
                return DBResult.fail("OTP has expired.", code="expired")
            if otp.otp_code != provided_code:
                return DBResult.fail("Invalid OTP code.", code="invalid_code")
            otp.mark_as_used()
            return DBResult.ok(otp=otp)
    except FundTransferOTP.DoesNotExist:
        return DBResult.fail(f"OTP #{otp_id} not found.", code="not_found")
    except DatabaseError as exc:
        logger.exception("verify_and_consume_otp DB error")
        return DBResult.fail(str(exc), code="db_error")


# ---------------------------------------------------------------------------
# Member save helpers
# ---------------------------------------------------------------------------

def save_member(member_data: Dict, member_id: Optional[int] = None) -> DBResult:
    """
    Create or update a Member record safely.

    Pass ``member_id`` to update an existing record. Omit to create a new one.

    ``member_data`` keys correspond to Member model fields, e.g.::

        {
            "first_name": "Juan",
            "last_name": "dela Cruz",
            "email": "juan@example.com",
            "rfid_card_number": "0012345678",
            "member_type_id": 1,
            "role": "member",
        }

    Returns DBResult with ``data['member']`` and ``data['created']``.
    """
    from members.models import Member

    # Strip unknown fields to prevent unexpected kwargs
    ALLOWED_FIELDS = {
        "first_name", "last_name", "email", "phone",
        "rfid_card_number", "member_type_id", "role",
        "is_active", "inactive_remark", "balance", "username",
    }
    clean_data = {k: v for k, v in member_data.items() if k in ALLOWED_FIELDS}

    role_slug = clean_data.pop("role", None)
    if role_slug is not None:
        from members.models import Role

        clean_data["member_role_id"] = Role.resolve_slug(role_slug).pk

    try:
        with transaction.atomic():
            if member_id:
                updated = Member.objects.filter(pk=member_id).update(**clean_data)
                if not updated:
                    return DBResult.fail(f"Member #{member_id} not found.", code="not_found")
                member = Member.objects.get(pk=member_id)
                created = False
            else:
                member = Member.objects.create(**clean_data)
                created = True

            logger.info(
                "%s Member #%d (%s).",
                "Created" if created else "Updated",
                member.pk,
                member.full_name,
            )
            return DBResult.ok(member=member, created=created)
    except IntegrityError as exc:
        logger.warning("save_member IntegrityError: %s", exc)
        return DBResult.fail(str(exc), code="integrity_error")
    except DatabaseError as exc:
        logger.exception("save_member DB error")
        return DBResult.fail(str(exc), code="db_error")


# ---------------------------------------------------------------------------
# Balance transaction helpers
# ---------------------------------------------------------------------------

def save_balance_transaction(
    member_id: int,
    transaction_type: str,
    amount: Decimal,
    balance_before: Decimal,
    balance_after: Decimal,
    notes: str = "",
) -> DBResult:
    """
    Persist a BalanceTransaction record for a member's balance change.

    ``transaction_type`` must be ``"deposit"`` or ``"deduction"``.

    Returns DBResult with ``data['balance_transaction']``.
    """
    from members.models import BalanceTransaction, Member

    VALID_TYPES = {"deposit", "deduction"}
    if transaction_type not in VALID_TYPES:
        return DBResult.fail(
            f"Invalid transaction_type '{transaction_type}'. Must be one of {VALID_TYPES}.",
            code="invalid_type",
        )

    try:
        member = Member.objects.get(pk=member_id)
        bt = BalanceTransaction.objects.create(
            member=member,
            transaction_type=transaction_type,
            amount=Decimal(str(amount)).quantize(Decimal("0.01")),
            balance_before=Decimal(str(balance_before)).quantize(Decimal("0.01")),
            balance_after=Decimal(str(balance_after)).quantize(Decimal("0.01")),
            notes=notes,
        )
        return DBResult.ok(balance_transaction=bt)
    except Member.DoesNotExist:
        return DBResult.fail(f"Member #{member_id} not found.", code="not_found")
    except DatabaseError as exc:
        logger.exception("save_balance_transaction DB error for member #%d", member_id)
        return DBResult.fail(str(exc), code="db_error")


def process_fund_transfer(
    sender_id: int,
    recipient_rfid: str,
    amount: Decimal,
    notes: str = "",
) -> DBResult:
    """
    Atomically transfer ``amount`` from one member to another.

    Steps performed inside a single ``atomic()`` block:
    1. Lock sender & recipient rows with ``select_for_update()``.
    2. Validate sender balance.
    3. Deduct from sender, credit recipient.
    4. Create BalanceTransaction records for both.
    5. Update ``last_transaction`` on both members.

    Returns DBResult with:
        ``sender``                – refreshed Member instance
        ``recipient``             – refreshed Member instance
        ``sender_transaction``    – BalanceTransaction (deduction)
        ``recipient_transaction`` – BalanceTransaction (deposit)
        ``sender_balance_before``, ``sender_balance_after``
        ``recipient_balance_before``, ``recipient_balance_after``
    """
    from members.models import Member, BalanceTransaction

    amount = Decimal(str(amount)).quantize(Decimal("0.01"))
    if amount <= 0:
        return DBResult.fail("Transfer amount must be positive.", code="invalid_amount")

    recipient_rfid = (recipient_rfid or "").strip()
    if not recipient_rfid:
        return DBResult.fail("Recipient RFID is required.", code="missing_rfid")

    try:
        with transaction.atomic():
            # Lock sender
            try:
                sender = Member.objects.select_for_update().get(pk=sender_id, is_active=True)
            except Member.DoesNotExist:
                return DBResult.fail(f"Sender member #{sender_id} not found.", code="not_found")

            # Lock recipient
            try:
                recipient = Member.objects.select_for_update().get(
                    rfid_card_number=recipient_rfid, is_active=True
                )
            except Member.DoesNotExist:
                return DBResult.fail("Recipient member not found.", code="not_found")

            if sender.pk == recipient.pk:
                return DBResult.fail("Cannot transfer funds to yourself.", code="self_transfer")

            sender_balance_before = Decimal(str(sender.balance)).quantize(Decimal("0.01"))
            if sender_balance_before < amount:
                return DBResult.fail(
                    f"Insufficient balance. Has ₱{sender_balance_before}, needs ₱{amount}.",
                    code="insufficient_balance",
                )

            # Deduct from sender
            sender_balance_after = (sender_balance_before - amount).quantize(Decimal("0.01"))
            sender.balance = sender_balance_after
            sender.last_transaction = timezone.now()
            sender.save(update_fields=["balance", "last_transaction", "updated_at"])

            # Create sender BalanceTransaction
            sender_txn = BalanceTransaction.objects.create(
                member=sender,
                transaction_type="deduction",
                amount=amount,
                balance_before=sender_balance_before,
                balance_after=sender_balance_after,
                notes=(
                    f"Fund transfer to {recipient.full_name} ({recipient.rfid_card_number})"
                    + (f" - {notes}" if notes else "")
                ),
            )

            # Credit recipient
            recipient_balance_before = Decimal(str(recipient.balance)).quantize(Decimal("0.01"))
            recipient_balance_after = (recipient_balance_before + amount).quantize(Decimal("0.01"))
            recipient.balance = recipient_balance_after
            recipient.last_transaction = timezone.now()
            recipient.save(update_fields=["balance", "last_transaction", "updated_at"])

            # Create recipient BalanceTransaction
            recipient_txn = BalanceTransaction.objects.create(
                member=recipient,
                transaction_type="deposit",
                amount=amount,
                balance_before=recipient_balance_before,
                balance_after=recipient_balance_after,
                notes=(
                    f"Fund transfer from {sender.full_name} ({sender.rfid_card_number})"
                    + (f" - {notes}" if notes else "")
                ),
            )

            logger.info(
                "Fund transfer: ₱%s from Member #%d → Member #%d.",
                amount, sender_id, recipient.pk,
            )
            return DBResult.ok(
                sender=sender,
                recipient=recipient,
                sender_transaction=sender_txn,
                recipient_transaction=recipient_txn,
                sender_balance_before=sender_balance_before,
                sender_balance_after=sender_balance_after,
                recipient_balance_before=recipient_balance_before,
                recipient_balance_after=recipient_balance_after,
                notes=notes,
            )
    except DatabaseError as exc:
        logger.exception("process_fund_transfer DB error (sender #%d → rfid %s)", sender_id, recipient_rfid)
        return DBResult.fail(str(exc), code="db_error")


# ---------------------------------------------------------------------------
# Product save helpers
# ---------------------------------------------------------------------------

def save_product(product_data: Dict, product_id: Optional[int] = None) -> DBResult:
    """
    Create or update a Product record safely.

    Pass ``product_id`` to update an existing record. Omit to create a new one.

    Returns DBResult with ``data['product']`` and ``data['created']``.
    """
    from inventory.models import Product

    ALLOWED_FIELDS = {
        "name", "description", "barcode", "category_id",
        "price", "cost", "stock_quantity", "low_stock_threshold",
        "is_active",
    }
    clean_data = {k: v for k, v in product_data.items() if k in ALLOWED_FIELDS}

    try:
        with transaction.atomic():
            if product_id:
                updated = Product.objects.filter(pk=product_id).update(**clean_data)
                if not updated:
                    return DBResult.fail(f"Product #{product_id} not found.", code="not_found")
                product = Product.objects.get(pk=product_id)
                created = False
            else:
                product = Product(**clean_data)
                product.save()  # triggers barcode image generation
                created = True

            logger.info(
                "%s Product #%d (%s).",
                "Created" if created else "Updated",
                product.pk,
                product.name,
            )
            return DBResult.ok(product=product, created=created)
    except IntegrityError as exc:
        logger.warning("save_product IntegrityError: %s", exc)
        return DBResult.fail(str(exc), code="integrity_error")
    except DatabaseError as exc:
        logger.exception("save_product DB error")
        return DBResult.fail(str(exc), code="db_error")
