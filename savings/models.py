"""Member savings products, accounts, and ledger.

``SavingsProduct`` holds the cooperative's savings *features* (rate, minimums,
term, withdrawal rules). Members open ``MemberSavingsAccount`` rows against a
product; deposits and withdrawals are posted as ``SavingsTransaction`` rows.
"""

import secrets
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class BaseModel(UUIDModel, TimeStampedModel):
    class Meta:
        abstract = True


class SavingsProduct(BaseModel):
    """Catalog of savings offerings and their rules."""

    class ProductType(models.TextChoices):
        SHARE_CAPITAL = "share_capital", "Share capital"
        REGULAR = "regular", "Regular savings"
        TIME_DEPOSIT = "time_deposit", "Time deposit"
        SPECIAL = "special", "Special savings"
        CAPITAL_BUILD_UP = "capital_build_up", "Capital build-up (CBU)"

    class Compounding(models.TextChoices):
        NONE = "none", "No compounding (simple)"
        MONTHLY = "monthly", "Monthly"
        QUARTERLY = "quarterly", "Quarterly"
        ANNUALLY = "annually", "Annually"

    name = models.CharField(max_length=150)
    code = models.SlugField(
        max_length=40,
        unique=True,
        help_text="Short unique code, e.g. regular, td-12, share.",
    )
    product_type = models.CharField(
        max_length=32,
        choices=ProductType.choices,
        default=ProductType.REGULAR,
    )
    description = models.TextField(blank=True)
    interest_rate = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=Decimal("0.000"),
        help_text="Annual interest rate in percent (e.g. 3.500 = 3.5%).",
    )
    compounding = models.CharField(
        max_length=16,
        choices=Compounding.choices,
        default=Compounding.ANNUALLY,
    )
    min_opening_deposit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Minimum amount required to open an account.",
    )
    min_maintaining_balance = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Balance that must remain after a withdrawal.",
    )
    min_additional_deposit = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Minimum amount for later deposits. 0 means any amount is allowed.",
    )
    max_balance = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("1000000.00"),
        help_text="Maximum account balance. 0 = no limit.",
    )
    term_months = models.PositiveIntegerField(
        default=0,
        help_text="Fixed term in months for time deposits. 0 = open-ended (no maturity).",
    )
    allows_withdrawal = models.BooleanField(
        default=True,
        help_text="Uncheck for products that cannot be withdrawn (e.g. share capital).",
    )
    withdrawal_notice_days = models.PositiveIntegerField(
        default=0,
        help_text="Days of notice required before a withdrawal. 0 = same day.",
    )
    max_free_withdrawals_per_month = models.PositiveIntegerField(
        default=0,
        help_text="Free withdrawals allowed per calendar month. 0 = unlimited.",
    )
    early_withdrawal_penalty_percent = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=Decimal("0.000"),
        help_text="Penalty % of withdrawn amount if taken before maturity.",
    )
    dividend_eligible = models.BooleanField(
        default=False,
        help_text="Counts toward patronage / dividend computation (typical for share capital).",
    )
    required_for_membership = models.BooleanField(
        default=False,
        help_text="Members are expected to hold this product (e.g. share capital).",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Savings product"
        verbose_name_plural = "Savings products"

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        errors = {}
        if self.interest_rate is not None and self.interest_rate < 0:
            errors["interest_rate"] = "Interest rate cannot be negative."
        if (
            self.early_withdrawal_penalty_percent is not None
            and self.early_withdrawal_penalty_percent < 0
        ):
            errors["early_withdrawal_penalty_percent"] = "Penalty cannot be negative."
        if self.product_type == self.ProductType.TIME_DEPOSIT and not self.term_months:
            errors["term_months"] = "Time deposits need a term of at least 1 month."
        if self.max_balance is not None and self.max_balance < 0:
            errors["max_balance"] = "Maximum balance cannot be negative."
        if (
            self.max_balance
            and self.min_opening_deposit is not None
            and self.max_balance < self.min_opening_deposit
        ):
            errors["max_balance"] = "Maximum balance must be at least the minimum opening deposit."
        if errors:
            raise ValidationError(errors)


class MemberSavingsAccount(BaseModel):
    """A member's savings account for one product."""

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        DORMANT = "dormant", "Dormant"
        MATURED = "matured", "Matured"
        CLOSED = "closed", "Closed"

    member = models.ForeignKey(
        "members.Member",
        on_delete=models.CASCADE,
        related_name="savings_accounts",
    )
    product = models.ForeignKey(
        SavingsProduct,
        on_delete=models.CASCADE,
        related_name="accounts",
    )
    account_number = models.CharField(max_length=32, unique=True, editable=False)
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.ACTIVE,
        db_index=True,
    )
    opened_at = models.DateTimeField(
        default=timezone.now,
        help_text="Official date and time this member's savings account was opened.",
    )
    maturity_date = models.DateField(
        null=True,
        blank=True,
        help_text="Set automatically from the product term when the account is opened.",
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-opened_at"]
        indexes = [
            models.Index(fields=["status", "-opened_at"], name="savings_acct_status_opened"),
        ]
        verbose_name = "Member savings account"
        verbose_name_plural = "Member savings accounts"

    def __str__(self):
        return f"{self.account_number} — {self.member.full_name}"

    def save(self, *args, **kwargs):
        if not self.account_number:
            self.account_number = self._allocate_account_number()
        super().save(*args, **kwargs)

    @property
    def opening_date(self):
        if not self.opened_at:
            return None
        when = self.opened_at
        if timezone.is_aware(when):
            when = timezone.localtime(when)
        return when.date()

    def _allocate_account_number(self):
        stamp = self.opened_at or timezone.now()
        if timezone.is_aware(stamp):
            stamp = timezone.localtime(stamp)
        prefix = stamp.strftime("SAV-%Y%m%d")
        for _ in range(12):
            candidate = f"{prefix}-{secrets.randbelow(1_000_000):06d}"
            if not MemberSavingsAccount.objects.filter(account_number=candidate).exists():
                return candidate
        raise RuntimeError("Could not allocate a unique savings account number")

    @property
    def can_transact(self):
        return self.status == self.Status.ACTIVE


class SavingsTransaction(TimeStampedModel):
    """Ledger row for deposits, withdrawals, interest, and penalties."""

    class TxnType(models.TextChoices):
        OPENING = "opening", "Opening deposit"
        DEPOSIT = "deposit", "Deposit"
        WITHDRAWAL = "withdrawal", "Withdrawal"
        INTEREST = "interest", "Interest credit"
        PENALTY = "penalty", "Penalty"
        ADJUSTMENT = "adjustment", "Adjustment"

    account = models.ForeignKey(
        MemberSavingsAccount,
        on_delete=models.CASCADE,
        related_name="transactions",
    )
    transaction_type = models.CharField(max_length=16, choices=TxnType.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    balance_before = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    reference = models.CharField(max_length=32, unique=True, editable=False)
    notes = models.TextField(blank=True)
    performed_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="savings_transactions",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Savings transaction"
        verbose_name_plural = "Savings transactions"

    def __str__(self):
        return f"{self.reference} — {self.get_transaction_type_display()} ₱{self.amount}"

    @property
    def is_credit(self):
        return self.transaction_type not in (
            self.TxnType.WITHDRAWAL,
            self.TxnType.PENALTY,
        )

    @property
    def receipt_amount_label(self):
        if self.transaction_type == self.TxnType.WITHDRAWAL:
            return "Amount withdrawn"
        if self.transaction_type == self.TxnType.PENALTY:
            return "Penalty charged"
        if self.transaction_type == self.TxnType.INTEREST:
            return "Interest credited"
        if self.transaction_type == self.TxnType.OPENING:
            return "Opening deposit"
        if self.transaction_type == self.TxnType.ADJUSTMENT:
            return "Adjustment amount"
        return "Amount received"

    def save(self, *args, **kwargs):
        if not self.reference:
            for _ in range(8):
                candidate = f"SV{secrets.token_hex(8).upper()}"
                if not SavingsTransaction.objects.filter(reference=candidate).exclude(pk=self.pk).exists():
                    self.reference = candidate
                    break
            else:
                raise RuntimeError("Could not allocate a unique savings transaction reference")
        super().save(*args, **kwargs)
