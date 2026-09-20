import uuid
from decimal import Decimal

from django import forms
from django.utils.text import slugify

from helper.money_forms import MoneyField, money_input
from members.models import Member

from . import models


class ShareCapitalProductForm(forms.ModelForm):
    code = forms.CharField(
        max_length=40,
        required=False,
        help_text="Optional. Leave blank to generate from the name.",
    )
    par_value = MoneyField(
        min_value=Decimal("0.01"),
        max_digits=12,
        decimal_places=2,
        label="Par value per share",
        widget=money_input(min="0.01", placeholder="100.00"),
    )
    min_contribution = MoneyField(
        min_value=Decimal("0.00"),
        max_digits=12,
        decimal_places=2,
        required=False,
        label="Minimum opening contribution",
        widget=money_input(min="0", placeholder="0.00"),
    )

    class Meta:
        model = models.ShareCapitalProduct
        fields = [
            "name",
            "code",
            "description",
            "par_value",
            "min_shares",
            "max_shares",
            "min_contribution",
            "dividend_rate",
            "allows_withdrawal",
            "required_for_membership",
            "is_active",
        ]
        widgets = {
            "description": forms.Textarea(
                attrs={
                    "rows": 3,
                    "placeholder": "Optional note for staff (e.g. common shares for regular members).",
                }
            ),
            "name": forms.TextInput(attrs={"placeholder": "Common Share Capital"}),
            "min_shares": forms.NumberInput(attrs={"min": 0, "step": 1}),
            "max_shares": forms.NumberInput(attrs={"min": 0, "step": 1}),
            "dividend_rate": forms.NumberInput(attrs={"min": 0, "step": "0.001"}),
        }
        labels = {
            "min_shares": "Minimum shares",
            "max_shares": "Maximum shares (0 = no limit)",
            "dividend_rate": "Annual dividend rate (%)",
            "allows_withdrawal": "Allow withdrawals",
            "required_for_membership": "Required for membership",
            "is_active": "Active (available on the share capital desk)",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["description"].required = False
        self.fields["is_active"].required = False
        self.fields["allows_withdrawal"].required = False
        self.fields["required_for_membership"].required = False
        self.fields["min_contribution"].required = False
        if not self.instance.pk and not self.data:
            self.fields["name"].initial = "Common Share Capital"
            self.fields["par_value"].initial = Decimal("100.00")
            self.fields["min_shares"].initial = 1
            self.fields["required_for_membership"].initial = True
            self.fields["is_active"].initial = True

    def clean_code(self):
        raw = (self.cleaned_data.get("code") or "").strip()
        name = (self.data.get("name") or self.cleaned_data.get("name") or "").strip()
        code = slugify(raw) or slugify(name) or "share-capital"
        qs = models.ShareCapitalProduct.objects.filter(code=code)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            code = f"{code}-{uuid.uuid4().hex[:6]}"
        return code[:40]

    def clean_min_contribution(self):
        value = self.cleaned_data.get("min_contribution")
        return value if value is not None else Decimal("0.00")



class ShareCapitalContributeForm(forms.Form):
    member = forms.ModelChoiceField(
        queryset=Member.objects.filter(
            is_active=True,
            member_role__slug="member",
        ).order_by("last_name", "first_name"),
        label="Member",
        empty_label="Search member...",
        widget=forms.Select(attrs={"autocomplete": "off"}),
    )
    amount = MoneyField(
        min_value=Decimal("0.01"),
        max_digits=12,
        decimal_places=2,
        label="Contribution amount",
        widget=money_input(min="0.01", placeholder="0.00"),
    )
    notes = forms.CharField(
        required=False,
        label="Notes (optional)",
        widget=forms.Textarea(
            attrs={
                "rows": 2,
                "placeholder": "e.g. initial subscription, additional shares",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        self.product = kwargs.pop("product", None)
        super().__init__(*args, **kwargs)
        self.share_product = self.product
        self.fields["member"].label_from_instance = (
            lambda m: f"{m.full_name} ({m.username or m.rfid_card_number or m.pk})"
        )
        product = self.product
        if product:
            floor = product.min_contribution or product.min_paid_up
            if floor and floor > Decimal("0.00"):
                self.fields["amount"].help_text = (
                    f"Minimum ₱{floor:,.2f} for {product.name}."
                )
            min_open = floor or Decimal("0.00")
            if min_open > Decimal("0.00"):
                opening = self.fields["amount"]
                opening.min_value = min_open
                opening.widget.attrs["min"] = str(min_open)


class ShareCapitalMovementForm(forms.Form):
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
