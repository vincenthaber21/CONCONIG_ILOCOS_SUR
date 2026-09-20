from decimal import Decimal

from django import forms

from helper.money_forms import MoneyField, money_input
from members.models import Member

from . import models


class PalayCreditSettingsForm(forms.ModelForm):
    member_max_outstanding = MoneyField(min_value=0, max_digits=12, decimal_places=2, required=False)
    interest_rate = MoneyField(min_value=0, max_digits=6, decimal_places=3, required=False)

    class Meta:
        model = models.PalayCreditSettings
        fields = [
            "is_enabled",
            "member_max_outstanding",
            "grace_period_days",
            "interest_rate",
            "interest_enabled",
            "allow_credit_on_sell",
            "allow_credit_on_buy",
            "min_membership_months",
        ]
        widgets = {
            "grace_period_days": forms.NumberInput(attrs={"min": 0, "max": 3650}),
            "min_membership_months": forms.NumberInput(attrs={"min": 0, "max": 600}),
        }
        labels = {
            "is_enabled": "Enable palay credit for members",
            "member_max_outstanding": "Max outstanding per member",
            "grace_period_days": "Grace period (days)",
            "interest_rate": "Monthly interest rate",
            "interest_enabled": "Apply interest after grace",
            "allow_credit_on_sell": "Utang from stock (sell tickets)",
            "allow_credit_on_buy": "Credit on buy tickets",
            "min_membership_months": "Minimum membership (months)",
        }
        help_texts = {
            "is_enabled": "Master switch — staff can post member trades on palay credit.",
            "member_max_outstanding": "Total unsettled palay credit cap per member. 0 = no limit.",
            "grace_period_days": "Days before interest may apply on unpaid palay credit.",
            "interest_rate": "Monthly rate after grace (e.g. 0.015 = 1.5%). 0 = no interest.",
            "allow_credit_on_sell": "Member takes rice from stock on utang (owes the coop).",
            "allow_credit_on_buy": "Member sells palay; coop pays later (advanced payment).",
            "min_membership_months": "Months registered before a member may use palay credit.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["member_max_outstanding"].required = False
        self.fields["interest_rate"].required = False

    def _money(self, field, default="0.00"):
        value = self.cleaned_data.get(field)
        return value if value is not None else Decimal(default)

    def clean_member_max_outstanding(self):
        return self._money("member_max_outstanding")

    def clean_interest_rate(self):
        return self._money("interest_rate")


class PalayTradeProductFeaturesForm(forms.ModelForm):
    """Edit rates, stock, and limits for Rice Palay / Bigas only."""

    buy_price_per_kg = MoneyField(min_value=0, max_digits=12, decimal_places=2)
    sell_price_per_kg = MoneyField(min_value=0, max_digits=12, decimal_places=2)
    stock_kg = MoneyField(min_value=0, max_digits=12, decimal_places=2)
    low_stock_kg = MoneyField(min_value=0, max_digits=12, decimal_places=2)
    min_quantity_kg = MoneyField(min_value=0, max_digits=12, decimal_places=2)
    max_quantity_kg = MoneyField(min_value=0, max_digits=12, decimal_places=2)

    class Meta:
        model = models.PalayTradeProduct
        fields = [
            "buy_price_per_kg",
            "sell_price_per_kg",
            "stock_kg",
            "low_stock_kg",
            "min_quantity_kg",
            "max_quantity_kg",
            "members_only",
            "credit_enabled",
            "description",
        ]
        widgets = {
            "description": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Optional notes about this product"}
            ),
        }
        labels = {
            "buy_price_per_kg": "Buy price per kg",
            "sell_price_per_kg": "Sell price per kg",
            "stock_kg": "Current stock (kg)",
            "low_stock_kg": "Low-stock alert (kg)",
            "min_quantity_kg": "Minimum quantity (kg)",
            "max_quantity_kg": "Maximum quantity (kg)",
            "members_only": "Members only",
            "credit_enabled": "Palay credit allowed",
            "description": "Notes",
        }
        help_texts = {
            "buy_price_per_kg": "Default rate when buying from a farmer.",
            "sell_price_per_kg": "Default rate when selling from stock.",
            "stock_kg": "Adjust opening or corrected stock. Trades still add/deduct after this.",
            "low_stock_kg": "Warn on the desk when stock falls to this level. Use 0 to disable.",
            "min_quantity_kg": "Optional minimum kg per ticket. 0 = no minimum.",
            "max_quantity_kg": "Optional maximum kg per ticket. 0 = no maximum.",
            "members_only": "If checked, only cooperative members can trade this product.",
            "credit_enabled": "Members may take this product on palay credit when credit is enabled.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in (
            "buy_price_per_kg",
            "sell_price_per_kg",
            "stock_kg",
            "low_stock_kg",
            "min_quantity_kg",
            "max_quantity_kg",
            "description",
        ):
            self.fields[name].required = False

    def _money(self, field, default="0.00"):
        value = self.cleaned_data.get(field)
        return value if value is not None else Decimal(default)

    def clean_buy_price_per_kg(self):
        return self._money("buy_price_per_kg")

    def clean_sell_price_per_kg(self):
        return self._money("sell_price_per_kg")

    def clean_stock_kg(self):
        return self._money("stock_kg")

    def clean_low_stock_kg(self):
        return self._money("low_stock_kg")

    def clean_min_quantity_kg(self):
        return self._money("min_quantity_kg")

    def clean_max_quantity_kg(self):
        return self._money("max_quantity_kg")


