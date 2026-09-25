import uuid
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.utils import timezone
from django.utils.text import slugify

from helper.money_forms import MoneyField, money_input
from members.models import Member

from . import models
from .policy import ANNUAL_INTEREST_RATE

# Natural / passbook regular savings — fixed coop defaults (not editable).
REGULAR_NATURAL_DEFAULTS = {
    key: value
    for key, value in models.SavingsProduct.regular_product_defaults().items()
    if key not in {"name", "description", "is_active", "interest_apply_months"}
}

# Fields staff set only when the time-deposit switch is on.
TIME_DEPOSIT_FIELDS = (
    "interest_rate",
    "min_opening_deposit",
    "max_balance",
    "allows_withdrawal",
    "rate_3_months",
    "rate_6_months",
    "rate_1_year",
)

# Applied once, when a time deposit is first created (not shown on the form).
TIME_DEPOSIT_CREATE_DEFAULTS = {
    "min_maintaining_balance": Decimal("0.00"),
    "min_additional_deposit": Decimal("0.00"),
    "withdrawal_notice_days": 0,
    "max_free_withdrawals_per_month": 0,
    "dividend_eligible": False,
    "required_for_membership": False,
}


class SavingsProductForm(forms.ModelForm):
    """Regular Savings product form, with an optional time-deposit feature set."""

    code = forms.CharField(
        max_length=40,
        required=False,
        help_text="Optional. Leave blank to generate from the name.",
    )
    is_time_deposit = forms.CharField(
        required=False,
        initial="0",
        label="Time deposit",
        widget=forms.HiddenInput(attrs={"id": "product-is-time-deposit"}),
    )
    min_opening_deposit = MoneyField(
        required=False,
        min_value=Decimal("0"),
        max_digits=12,
        decimal_places=2,
        label="Minimum opening deposit",
        widget=money_input(min="5000", placeholder="5,000.00"),
    )
    max_balance = MoneyField(
        required=False,
        min_value=Decimal("0"),
        max_digits=14,
        decimal_places=2,
        label="Maximum balance",
        help_text="0 = no limit.",
        widget=money_input(min="0", placeholder="0.00"),
    )

    class Meta:
        model = models.SavingsProduct
        fields = [
            "name",
            "code",
            "description",
            "interest_apply_months",
            "is_active",
            *TIME_DEPOSIT_FIELDS,
        ]
        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Optional note for staff (e.g. passbook savings for members).",
                }
            ),
            "name": forms.TextInput(attrs={"placeholder": "Regular Savings", "id": "id_name"}),
            "interest_apply_months": forms.NumberInput(
                attrs={"min": 1, "max": 120, "step": 1}
            ),
            "interest_rate": forms.NumberInput(
                attrs={"min": "0", "step": "0.001", "placeholder": "0.020"}
            ),
            "rate_3_months": forms.NumberInput(
                attrs={"min": "0", "step": "0.001", "placeholder": "0.010"}
            ),
            "rate_6_months": forms.NumberInput(
                attrs={"min": "0", "step": "0.001", "placeholder": "0.010"}
            ),
            "rate_1_year": forms.NumberInput(
                attrs={"min": "0", "step": "0.001", "placeholder": "0.030"}
            ),
            "allows_withdrawal": forms.CheckboxInput(),
        }
        labels = {
            "name": "Display name",
            "is_active": "Active (available when opening accounts)",
            "interest_apply_months": "Apply interest every (months)",
            "interest_rate": "Interest rate",
            "rate_3_months": "3 months interest",
            "rate_6_months": "6 months interest",
            "rate_1_year": "1 year interest",
            "allows_withdrawal": "Allow withdrawals before maturity",
        }
        help_texts = {
            "interest_rate": (
                "From ₱5,000 up to ₱100,000. Interest = time deposit × this rate. "
                "Example: ₱50,000 × 0.02 = ₱1,000.00."
            ),
            "rate_3_months": "savings × this rate × (3/12) when the member selects 3 months.",
            "rate_6_months": "savings × this rate × (6/12) when the member selects 6 months.",
            "rate_1_year": "savings × this rate when the member selects 1 year.",
            "allows_withdrawal": (
                "When off, this product cannot be withdrawn at the savings desk."
            ),
        }

    @staticmethod
    def _truthy_flag(raw):
        return str(raw or "").strip().lower() in {"1", "true", "on", "yes"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["description"].required = False
        self.fields["is_active"].required = False
        for name in TIME_DEPOSIT_FIELDS:
            self.fields[name].required = False
        self._original_product_type = None
        self._original_time_deposit_values = {}
        if self.instance.pk:
            self._original_product_type = self.instance.product_type
            for name in TIME_DEPOSIT_FIELDS:
                self._original_time_deposit_values[name] = getattr(self.instance, name)
        self.fields["min_opening_deposit"].help_text = "Minimum is ₱5,000.00."
        self.fields["max_balance"].help_text = (
            "Highest balance for this time deposit. ₱10,000,000.00 is allowed."
        )
        months = self.fields["interest_apply_months"]
        months.min_value = 1
        months.max_value = 120
        months.widget.attrs.update({"min": 1, "max": 120, "step": 1})
        if self.instance and self.instance.pk:
            self.fields["is_time_deposit"].initial = (
                "1"
                if self.instance.product_type == models.SavingsProduct.ProductType.TIME_DEPOSIT
                else "0"
            )
        elif not self.is_bound:
            self.fields["name"].initial = "Regular Savings"
            self.fields["is_active"].initial = True
            self.fields["is_time_deposit"].initial = "0"
            self.fields["interest_rate"].initial = Decimal("0.020")
            self.fields["rate_3_months"].initial = Decimal("0.010")
            self.fields["rate_6_months"].initial = Decimal("0.010")
            self.fields["rate_1_year"].initial = Decimal("0.030")
            self.fields["min_opening_deposit"].initial = Decimal("5000.00")
            self.fields["max_balance"].initial = Decimal("999999.99")
            self.fields["allows_withdrawal"].initial = True

    def clean_code(self):
        raw = (self.cleaned_data.get("code") or "").strip()
        name = (self.data.get("name") or self.cleaned_data.get("name") or "").strip()
        code = slugify(raw) or slugify(name) or "regular-savings"
        qs = models.SavingsProduct.objects.filter(code=code)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            code = f"{code}-{uuid.uuid4().hex[:6]}"
        return code[:40]

    def clean_interest_apply_months(self):
        if self._truthy_flag(self.data.get("is_time_deposit")):
            return 12
        value = self.cleaned_data.get("interest_apply_months")
        if value is None or value < 1 or value > 120:
            raise forms.ValidationError("Enter a number of months from 1 to 120.")
        return value

    def clean_is_time_deposit(self):
        return self._truthy_flag(self.cleaned_data.get("is_time_deposit", "0"))

    def clean(self):
        cleaned = super().clean()
        enabled = bool(cleaned.get("is_time_deposit"))
        regular_types = {
            models.SavingsProduct.ProductType.REGULAR,
            models.SavingsProduct.ProductType.TIME_DEPOSIT,
        }
        if not enabled:
            for name in TIME_DEPOSIT_FIELDS:
                self._errors.pop(name, None)
            if cleaned.get("interest_rate") is None:
                cleaned["interest_rate"] = ANNUAL_INTEREST_RATE
            for name, default in (
                ("rate_3_months", Decimal("0.010")),
                ("rate_6_months", Decimal("0.010")),
                ("rate_1_year", Decimal("0.030")),
            ):
                if cleaned.get(name) is None:
                    cleaned[name] = default
            if not self.instance.pk or self.instance.product_type in regular_types:
                self.instance.product_type = models.SavingsProduct.ProductType.REGULAR
            return cleaned

        self.instance.product_type = models.SavingsProduct.ProductType.TIME_DEPOSIT

        rate = cleaned.get("interest_rate")
        if rate is None:
            self.add_error("interest_rate", "Enter an interest rate for this time deposit.")
        elif rate < 0:
            self.add_error("interest_rate", "Interest rate cannot be negative.")

        for name, default in (
            ("rate_3_months", Decimal("0.010")),
            ("rate_6_months", Decimal("0.010")),
            ("rate_1_year", Decimal("0.030")),
        ):
            value = cleaned.get(name)
            if value is None:
                cleaned[name] = default
            elif value < 0:
                self.add_error(name, "Interest cannot be negative.")

        opening = cleaned.get("min_opening_deposit")
        if opening is None:
            cleaned["min_opening_deposit"] = Decimal("5000.00")
            opening = cleaned["min_opening_deposit"]
        elif opening < Decimal("5000.00"):
            self.add_error(
                "min_opening_deposit",
                "Time deposit minimum is ₱5,000.00.",
            )
        ceiling = cleaned.get("max_balance")
        if not ceiling:
            cleaned["max_balance"] = Decimal("999999.99")
            ceiling = cleaned["max_balance"]
        if ceiling and opening is not None and ceiling < opening:
            self.add_error(
                "max_balance",
                "Maximum balance must be at least the minimum opening deposit.",
            )
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        enabled = bool(self.cleaned_data.get("is_time_deposit"))
        original_type = self._original_product_type
        if enabled:
            instance.product_type = models.SavingsProduct.ProductType.TIME_DEPOSIT
            instance.interest_apply_months = 12
            instance.term_months = 0
            instance.compounding = models.SavingsProduct.Compounding.ANNUALLY
            instance.early_withdrawal_penalty_percent = Decimal("0.000")
            if instance.min_opening_deposit is None or instance.min_opening_deposit < Decimal("5000.00"):
                instance.min_opening_deposit = Decimal("5000.00")
            if not instance.max_balance:
                instance.max_balance = Decimal("999999.99")
            if original_type is None:
                for field_name, value in TIME_DEPOSIT_CREATE_DEFAULTS.items():
                    setattr(instance, field_name, value)
        elif original_type in (
            None,
            models.SavingsProduct.ProductType.REGULAR,
            models.SavingsProduct.ProductType.TIME_DEPOSIT,
        ):
            for field_name, value in REGULAR_NATURAL_DEFAULTS.items():
                setattr(instance, field_name, value)
        else:
            instance.product_type = original_type
            for field_name, value in self._original_time_deposit_values.items():
                setattr(instance, field_name, value)
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class OpenSavingsAccountForm(forms.Form):
    member = forms.ModelChoiceField(
        queryset=Member.objects.filter(
            is_active=True,
            member_role__slug="member",
        ).order_by("last_name", "first_name"),
        label="Primary member",
        empty_label="Search member...",
        widget=forms.Select(attrs={"autocomplete": "off"}),
    )
    is_joint = forms.BooleanField(
        required=False,
        initial=False,
        label="Joint account",
        help_text="Share this Regular Savings account with another member (co-owner).",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input", "id": "id_is_joint"}),
    )
    joint_member = forms.ModelChoiceField(
        queryset=Member.objects.filter(
            is_active=True,
            member_role__slug="member",
        ).order_by("last_name", "first_name"),
        required=False,
        label="Joint co-owner",
        empty_label="Search co-owner...",
        widget=forms.Select(attrs={"autocomplete": "off"}),
    )
    product = forms.ModelChoiceField(
        queryset=models.SavingsProduct.objects.filter(
            is_active=True,
            product_type__in=[
                models.SavingsProduct.ProductType.REGULAR,
                models.SavingsProduct.ProductType.TIME_DEPOSIT,
            ],
        ).order_by("product_type", "name"),
        required=False,
        label="Savings product",
        empty_label=None,
    )
    deposit_term_months = forms.ChoiceField(
        required=False,
        label="Member's term",
        choices=[
            ("3", "3 months"),
            ("6", "6 months"),
            ("12", "1 year"),
        ],
        widget=forms.RadioSelect,
    )
    opening_amount = MoneyField(
        min_value=Decimal("0.01"),
        max_digits=12,
        decimal_places=2,
        label="Opening deposit",
        widget=money_input(min="0.01", placeholder="1,000.00"),
    )
    opening_date = forms.DateField(
        label="Opening date",
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        help_text="Official date this member's savings account starts. Defaults to today.",
    )
    notes = forms.CharField(
        required=False,
        label="Notes (optional)",
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "placeholder": "e.g. walk-in opening, referral source",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        # Always resolve Regular Savings before binding so a missing hidden
        # product field never blocks account opening.
        regular_product = models.SavingsProduct.ensure_regular_product()
        data = kwargs.get("data")
        if data is not None:
            data = data.copy()
            if not data.get("product"):
                data["product"] = str(regular_product.pk)
            kwargs["data"] = data

        super().__init__(*args, **kwargs)
        self.fields["product"].queryset = models.SavingsProduct.objects.filter(
            is_active=True,
            product_type__in=[
                models.SavingsProduct.ProductType.REGULAR,
                models.SavingsProduct.ProductType.TIME_DEPOSIT,
            ],
        ).order_by("product_type", "name")
        # Members who closed savings cannot open again. A second open account
        # of the same product is blocked in clean().
        closed_primary_ids = models.MemberSavingsAccount.objects.filter(
            status=models.MemberSavingsAccount.Status.CLOSED,
        ).values("member_id")
        closed_joint_ids = models.SavingsJointOwner.objects.filter(
            account__status=models.MemberSavingsAccount.Status.CLOSED,
        ).values("member_id")
        eligible_qs = (
            Member.objects.filter(
                is_active=True,
                member_role__slug="member",
            )
            .exclude(pk__in=closed_primary_ids)
            .exclude(pk__in=closed_joint_ids)
            .order_by("last_name", "first_name")
        )
        label_fn = lambda m: f"{m.full_name} ({m.username or m.rfid_card_number or m.pk})"
        self.fields["member"].queryset = eligible_qs
        self.fields["member"].label_from_instance = label_fn
        self.fields["joint_member"].queryset = eligible_qs
        self.fields["joint_member"].label_from_instance = label_fn
        self.regular_product = (
            self.fields["product"].queryset.filter(pk=regular_product.pk).first()
            or self.fields["product"].queryset.first()
            or regular_product
        )
        self.fields["product"].initial = self.regular_product.pk
        min_open = self.regular_product.min_opening_deposit or Decimal("0.00")
        if min_open > Decimal("0.00"):
            opening = self.fields["opening_amount"]
            opening.min_value = min_open
            opening.validators = [
                v
                for v in opening.validators
                if not v.__class__.__name__.endswith("MinValueValidator")
            ]
            opening.validators.append(MinValueValidator(min_open))
            opening.widget.attrs["min"] = str(min_open)
            opening.help_text = f"Minimum ₱{min_open:,.2f} for {self.regular_product.name}."
        today = timezone.localdate()
        opening_date = self.fields["opening_date"]
        if not self.data:
            opening_date.initial = today
        opening_date.widget.attrs["max"] = today.isoformat()

    def opening_product_catalog(self):
        rows = []
        for product in self.fields["product"].queryset:
            rows.append(
                {
                    "id": str(product.pk),
                    "name": product.name,
                    "type": product.product_type,
                    "min": str(product.min_opening_deposit or 0),
                    "max": str(product.max_balance or 0),
                    "rate": str(product.interest_rate or 0),
                    "rate3": str(getattr(product, "rate_3_months", "0.010")),
                    "rate6": str(getattr(product, "rate_6_months", "0.010")),
                    "rate1": str(getattr(product, "rate_1_year", "0.030")),
                }
            )
        return rows

    def clean_member(self):
        member = self.cleaned_data["member"]
        from . import services

        try:
            # Product-specific check runs in clean() once product is known.
            services.assert_member_can_open_savings(member, product=None)
        except ValidationError as exc:
            raise forms.ValidationError(
                " ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            ) from exc
        return member

    def clean_joint_member(self):
        joint_member = self.cleaned_data.get("joint_member")
        if not joint_member:
            return joint_member
        # Primary may already be in cleaned_data; fall back to raw POST/data.
        primary = self.cleaned_data.get("member")
        if primary is None:
            raw = (self.data.get("member") or "").strip()
            if raw:
                primary = Member.objects.filter(pk=raw).first()
        if primary and joint_member.pk == primary.pk:
            raise forms.ValidationError(
                "Duplicate member: the co-owner must be different from the primary holder."
            )
        from . import services

        try:
            services.assert_member_can_open_savings(joint_member, product=None)
        except ValidationError as exc:
            raise forms.ValidationError(
                " ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            ) from exc
        return joint_member

    def clean_product(self):
        product = self.cleaned_data.get("product") or self.regular_product
        if not product:
            product = models.SavingsProduct.ensure_regular_product()
        if not product:
            raise forms.ValidationError(
                "No active Regular Savings product is set up yet. Add one under Regular Savings first."
            )
        return product

    def clean_opening_date(self):
        value = self.cleaned_data.get("opening_date")
        if value and value > timezone.localdate():
            raise forms.ValidationError("Opening date cannot be in the future.")
        return value

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("product"):
            cleaned["product"] = self.regular_product or models.SavingsProduct.ensure_regular_product()
        member = cleaned.get("member")
        product = cleaned.get("product")
        is_joint = bool(cleaned.get("is_joint"))
        joint_member = cleaned.get("joint_member")
        cleaned["is_joint"] = is_joint

        if is_joint:
            if not joint_member:
                self.add_error("joint_member", "Select a joint co-owner for this account.")
            elif member and joint_member and joint_member.pk == member.pk:
                self.add_error(
                    "joint_member",
                    "Duplicate member: the co-owner must be different from the primary holder.",
                )
                cleaned["joint_member"] = None
                joint_member = None
        else:
            cleaned["joint_member"] = None
            joint_member = None

        from . import services

        if member and product:
            try:
                services.assert_member_can_open_savings(member, product)
            except ValidationError as exc:
                self.add_error(
                    "member",
                    " ".join(exc.messages) if hasattr(exc, "messages") else str(exc),
                )
        if joint_member and product:
            try:
                services.assert_member_can_open_savings(joint_member, product)
            except ValidationError as exc:
                self.add_error(
                    "joint_member",
                    " ".join(exc.messages) if hasattr(exc, "messages") else str(exc),
                )

        amount = cleaned.get("opening_amount")
        if product and amount is not None:
            min_open = product.min_opening_deposit
            if min_open > Decimal("0.00") and amount < min_open:
                self.add_error(
                    "opening_amount",
                    f"Opening deposit must be at least ₱{min_open:,.2f}.",
                )
            max_bal = product.max_balance or Decimal("0.00")
            if max_bal > Decimal("0.00") and amount > max_bal:
                self.add_error(
                    "opening_amount",
                    f"Opening deposit cannot exceed the maximum balance of ₱{max_bal:,.2f}.",
                )
        is_time_deposit = (
            product is not None
            and product.product_type == models.SavingsProduct.ProductType.TIME_DEPOSIT
        )
        term = (cleaned.get("deposit_term_months") or "").strip()
        from .policy import time_deposit_uses_term

        if is_time_deposit and amount is not None and time_deposit_uses_term(amount):
            if term not in {"3", "6", "12"}:
                self.add_error(
                    "deposit_term_months",
                    "For ₱100,001 and above, select 3 months, 6 months, or 1 year.",
                )
            else:
                cleaned["deposit_term_months"] = int(term)
        else:
            cleaned["deposit_term_months"] = None
        return cleaned


class SavingsMovementForm(forms.Form):
    amount = MoneyField(
        min_value=Decimal("0.01"),
        max_digits=12,
        decimal_places=2,
        label="Amount",
        widget=money_input(min="0.01", placeholder="0.00"),
    )
    notes = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Optional note"}),
    )


class CloseSavingsAccountForm(forms.Form):
    notes = forms.CharField(
        required=False,
        label="Closing remark",
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "class": "form-control",
                "placeholder": "Optional note (e.g. reason for resignation).",
            }
        ),
    )
    mark_member_resign = forms.BooleanField(
        required=False,
        initial=True,
        label="Set member status to Resign (savings only)",
        help_text=(
            "Sets membership status to Resign for this savings exit. "
            "The member stays active and can still use loans, credit, and "
            "other coop services — only savings is permanently barred."
        ),
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
