"""Palay trade products (features) and buy/sell tickets.

The coop trades only two products: **Rice Palay** (unmilled) and **Bigas**
(milled rice). ``PalayTradeProduct`` holds buy/sell rates and stock; staff post
``PalayTrade`` tickets against one of those products.
"""

import secrets
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

# Fixed catalog — new trades only use these two products.
DEFAULT_PRODUCTS = (
    {
        "code": "rice-palay",
        "name": "Rice Palay",
        "aliases": ("rice-palay", "palay", "rice", "normal-rice", "rice palay"),
        "description": "Unmilled rice (palay) bought from farmers or sold from stock.",
    },
    {
        "code": "bigas",
        "name": "Bigas",
        "aliases": ("bigas", "milled-rice", "milled rice"),
        "description": "Milled rice (bigas) for buy and sell tickets.",
    },
)
DEFAULT_PRODUCT_CODES = frozenset(item["code"] for item in DEFAULT_PRODUCTS)


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


class PalayVariety(BaseModel):
    """Reusable rice variety / hybrid names staff can pick when defining products."""

    name = models.CharField(
        max_length=100,
        unique=True,
        help_text="Rice variety or hybrid name (e.g. IR64, RC222).",
    )
    description = models.CharField(max_length=200, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Palay variety"
        verbose_name_plural = "Palay varieties"

    def __str__(self):
        return self.name

    @classmethod
    def get_or_create_by_name(cls, name):
        cleaned = (name or "").strip()
        if not cleaned:
            return None
        variety = cls.objects.filter(name__iexact=cleaned).first()
        if variety:
            if not variety.is_active:
                variety.is_active = True
                variety.save(update_fields=["is_active", "updated_at"])
            return variety
        return cls.objects.create(name=cleaned)


class PalayTradeProduct(BaseModel):
    """Rice Palay or Bigas trading rules (rates, stock, quantity limits)."""

    class Grade(models.TextChoices):
        FANCY = "fancy", "Fancy"
        PREMIUM = "premium", "Premium"
        GRADE_1 = "grade_1", "Grade 1"
        GRADE_2 = "grade_2", "Grade 2"
        GRADE_3 = "grade_3", "Grade 3"
        BROKEN = "broken", "Broken / reject"
        OTHER = "other", "Other"

    class Season(models.TextChoices):
        ANY = "any", "Any season"
        WET = "wet", "Wet season"
        DRY = "dry", "Dry season"

    name = models.CharField(
        max_length=150,
        help_text="Display name — use Rice Palay or Bigas.",
    )
    code = models.SlugField(
        max_length=40,
        unique=True,
        help_text="Short unique code: rice-palay or bigas.",
    )
    variety = models.ForeignKey(
        PalayVariety,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="products",
        help_text="Rice variety or hybrid. Use Add another variety if it is not in the list yet.",
    )
    grade = models.CharField(
        max_length=16,
        choices=Grade.choices,
        default=Grade.GRADE_1,
    )
    season = models.CharField(
        max_length=8,
        choices=Season.choices,
        default=Season.ANY,
    )
    description = models.TextField(blank=True)
    buy_price_per_kg = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Default price the coop pays per kilogram when buying.",
    )
    sell_price_per_kg = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Default price per kilogram when selling from stock.",
    )
    stock_kg = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Current rice stock in kilograms. Buys add stock; sells reduce stock.",
    )
    low_stock_kg = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Warn when stock falls to this level or below. 0 = no low-stock warning.",
    )
    min_quantity_kg = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Minimum kilograms per trade. 0 = no minimum.",
    )
    max_quantity_kg = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Maximum kilograms per trade. 0 = no maximum.",
    )
    members_only = models.BooleanField(
        default=False,
        help_text="If checked, only cooperative members can trade under this product.",
    )
    credit_enabled = models.BooleanField(
        default=False,
        help_text=(
            "Allow members to post this product on palay credit when palay credit "
            "is enabled in settings."
        ),
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Palay trade product"
        verbose_name_plural = "Palay trade products"

    def __str__(self):
        return self.name

    @property
    def is_low_stock(self):
        if not self.low_stock_kg:
            return False
        return self.stock_kg <= self.low_stock_kg

    def clean(self):
        super().clean()
        errors = {}
        for field in (
            "buy_price_per_kg",
            "sell_price_per_kg",
            "stock_kg",
            "low_stock_kg",
            "min_quantity_kg",
            "max_quantity_kg",
        ):
            value = getattr(self, field)
            if value is not None and value < 0:
                errors[field] = "Cannot be negative."
        if (
            self.max_quantity_kg
            and self.min_quantity_kg
            and self.max_quantity_kg < self.min_quantity_kg
        ):
            errors["max_quantity_kg"] = "Must be greater than or equal to the minimum."
        if errors:
            raise ValidationError(errors)

    @classmethod
    def active_trade_products(cls):
        """Rice Palay and Bigas only (ensures they exist). Rice Palay first."""
        from django.db.models import Case, IntegerField, Value, When

        cls.ensure_default_products()
        return cls.objects.filter(
            is_active=True,
            code__in=DEFAULT_PRODUCT_CODES,
        ).order_by(
            Case(
                When(code="rice-palay", then=Value(0)),
                When(code="bigas", then=Value(1)),
                default=Value(99),
                output_field=IntegerField(),
            ),
            "name",
        )

    @classmethod
    def ensure_default_products(cls):
        """Create/rename so only Rice Palay and Bigas are active for trading."""
        kept_ids = []
        for spec in DEFAULT_PRODUCTS:
            product = cls._resolve_default_product(spec)
            kept_ids.append(product.pk)
        cls.objects.exclude(pk__in=kept_ids).filter(is_active=True).update(is_active=False)
        return list(cls.objects.filter(pk__in=kept_ids).order_by("name"))

    @classmethod
    def _resolve_default_product(cls, spec):
        product = cls.objects.filter(code=spec["code"]).first()
        if product is None:
            for alias in spec["aliases"]:
                product = (
                    cls.objects.filter(code__iexact=alias).first()
                    or cls.objects.filter(name__iexact=alias).first()
                )
                if product:
                    break
        if product is None:
            return cls.objects.create(
                name=spec["name"],
                code=spec["code"],
                grade=cls.Grade.OTHER,
                season=cls.Season.ANY,
                description=spec["description"],
                is_active=True,
            )

        updates = []
        if product.name != spec["name"]:
            product.name = spec["name"]
            updates.append("name")
        if product.code != spec["code"]:
            # Avoid unique collisions when renaming another row onto the canonical code.
            clash = cls.objects.filter(code=spec["code"]).exclude(pk=product.pk).first()
            if clash is None:
                product.code = spec["code"]
                updates.append("code")
        if not product.is_active:
            product.is_active = True
            updates.append("is_active")
        if not (product.description or "").strip():
            product.description = spec["description"]
            updates.append("description")
        if updates:
            updates.append("updated_at")
            product.save(update_fields=updates)
        return product


class PalayCreditSettings(models.Model):
    """Singleton rules for member palay credit (utang on palay desk trades)."""

    is_enabled = models.BooleanField(
        default=False,
        help_text="When enabled, staff can post eligible trades on palay credit for members.",
    )
    member_max_outstanding = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=(
            "Maximum total unsettled palay credit per member. "
            "Set to 0 for no limit."
        ),
    )
    grace_period_days = models.PositiveIntegerField(
        default=7,
        help_text=(
            "Days after a credit trade before interest may apply. "
            "Members can pay within this period with no interest."
        ),
    )
    interest_rate = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=Decimal("0.000"),
        help_text=(
            "Monthly interest on unpaid palay credit after grace. "
            "Use 0.015 for 1.5% per month. Set to 0 to disable interest."
        ),
    )
    interest_enabled = models.BooleanField(
        default=False,
        help_text="Apply monthly interest to overdue palay credit balances.",
    )
    allow_credit_on_sell = models.BooleanField(
        default=True,
        help_text="Member may buy Rice Palay or Bigas on credit (member owes the coop).",
    )
    allow_credit_on_buy = models.BooleanField(
        default=False,
        help_text=(
            "Member may sell palay on credit (coop pays later). "
            "Usually disabled; enable only if your coop records farmer advances this way."
        ),
    )
    min_membership_months = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Minimum months registered before a member may use palay credit. "
            "0 = no waiting period."
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Palay credit settings"
        verbose_name_plural = "Palay credit settings"

    def __str__(self):
        if not self.is_enabled:
            return "Palay credit — disabled"
        cap = self.member_max_outstanding or Decimal("0.00")
        cap_label = f"₱{cap:,.2f} cap" if cap > 0 else "no cap"
        return f"Palay credit — enabled ({cap_label})"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "is_enabled": False,
                "member_max_outstanding": Decimal("0.00"),
                "grace_period_days": 7,
                "interest_rate": Decimal("0.000"),
                "interest_enabled": False,
                "allow_credit_on_sell": True,
                "allow_credit_on_buy": False,
                "min_membership_months": 0,
            },
        )
        return obj


