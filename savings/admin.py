from decimal import Decimal

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import ValidationError
from django.utils import timezone

from members.models import Member

from . import models, services


class SavingsProductAdminForm(forms.ModelForm):
    class Meta:
        model = models.SavingsProduct
        fields = "__all__"

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        instance = self.instance or models.SavingsProduct()
        for name, value in cleaned.items():
            setattr(instance, name, value)
        try:
            instance.clean()
        except ValidationError as exc:
            raise forms.ValidationError(exc.message_dict) from exc
        return cleaned


@admin.register(models.SavingsProduct)
class SavingsProductAdmin(admin.ModelAdmin):
    form = SavingsProductAdminForm
    list_display = (
        "name",
        "code",
        "product_type",
        "interest_rate",
        "min_opening_deposit",
        "term_months",
        "allows_withdrawal",
        "is_active",
    )
    list_filter = ("product_type", "is_active", "allows_withdrawal", "dividend_eligible")
    search_fields = ("name", "code", "description")
    list_editable = ("is_active",)
    fieldsets = (
        (
            None,
            {
                "fields": ("name", "code", "product_type", "description", "is_active"),
            },
        ),
        (
            "Interest",
            {
                "fields": ("interest_rate", "compounding"),
                "description": (
                    "Annual rate is a flat 5%. Interest is credited monthly on the "
                    "opening anniversary (same calendar day) as (balance × 5%) ÷ 12."
                ),
            },
        ),
        (
            "Minimums & term",
            {
                "fields": (
                    "min_opening_deposit",
                    "max_balance",
                    "min_maintaining_balance",
                    "min_additional_deposit",
                    "term_months",
                ),
            },
        ),
        (
            "Withdrawal rules",
            {
                "fields": (
                    "allows_withdrawal",
                    "withdrawal_notice_days",
                    "max_free_withdrawals_per_month",
                    "early_withdrawal_penalty_percent",
                ),
            },
        ),
        (
            "Membership",
            {
                "fields": ("dividend_eligible", "required_for_membership"),
            },
        ),
    )

    def get_deleted_objects(self, objs, request):
        """Allow staff to delete products that still have member savings accounts.

        Related accounts (and their ledger transactions) are deleted with the
        product via CASCADE.
        """
        deleted_objects, model_count, perms_needed, protected = super().get_deleted_objects(
            objs, request
        )
        if not (request.user.is_superuser or request.user.is_staff):
            return deleted_objects, model_count, perms_needed, protected

        protected = []
        return deleted_objects, model_count, perms_needed, protected

    def has_delete_permission(self, request, obj=None):
        return request.user.is_active and (
            request.user.is_superuser or request.user.is_staff
        )


class MemberSavingsAccountAdminForm(forms.ModelForm):
    opening_amount = forms.DecimalField(
        min_value=Decimal("0.01"),
        max_digits=12,
        decimal_places=2,
        required=False,
        help_text="Required when creating an account. Posted as the opening deposit.",
    )
    opening_date = forms.DateField(
        required=False,
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
        help_text="Official date this member's savings account starts. Defaults to today.",
    )

    class Meta:
        model = models.MemberSavingsAccount
        fields = ("member", "product", "status", "notes", "closed_at")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        member_qs = Member.objects.filter(
            is_active=True,
            member_role__slug="member",
        )
        if self.instance.pk and self.instance.member_id:
            member_qs = (
                member_qs | Member.objects.filter(pk=self.instance.member_id)
            ).distinct()
        self.fields["member"].queryset = member_qs.order_by("last_name", "first_name")
        product = None
        product_id = (self.data.get("product") if self.data else None) or self.initial.get(
            "product"
        )
        if product_id:
            product = models.SavingsProduct.objects.filter(pk=product_id).first()
        today = timezone.localdate()
        self.fields["opening_date"].widget.attrs["max"] = today.isoformat()
        if product and product.min_opening_deposit > Decimal("0.00"):
            self.fields["opening_amount"].min_value = product.min_opening_deposit
            self.fields["opening_amount"].help_text = (
                f"Required when creating an account. Minimum ₱{product.min_opening_deposit:,.2f} "
                f"for {product.name}."
            )
        if self.instance.pk:
            self.fields["opening_amount"].widget = forms.HiddenInput()
            self.fields["opening_date"].widget = forms.HiddenInput()
        else:
            self.fields["opening_amount"].required = True
            self.fields["opening_date"].required = True
            self.fields["opening_date"].initial = today

    def clean_opening_date(self):
        value = self.cleaned_data.get("opening_date")
        if value and value > timezone.localdate():
            raise forms.ValidationError("Opening date cannot be in the future.")
        return value

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk:
            return cleaned
        member = cleaned.get("member")
        product = cleaned.get("product")
        amount = cleaned.get("opening_amount")
        if member and product:
            try:
                services.assert_member_can_open_savings(member, product)
            except ValidationError as exc:
                self.add_error(
                    "member",
                    " ".join(exc.messages) if hasattr(exc, "messages") else str(exc),
                )
        if member and product and amount is not None:
            try:
                if not product.is_active:
                    raise ValidationError("This savings product is not active.")
                if amount < product.min_opening_deposit:
                    raise ValidationError(
                        {
                            "opening_amount": (
                                f"Opening deposit must be at least ₱{product.min_opening_deposit}."
                            )
                        }
                    )
            except ValidationError:
                raise
        return cleaned