class PalayTradeForm(forms.Form):
    product = forms.ModelChoiceField(
        queryset=models.PalayTradeProduct.objects.none(),
        label="Product",
        widget=forms.RadioSelect,
        empty_label=None,
    )
    trade_type = forms.ChoiceField(
        choices=models.PalayTrade.TradeType.choices,
        label="Trade type",
        widget=forms.RadioSelect,
        initial=models.PalayTrade.TradeType.BUY,
    )
    member = forms.ModelChoiceField(
        queryset=Member.objects.filter(
            is_active=True,
            member_role__slug="member",
        ).order_by("last_name", "first_name"),
        required=False,
        label="Member (optional)",
        empty_label="Search member...",
        widget=forms.Select(attrs={"autocomplete": "off"}),
    )
    party_name = forms.CharField(
        max_length=200,
        required=False,
        label="Farmer / buyer name",
        help_text="Required when no member is selected.",
        widget=forms.TextInput(
            attrs={"placeholder": "Full name of farmer or buyer", "autocomplete": "name"}
        ),
    )
    gross_kg = MoneyField(
        min_value=Decimal("0.01"),
        max_digits=12,
        decimal_places=2,
        label="Weight (kg)",
        widget=money_input(min="0.01", placeholder="0.00"),
    )
    unit_price = MoneyField(
        min_value=Decimal("0.01"),
        max_digits=12,
        decimal_places=2,
        required=False,
        label="Unit price per kg",
        help_text="Filled from the product rate. You can override it.",
        widget=money_input(min="0.01", placeholder="0.00"),
    )
    notes = forms.CharField(
        required=False,
        label="Notes (optional)",
        widget=forms.Textarea(
            attrs={"rows": 2, "placeholder": "Optional remark for this ticket"}
        ),
    )
    payment_method = forms.ChoiceField(
        choices=models.PalayTrade.PaymentMethod.choices,
        label="Payment",
        initial=models.PalayTrade.PaymentMethod.CASH,
        widget=forms.RadioSelect,
    )

    def __init__(self, *args, **kwargs):
        self.credit_settings = kwargs.pop("credit_settings", None)
        super().__init__(*args, **kwargs)
        products = models.PalayTradeProduct.active_trade_products()
        self.fields["product"].queryset = products
        self.fields["member"].label_from_instance = (
            lambda m: f"{m.full_name} ({m.username or m.rfid_card_number or m.pk})"
        )
        self.fields["product"].label_from_instance = lambda p: p.name
        if not self.is_bound and products.exists() and not self.initial.get("product"):
            self.fields["product"].initial = products.first().pk
        settings = self.credit_settings or models.PalayCreditSettings.get()
        if not settings.is_enabled:
            self.fields["payment_method"].choices = [
                (models.PalayTrade.PaymentMethod.CASH, "Cash"),
            ]
            self.fields["payment_method"].initial = models.PalayTrade.PaymentMethod.CASH

    def clean(self):
        cleaned = super().clean()
        member = cleaned.get("member")
        party = (cleaned.get("party_name") or "").strip()
        product = cleaned.get("product")
        payment_method = cleaned.get("payment_method") or models.PalayTrade.PaymentMethod.CASH
        if member:
            cleaned["party_name"] = member.full_name
        elif not party:
            self.add_error("party_name", "Enter a farmer/buyer name or select a member.")
        else:
            cleaned["party_name"] = party
        if product and product.members_only and not member:
            self.add_error("member", "This product requires a cooperative member.")
        if payment_method == models.PalayTrade.PaymentMethod.CREDIT and not member:
            self.add_error("payment_method", "Palay credit requires a cooperative member.")
        cleaned["payment_method"] = payment_method
        return cleaned