class PalayTrade(BaseModel):
    """A single palay buy or sell ticket."""

    class TradeType(models.TextChoices):
        BUY = "buy", "Buy from farmer"
        SELL = "sell", "Sell from stock"

    class Status(models.TextChoices):
        POSTED = "posted", "Posted"
        VOID = "void", "Void"

    class PaymentMethod(models.TextChoices):
        CASH = "cash", "Cash"
        CREDIT = "credit", "Palay credit"

    product = models.ForeignKey(
        PalayTradeProduct,
        on_delete=models.PROTECT,
        related_name="trades",
    )
    trade_type = models.CharField(max_length=8, choices=TradeType.choices)
    member = models.ForeignKey(
        "members.Member",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="palay_trades",
        help_text="Linked member when the farmer/buyer is a cooperative member.",
    )
    party_name = models.CharField(
        max_length=200,
        help_text="Farmer or buyer name (filled from member when linked).",
    )
    reference = models.CharField(max_length=32, unique=True, editable=False)
    traded_at = models.DateTimeField(default=timezone.now)
    gross_kg = models.DecimalField(max_digits=12, decimal_places=2)
    net_kg = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    unit_price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Price per kilogram applied on this ticket.",
    )
    gross_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    net_amount = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal("0.00"))
    payment_method = models.CharField(
        max_length=8,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
        db_index=True,
    )
    credit_amount_paid = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Amount already paid against this palay credit ticket.",
    )
    credit_settled_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="When the palay credit balance for this ticket was fully paid.",
    )
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.POSTED,
        db_index=True,
    )
    notes = models.TextField(blank=True)
    performed_by = models.ForeignKey(
        "auth.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="palay_trades",
    )

    class Meta:
        ordering = ["-traded_at"]
        verbose_name = "Palay trade"
        verbose_name_plural = "Palay trades"

    def __str__(self):
        return f"{self.reference} — {self.get_trade_type_display()} {self.net_kg} kg"

    @property
    def credit_outstanding(self):
        if self.payment_method != self.PaymentMethod.CREDIT or self.credit_settled_at:
            return Decimal("0.00")
        paid = self.credit_amount_paid or Decimal("0.00")
        remaining = (self.net_amount or Decimal("0.00")) - paid
        return max(remaining, Decimal("0.00")).quantize(Decimal("0.01"))

    @property
    def is_credit_open(self):
        return (
            self.payment_method == self.PaymentMethod.CREDIT
            and self.status == self.Status.POSTED
            and self.credit_settled_at is None
            and self.credit_outstanding > Decimal("0.00")
        )

    def save(self, *args, **kwargs):
        if not self.reference:
            for _ in range(8):
                candidate = f"PY{secrets.token_hex(8).upper()}"
                if not PalayTrade.objects.filter(reference=candidate).exclude(pk=self.pk).exists():
                    self.reference = candidate
                    break
            else:
                raise RuntimeError("Could not allocate a unique palay trade reference")
        super().save(*args, **kwargs)