class SavingsTransactionInline(admin.TabularInline):
    model = models.SavingsTransaction
    extra = 0
    fields = (
        "reference",
        "transaction_type",
        "amount",
        "balance_before",
        "balance_after",
        "notes",
        "performed_by",
        "created_at",
    )
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(models.MemberSavingsAccount)
class MemberSavingsAccountAdmin(admin.ModelAdmin):
    form = MemberSavingsAccountAdminForm
    list_display = (
        "account_number",
        "member",
        "product",
        "balance",
        "status",
        "opened_at",
        "maturity_date",
    )
    list_filter = ("status", "product")
    search_fields = (
        "account_number",
        "member__first_name",
        "member__last_name",
        "member__username",
        "member__rfid_card_number",
    )
    autocomplete_fields = ("member", "product")
    readonly_fields = ("account_number", "balance", "opened_at", "maturity_date")
    inlines = [SavingsTransactionInline]
    fieldsets = (
        (
            None,
            {
                "fields": ("member", "product", "opening_amount", "opening_date", "status", "notes"),
                "description": (
                    "Saving a new account writes it to the database, assigns an "
                    "account number, and posts the opening deposit to the ledger."
                ),
            },
        ),
        (
            "Record",
            {
                "fields": ("account_number", "balance", "opened_at", "maturity_date", "closed_at"),
            },
        ),
    )

    def get_fieldsets(self, request, obj=None):
        if obj:
            return (
                (None, {"fields": ("member", "product", "status", "notes")}),
                (
                    "Record",
                    {
                        "fields": (
                            "account_number",
                            "balance",
                            "opened_at",
                            "maturity_date",
                            "closed_at",
                        ),
                    },
                ),
            )
        return self.fieldsets

    def get_readonly_fields(self, request, obj=None):
        readonly = list(self.readonly_fields)
        if obj:
            readonly.extend(["member", "product"])
        return readonly

    def save_model(self, request, obj, form, change):
        if change:
            super().save_model(request, obj, form, change)
            return
        try:
            created = services.open_account(
                member=form.cleaned_data["member"],
                product=form.cleaned_data["product"],
                opening_amount=form.cleaned_data["opening_amount"],
                performed_by=request.user,
                notes=form.cleaned_data.get("notes") or "",
                opening_date=form.cleaned_data.get("opening_date"),
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            raise
        obj.pk = created.pk
        obj.account_number = created.account_number
        obj.balance = created.balance
        obj.opened_at = created.opened_at
        obj.maturity_date = created.maturity_date
        obj.status = created.status
        messages.success(
            request,
            f"Saved {created.account_number} for {created.member.full_name} "
            f"(balance ₱{created.balance}).",
        )


class SavingsTransactionAdminForm(forms.ModelForm):
    class Meta:
        model = models.SavingsTransaction
        fields = ("account", "transaction_type", "amount", "notes")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        opening = models.SavingsTransaction.TxnType.OPENING
        self.fields["transaction_type"].choices = [
            choice
            for choice in self.fields["transaction_type"].choices
            if choice[0] and choice[0] != opening
        ]

    def clean(self):
        cleaned = super().clean()
        account = cleaned.get("account")
        txn_type = cleaned.get("transaction_type")
        amount = cleaned.get("amount")
        if not (account and txn_type and amount is not None):
            return cleaned
        if txn_type == models.SavingsTransaction.TxnType.OPENING:
            raise ValidationError(
                "Create a member savings account instead of posting type Opening."
            )
        if txn_type == models.SavingsTransaction.TxnType.WITHDRAWAL:
            if not account.product.allows_withdrawal:
                raise ValidationError("Withdrawals are not allowed on this savings product.")
            remaining = account.balance - amount
            if remaining < account.product.min_maintaining_balance:
                raise ValidationError(
                    f"Balance after withdrawal must stay at least "
                    f"₱{account.product.min_maintaining_balance}."
                )
        return cleaned


@admin.register(models.SavingsTransaction)
class SavingsTransactionAdmin(admin.ModelAdmin):
    form = SavingsTransactionAdminForm
    list_display = (
        "reference",
        "account",
        "transaction_type",
        "amount",
        "balance_after",
        "created_at",
    )
    list_filter = ("transaction_type",)
    search_fields = (
        "reference",
        "account__account_number",
        "account__member__first_name",
        "account__member__last_name",
    )
    autocomplete_fields = ("account",)
    actions = ["delete_selected_transactions"]
    readonly_fields = (
        "reference",
        "balance_before",
        "balance_after",
        "performed_by",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            None,
            {
                "fields": ("account", "transaction_type", "amount", "notes"),
                "description": (
                    "Saving a deposit, withdrawal, interest, or penalty updates the "
                    "member account balance in the database. "
                    "Delete only the latest transaction per account — the balance is reversed."
                ),
            },
        ),
        (
            "Posted values",
            {
                "fields": (
                    "reference",
                    "balance_before",
                    "balance_after",
                    "performed_by",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )

    def has_change_permission(self, request, obj=None):
        return obj is None or request.method == "GET"

    def has_delete_permission(self, request, obj=None):
        return request.user.is_staff

    def get_actions(self, request):
        actions = super().get_actions(request)
        # Prefer our balance-safe action over Django's default hard delete.
        if "delete_selected" in actions:
            del actions["delete_selected"]
        return actions

    def _delete_transactions(self, request, queryset):
        deleted = 0
        errors = []
        # Newest first so multi-select on one account can unwind in order.
        ordered = list(queryset.order_by("-created_at", "-id"))
        for txn in ordered:
            try:
                services.delete_transaction(txn, performed_by=request.user)
                deleted += 1
            except ValidationError as exc:
                msg = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
                errors.append(f"{txn.reference}: {msg}")
        return deleted, errors

    @admin.action(description="Delete selected transactions (reverse balance)")
    def delete_selected_transactions(self, request, queryset):
        deleted, errors = self._delete_transactions(request, queryset)
        if deleted:
            self.message_user(
                request,
                f"Deleted {deleted} savings transaction(s) and reversed account balance(s).",
                messages.SUCCESS,
            )
        for msg in errors[:10]:
            self.message_user(request, msg, messages.ERROR)
        if len(errors) > 10:
            self.message_user(
                request,
                f"…and {len(errors) - 10} more error(s).",
                messages.ERROR,
            )

    def delete_model(self, request, obj):
        services.delete_transaction(obj, performed_by=request.user)

    def delete_queryset(self, request, queryset):
        deleted, errors = self._delete_transactions(request, queryset)
        if deleted:
            self.message_user(
                request,
                f"Deleted {deleted} savings transaction(s) and reversed account balance(s).",
                messages.SUCCESS,
            )
        for msg in errors[:10]:
            self.message_user(request, msg, messages.ERROR)

    def delete_view(self, request, object_id, extra_context=None):
        """Confirm delete, then reverse balance; block non-latest rows with a clear error."""
        from django.contrib.admin.utils import unquote
        from django.http import HttpResponseRedirect
        from django.urls import reverse

        obj = self.get_object(request, unquote(object_id))
        if request.method == "POST" and obj is not None:
            try:
                reference, account = services.delete_transaction(
                    obj,
                    performed_by=request.user,
                )
            except ValidationError as exc:
                msg = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
                self.message_user(request, msg, messages.ERROR)
                return HttpResponseRedirect(
                    reverse("admin:savings_savingstransaction_change", args=[object_id])
                )
            self.message_user(
                request,
                f"Deleted {reference}. {account.account_number} balance is now ₱{account.balance}.",
                messages.SUCCESS,
            )
            return HttpResponseRedirect(
                reverse("admin:savings_savingstransaction_changelist")
            )
        return super().delete_view(request, object_id, extra_context=extra_context)

    def save_model(self, request, obj, form, change):
        if change:
            return
        try:
            created = services.post_admin_transaction(
                account=form.cleaned_data["account"],
                txn_type=form.cleaned_data["transaction_type"],
                amount=form.cleaned_data["amount"],
                performed_by=request.user,
                notes=form.cleaned_data.get("notes") or "",
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            raise
        obj.pk = created.pk
        obj.reference = created.reference
        obj.balance_before = created.balance_before
        obj.balance_after = created.balance_after
        obj.performed_by = created.performed_by
        messages.success(request, f"Saved {created.reference} to the savings ledger.")