class PalayCreditUtangForm(forms.Form):
    """Member takes rice from stock on utang (sell + palay credit)."""

    MEMBER_PREVIEW_LIMIT = 10

    member = forms.ModelChoiceField(
        queryset=Member.objects.none(),
        label="Member",
        empty_label="Search member…",
        widget=forms.Select(attrs={"autocomplete": "off"}),
    )
    product = forms.ModelChoiceField(
        queryset=models.PalayTradeProduct.objects.none(),
        label="Rice from stock",
        widget=forms.RadioSelect,
        empty_label=None,
    )
    gross_kg = MoneyField(
        min_value=Decimal("0.01"),
        max_digits=12,
        decimal_places=2,
        label="Kilos (utang)",
        widget=money_input(min="0.01", placeholder="0.00"),
    )
    notes = forms.CharField(
        required=False,
        label="Notes (optional)",
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Optional remark for this utang ticket"}),
    )

    @classmethod
    def member_queryset(cls):
        return Member.objects.filter(
            is_active=True,
            member_role__slug="member",
        ).order_by("last_name", "first_name")

    @classmethod
    def member_label(cls, member):
        return f"{member.full_name} ({member.username or member.rfid_card_number or member.pk})"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        products = models.PalayTradeProduct.active_trade_products()
        self.fields["product"].queryset = products
        self.fields["member"].label_from_instance = self.member_label

        base_members = self.member_queryset()
        preview_ids = list(base_members.values_list("pk", flat=True)[: self.MEMBER_PREVIEW_LIMIT])
        if self.is_bound:
            raw = self.data.get(self.add_prefix("member"))
            if raw:
                try:
                    selected_id = int(raw)
                except (TypeError, ValueError):
                    selected_id = None
                if selected_id and selected_id not in preview_ids:
                    preview_ids.append(selected_id)
        self.fields["member"].queryset = base_members.filter(pk__in=preview_ids)

        self.fields["product"].label_from_instance = lambda p: p.name
        if not self.is_bound and products.exists():
            self.fields["product"].initial = products.first().pk

    def clean_member(self):
        member = self.cleaned_data.get("member")
        if member and member.role != "member":
            raise forms.ValidationError("Only cooperative members may take rice on utang.")
        return member

    def clean(self):
        cleaned = super().clean()
        member = cleaned.get("member")
        if member:
            cleaned["party_name"] = member.full_name
        return cleaned
