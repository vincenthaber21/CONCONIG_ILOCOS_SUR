import uuid
from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.text import slugify

from helper.money_forms import MoneyField, money_input
from members.models import Member

from . import models
from .policy import ANNUAL_INTEREST_RATE

# Natural / passbook regular savings — fixed coop defaults (not editable).
REGULAR_NATURAL_DEFAULTS = {
    "product_type": models.SavingsProduct.ProductType.REGULAR,
    "interest_rate": ANNUAL_INTEREST_RATE,
    "compounding": models.SavingsProduct.Compounding.ANNUALLY,
    "min_opening_deposit": Decimal("1000.00"),
    "max_balance": Decimal("1000000.00"),
    "term_months": 0,
    "min_maintaining_balance": Decimal("0.00"),
    "min_additional_deposit": Decimal("0.00"),
    "allows_withdrawal": True,
    "withdrawal_notice_days": 0,
    "max_free_withdrawals_per_month": 0,
    "early_withdrawal_penalty_percent": Decimal("0.000"),
    "dividend_eligible": False,
    "required_for_membership": False,
}


class SavingsProductForm(forms.ModelForm):
    """Simple Regular Savings product form — policy values are fixed, not shown as inputs."""

    code = forms.CharField(
        max_length=40,
        required=False,
        help_text="Optional. Leave blank to generate from the name.",
    )

    class Meta:
        model = models.SavingsProduct
        fields = ["name", "code", "description", "is_active"]
        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Optional note for staff (e.g. passbook savings for members).",
                }
            ),
            "name": forms.TextInput(attrs={"placeholder": "Regular Savings"}),
        }
        labels = {
            "name": "Display name",
            "is_active": "Active (available when opening accounts)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["description"].required = False
        self.fields["is_active"].required = False
        if not self.instance.pk and not self.data:
            self.fields["name"].initial = "Regular Savings"
            self.fields["is_active"].initial = True

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

    def save(self, commit=True):
        instance = super().save(commit=False)
        if not self.instance.pk:
            for field_name, value in REGULAR_NATURAL_DEFAULTS.items():
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
        label="Member",
        empty_label="Search member...",
        widget=forms.Select(attrs={"autocomplete": "off"}),
    )
    product = forms.ModelChoiceField(
        queryset=models.SavingsProduct.objects.filter(
            is_active=True,
            product_type=models.SavingsProduct.ProductType.REGULAR,
        ).order_by("name"),
        widget=forms.HiddenInput(),
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
        super().__init__(*args, **kwargs)
        # Members who closed savings (or already hold an open Regular account)
        # cannot open again.
        closed_member_ids = models.MemberSavingsAccount.objects.filter(
            status=models.MemberSavingsAccount.Status.CLOSED,
        ).values("member_id")
        open_regular_member_ids = models.MemberSavingsAccount.objects.filter(
            product__product_type=models.SavingsProduct.ProductType.REGULAR,
        ).exclude(
            status=models.MemberSavingsAccount.Status.CLOSED,
        ).values("member_id")
        self.fields["member"].queryset = (
            Member.objects.filter(
                is_active=True,
                member_role__slug="member",
            )
            .exclude(pk__in=closed_member_ids)
            .exclude(pk__in=open_regular_member_ids)
            .order_by("last_name", "first_name")
        )
        self.fields["member"].label_from_instance = (
            lambda m: f"{m.full_name} ({m.username or m.rfid_card_number or m.pk})"
        )
        self.regular_product = (
            self.fields["product"].queryset.first()
        )
        if self.regular_product and not self.data:
            self.fields["product"].initial = self.regular_product.pk
        if not self.regular_product:
            self.fields["product"].required = False
        elif self.regular_product.min_opening_deposit > Decimal("0.00"):
            min_open = self.regular_product.min_opening_deposit
            opening = self.fields["opening_amount"]
            opening.min_value = min_open
            opening.widget.attrs["min"] = str(min_open)
            opening.help_text = f"Minimum ₱{min_open:,.2f} for {self.regular_product.name}."
        today = timezone.localdate()
        opening = self.fields["opening_date"]
        if not self.data:
            opening.initial = today
        opening.widget.attrs["max"] = today.isoformat()

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

    def clean_product(self):
        product = self.cleaned_data.get("product") or self.regular_product
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
        if not cleaned.get("product") and self.regular_product:
            cleaned["product"] = self.regular_product
        member = cleaned.get("member")
        product = cleaned.get("product")
        if member and product:
            from . import services

            try:
                services.assert_member_can_open_savings(member, product)
            except ValidationError as exc:
                self.add_error(
                    "member",
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
