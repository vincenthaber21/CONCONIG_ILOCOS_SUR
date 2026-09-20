"""Share capital product template (rules) for member paid-up capital.

Member balances live on ``members.Member.share_capital``; ledger rows are
``members.ShareCapitalTransaction``. This model is the cooperative's share
capital *template* — par value, minimums, dividend rate, and withdrawal rules.
"""

import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


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


class ShareCapitalProduct(BaseModel):
    """Catalog of share-capital offerings and their rules."""

    name = models.CharField(max_length=150)
    code = models.SlugField(
        max_length=40,
        unique=True,
        help_text="Short unique code, e.g. common-share, preferred.",
    )
    description = models.TextField(blank=True)
    par_value = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("100.00"),
        help_text="Value of one share in pesos.",
    )
    min_shares = models.PositiveIntegerField(
        default=1,
        help_text="Minimum number of shares a member must hold.",
    )
    max_shares = models.PositiveIntegerField(
        default=0,
        help_text="Maximum shares a member may hold. 0 = no limit.",
    )
    min_contribution = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Minimum paid-up amount to start (opening contribution). 0 = any amount.",
    )
    dividend_rate = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=Decimal("0.000"),
        help_text="Annual dividend rate in percent (e.g. 5.000 = 5%).",
    )
    allows_withdrawal = models.BooleanField(
        default=False,
        help_text="Share capital is usually locked. Check only if withdrawals are allowed.",
    )
    required_for_membership = models.BooleanField(
        default=True,
        help_text="Members are expected to hold this product.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Share capital product"
        verbose_name_plural = "Share capital products"

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        errors = {}
        if self.par_value is not None and self.par_value <= 0:
            errors["par_value"] = "Par value must be greater than zero."
        if self.dividend_rate is not None and self.dividend_rate < 0:
            errors["dividend_rate"] = "Dividend rate cannot be negative."
        if self.min_contribution is not None and self.min_contribution < 0:
            errors["min_contribution"] = "Minimum contribution cannot be negative."
        if (
            self.max_shares
            and self.min_shares
            and self.max_shares < self.min_shares
        ):
            errors["max_shares"] = "Maximum shares must be at least the minimum shares."
        min_from_shares = self.min_paid_up
        if (
            self.min_contribution is not None
            and min_from_shares is not None
            and self.min_contribution
            and self.min_contribution < min_from_shares
        ):
            errors["min_contribution"] = (
                f"Minimum contribution must be at least "
                f"₱{min_from_shares:,.2f} ({self.min_shares} × par value)."
            )
        if errors:
            raise ValidationError(errors)

    @property
    def min_paid_up(self):
        if not self.par_value or not self.min_shares:
            return None
        return (self.par_value * self.min_shares).quantize(Decimal("0.01"))

    @property
    def max_paid_up(self):
        if not self.par_value or not self.max_shares:
            return None
        return (self.par_value * self.max_shares).quantize(Decimal("0.01"))

    def shares_for(self, amount):
        amount = Decimal(amount or 0)
        if not self.par_value or self.par_value <= 0:
            return None
        return (amount / self.par_value).quantize(Decimal("0.01"))

    @property
    def dividend_rate_display(self):
        rate = self.dividend_rate or Decimal("0")
        return f"{rate.normalize()}%" if rate else "None"


def active_share_capital_product():
    """First active product, used as the desk default template."""
    return ShareCapitalProduct.objects.filter(is_active=True).order_by("name").first()
