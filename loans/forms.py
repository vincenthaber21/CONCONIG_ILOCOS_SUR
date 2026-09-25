from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator

from helper.money_forms import MoneyField, money_input

from . import models

TWO_PLACES = Decimal("0.01")


class LoanSettingsForm(forms.ModelForm):
    class Meta:
        model = models.LoanSettings
        fields = [
            "grace_period_days",
            "min_membership_enabled",
            "min_membership_months",
            "committee_single_approver",
            "usable_days_editable",
        ]
        widgets = {
            "grace_period_days": forms.NumberInput(attrs={"min": 0, "step": 1}),
            "min_membership_enabled": forms.CheckboxInput(),
            "min_membership_months": forms.NumberInput(attrs={"min": 0, "step": 1}),
            "committee_single_approver": forms.CheckboxInput(),
            "usable_days_editable": forms.CheckboxInput(),
        }
        labels = {
            "grace_period_days": "Late-payment grace period (days)",
            "min_membership_enabled": "Require minimum membership before loan",
            "min_membership_months": "Minimum membership (months)",
            "committee_single_approver": "Allow one-person committee approval",
            "usable_days_editable": "Allow editing usable days on payment",
        }
        help_texts = {
            "grace_period_days": (
                "How many days after the due date a member may still pay without "
                "late-payment interest. 0 means late interest starts the day after "
                "the due date."
            ),
            "min_membership_enabled": (
                "When checked, members must wait the months below before requesting a loan. "
                "Uncheck to allow any member to apply immediately."
            ),
            "min_membership_months": (
                "Minimum months a member must be registered before they can request a loan "
                "(used only when the rule above is enabled). "
                "Set to 0 to allow loan requests immediately."
            ),
            "committee_single_approver": (
                "When checked, any one authorized approver can approve or reject a loan. "
                "When unchecked, a majority of listed approvers is required."
            ),
            "usable_days_editable": (
                "When checked, staff can type Days on the Interest period section "
                "(To date follows From + Days). When unchecked, Days stays locked and "
                "is calculated as To − From."
            ),
        }


class LoanProductForm(forms.ModelForm):
    min_amount = MoneyField(min_value=0, max_digits=12, decimal_places=2, label="Minimum amount")
    max_amount = MoneyField(min_value=0, max_digits=12, decimal_places=2, label="Maximum amount")
    uses_usable_days = forms.CharField(
        required=False,
        initial="0",
        label="Use usable days",
        widget=forms.HiddenInput(attrs={"id": "product-use-usable-days"}),
    )
    class Meta:
        model = models.LoanProduct
        fields = [
            "name",
            "description",
            "term_months",
            "interest_rate",
            "min_amount",
            "max_amount",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "term_months": forms.NumberInput(attrs={"min": 1, "step": 1}),
            "interest_rate": forms.NumberInput(
                attrs={
                    "step": "any",
                    "min": "0",
                    "inputmode": "decimal",
                    "placeholder": "0.180",
                    "id": "id_interest_rate",
                }
            ),
        }
        labels = {
            "term_months": "Term (months)",
            "interest_rate": "Interest rate",
        }
        help_texts = {
            "term_months": (
                "How many monthly installments this product uses. "
                "Term only sets the number of months — it does not change interest calculation."
            ),
            "interest_rate": (
                "Type the rate used in the formula, such as 0.180. "
                "0.180 means 18%. New applications start with this rate."
            ),
        }

    @staticmethod
    def _truthy_flag(raw):
        return str(raw or "").strip().lower() in {"1", "true", "on", "yes"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields["uses_usable_days"].initial = (
                "1" if self.instance.uses_usable_days else "0"
            )
        elif not self.is_bound:
            self.fields["uses_usable_days"].initial = "0"
        self.fields["interest_rate"].required = True

    def clean_interest_rate(self):
        rate = self.cleaned_data.get("interest_rate")
        if rate is None:
            raise forms.ValidationError("Enter the interest rate for this product.")
        rate = Decimal(rate)
        if rate < 0:
            raise forms.ValidationError("Interest rate cannot be negative.")
        return rate.quantize(Decimal("0.001"))

    def clean_uses_usable_days(self):
        raw = self.cleaned_data.get("uses_usable_days", "0")
        return self._truthy_flag(raw)

    def clean(self):
        cleaned_data = super().clean()
        min_amount = cleaned_data.get("min_amount")
        max_amount = cleaned_data.get("max_amount")
        if min_amount is not None and max_amount is not None and min_amount > max_amount:
            raise forms.ValidationError("Minimum amount cannot be greater than maximum amount.")
        term_months = cleaned_data.get("term_months")
        if term_months is not None and term_months < 1:
            self.add_error("term_months", "Term must be at least 1 month.")
        return cleaned_data

    def save(self, commit=True):
        product = super().save(commit=False)
        rate = self.cleaned_data.get("interest_rate")
        product.interest_rate = Decimal("0") if rate is None else Decimal(rate)
        product.uses_usable_days = bool(self.cleaned_data.get("uses_usable_days"))
        # Collateral / insurance are not shown in the product UI; apply defaults.
        if not product.pk:
            product.requires_collateral = False
            product.requires_insurance = False
        if commit:
            product.save()
        return product


class LoanInquiryForm(forms.ModelForm):
    class Meta:
        model = models.LoanInquiry
        fields = ["loan_product", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class LoanApplicationForm(forms.ModelForm):
    purpose = forms.CharField(
        required=True,
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "required": "required",
                "placeholder": "Describe how you will use the loan (e.g. medical expenses, business capital).",
            }
        ),
        label="Loan purpose",
        help_text="Required. Briefly explain why you are requesting this loan.",
    )
    amount_requested = MoneyField(
        max_digits=12,
        decimal_places=2,
        label="Amount requested",
        widget=money_input(
            placeholder="Select a loan product first",
            inputmode="decimal",
        ),
    )
    use_usable_days = forms.CharField(
        required=False,
        initial="0",
        label="Use usable days",
        widget=forms.HiddenInput(attrs={"id": "loan-use-usable-days"}),
    )

    class Meta:
        model = models.LoanApplication
        fields = [
            "loan_product",
            "amount_requested",
            "term_months",
            "interest_rate",
            "usable_from",
            "usable_to",
            "usable_days",
            "purpose",
        ]
        widgets = {
            "term_months": forms.HiddenInput(attrs={"id": "id_term_months"}),
            "interest_rate": forms.NumberInput(
                attrs={
                    "step": "any",
                    "min": "0",
                    "inputmode": "decimal",
                    "placeholder": "Select a loan product first",
                    "id": "id_interest_rate",
                    "readonly": "readonly",
                    "tabindex": "-1",
                }
            ),
            "usable_from": forms.HiddenInput(
                attrs={"id": "loan-usable-from"}
            ),
            "usable_to": forms.HiddenInput(
                attrs={"id": "loan-usable-to"}
            ),
            "usable_days": forms.HiddenInput(
                attrs={"id": "loan-usable-days"}
            ),
        }
        labels = {
            "term_months": "Term (months)",
            "interest_rate": "Interest rate",
            "usable_from": "Application date",
            "usable_to": "To",
            "usable_days": "Usable days",
        }
        help_texts = {
            "term_months": (
                "Taken automatically from the selected loan product."
            ),
            "interest_rate": (
                "Filled automatically from the selected loan product. "
                "Change it on the product page if this rate should be different."
            ),
        }

    @staticmethod
    def _truthy_flag(raw):
        return str(raw or "").strip().lower() in {"1", "true", "on", "yes"}

    def _resolve_use_usable_days(self):
        if self.is_bound:
            raw = self.data.get("use_usable_days", "0")
        else:
            raw = self.fields["use_usable_days"].initial or "0"
        return self._truthy_flag(raw)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["loan_product"].required = True
        self.fields["loan_product"].empty_label = "— Select a loan product —"
        self.fields["amount_requested"].required = True
        self.fields["amount_requested"].help_text = (
            "Choose a loan product first. You can only request an amount within that product's allowed range."
        )
        self.fields["term_months"].required = False
        self.fields["interest_rate"].required = True
        # Usable days follows the product setting (configured on Products page).
        if not self.is_bound:
            self.fields["use_usable_days"].initial = "0"
        self.use_usable_days = self._resolve_use_usable_days()
        # From/To dates are collected on payment, not on apply.
        self.fields["usable_from"].required = False
        self.fields["usable_from"].label = "From"
        self.fields["usable_to"].required = False
        self.fields["usable_days"].required = False
        amount_widget = self.fields["amount_requested"].widget
        amount_widget.attrs.setdefault("readonly", "readonly")
        amount_widget.attrs.setdefault("id", "id_amount_requested")
        # Interest rate is locked to the selected loan product.
        self.fields["interest_rate"].widget.attrs["readonly"] = "readonly"

        product = self._resolve_selected_product()
        if product is not None:
            self._apply_product_amount_limits(product)
            self._apply_product_interest_default(product)
            self._apply_product_term_default(product)
            self._apply_product_usable_days(product)

    def _resolve_selected_product(self):
        product = None
        if self.is_bound:
            raw = self.data.get(self.add_prefix("loan_product"))
            if raw:
                product = models.LoanProduct.objects.filter(pk=raw).first()
        else:
            raw = self.initial.get("loan_product")
            if raw:
                if isinstance(raw, models.LoanProduct):
                    product = raw
                else:
                    product = models.LoanProduct.objects.filter(pk=raw).first()
        if product is None and self.instance.pk and self.instance.loan_product_id:
            product = self.instance.loan_product
        return product

    def _apply_product_amount_limits(self, product):
        amount_field = self.fields["amount_requested"]
        min_amount = product.min_amount
        max_amount = product.max_amount
        amount_field.widget.attrs["min"] = str(min_amount)
        amount_field.widget.attrs["max"] = str(max_amount)
        amount_field.widget.attrs["placeholder"] = (
            f"Enter amount from ₱{min_amount:,.2f} to ₱{max_amount:,.2f}"
        )
        amount_field.help_text = (
            f"Available for {product.name}: ₱{min_amount:,.2f} – ₱{max_amount:,.2f}."
        )
        amount_field.widget.attrs.pop("readonly", None)

    def _apply_product_interest_default(self, product):
        rate_field = self.fields["interest_rate"]
        rate = product.interest_rate if product.interest_rate is not None else Decimal("0")
        rate_field.widget.attrs["readonly"] = "readonly"
        rate_field.widget.attrs["placeholder"] = f"{rate}"
        rate_field.initial = rate
        if self.is_bound:
            mutable = self.data.copy()
            mutable[self.add_prefix("interest_rate")] = str(rate)
            self.data = mutable

    def _apply_product_term_default(self, product):
        # Term is not shown on apply — always locked to the product setting.
        term_field = self.fields["term_months"]
        term_field.initial = product.term_months
        if self.is_bound:
            mutable = self.data.copy()
            mutable[self.add_prefix("term_months")] = str(product.term_months)
            self.data = mutable
        else:
            term_field.initial = product.term_months

    def _apply_product_usable_days(self, product):
        """Usable days on/off comes from the product catalog — not shown on Apply."""
        enabled = bool(getattr(product, "uses_usable_days", False))
        flag = "1" if enabled else "0"
        self.fields["use_usable_days"].initial = flag
        self.use_usable_days = enabled
        self.fields["usable_from"].required = False
        if self.is_bound:
            mutable = self.data.copy()
            mutable[self.add_prefix("use_usable_days")] = flag
            self.data = mutable

    def clean_purpose(self):
        purpose = (self.cleaned_data.get("purpose") or "").strip()
        if not purpose:
            raise forms.ValidationError("Loan purpose is required.")
        return purpose

    def clean_term_months(self):
        # Prefer product term; fall back to submitted/hidden value.
        product = self._resolve_selected_product()
        if product is not None:
            return max(1, int(product.term_months or 1))
        term = self.cleaned_data.get("term_months")
        if term is None:
            raise forms.ValidationError("Select a loan product to set the term.")
        if term < 1:
            raise forms.ValidationError("Term must be at least 1 month.")
        return term

    def clean_interest_rate(self):
        from decimal import Decimal, InvalidOperation

        rate = self.cleaned_data.get("interest_rate")
        if rate is None:
            raise forms.ValidationError("Please enter the interest rate for this loan.")
        try:
            rate = Decimal(rate)
        except (InvalidOperation, TypeError, ValueError):
            raise forms.ValidationError("Enter a valid interest rate.")
        if rate < 0:
            raise forms.ValidationError("Interest rate cannot be negative.")
        return rate.quantize(Decimal("0.001"))

    def clean_use_usable_days(self):
        raw = self.cleaned_data.get("use_usable_days", "0")
        return "1" if self._truthy_flag(raw) else "0"

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get("loan_product")
        amount = cleaned_data.get("amount_requested")

        if not product:
            self.add_error("loan_product", "Please select a loan product.")
            return cleaned_data

        # Always use the product term and interest from Loan Products settings.
        cleaned_data["term_months"] = max(1, int(product.term_months or 1))
        cleaned_data["interest_rate"] = Decimal(product.interest_rate or 0).quantize(
            Decimal("0.001")
        )

        # Usable days follows the product catalog; From/To are entered on payment only.
        use_usable_days = bool(getattr(product, "uses_usable_days", False))
        cleaned_data["use_usable_days"] = use_usable_days
        self.use_usable_days = use_usable_days
        cleaned_data["usable_from"] = None
        cleaned_data["usable_to"] = None
        cleaned_data["usable_days"] = None

        if amount is None:
            self.add_error("amount_requested", "Please enter the amount you want to request.")
            return cleaned_data
        if amount < product.min_amount or amount > product.max_amount:
            self.add_error(
                "amount_requested",
                (
                    f"Amount must be between ₱{product.min_amount:,.2f} and "
                    f"₱{product.max_amount:,.2f} for {product.name}."
                ),
            )

        return cleaned_data

    def save(self, commit=True):
        application = super().save(commit=False)
        if application.loan_product_id:
            # Term and interest always come from the product.
            application.term_months = max(
                1, int(application.loan_product.term_months or 1)
            )
            application.interest_rate = application.loan_product.interest_rate
        if (
            application.usable_from
            and application.usable_to
            and application.usable_days is None
        ):
            application.usable_days = (
                application.usable_to - application.usable_from
            ).days
        if commit:
            application.save()
        return application


class StaffLoanApplicationForm(LoanApplicationForm):
    """Staff walk-in application: same fields as the member form, plus borrower."""

    coop_member = forms.ModelChoiceField(
        queryset=None,
        required=True,
        # Empty label text must stay blank so Tom Select can show its placeholder
        # (otherwise the control and dropdown both show "— Select a member —").
        empty_label="",
        label="Member",
        help_text="Select the member this new application is for.",
        widget=forms.Select(attrs={"id": "id_coop_member"}),
    )

    def __init__(self, *args, **kwargs):
        from members.models import Member

        super().__init__(*args, **kwargs)
        self.fields["coop_member"].queryset = (
            Member.objects.filter(is_active=True, member_role__slug="member")
            .select_related("user", "member_role")
            .order_by("last_name", "first_name")
        )
        self.fields["coop_member"].label_from_instance = (
            lambda obj: f"{obj.full_name} ({obj.username})"
            if obj.username
            else obj.full_name
        )
        self.fields["loan_product"].widget.attrs.setdefault("id", "id_loan_product")
        # Staff can type the amount after choosing a product. Interest stays locked.
        self.fields["amount_requested"].widget.attrs.pop("readonly", None)
        self.fields["interest_rate"].widget.attrs["readonly"] = "readonly"
        self.order_fields(
            [
                "coop_member",
                "loan_product",
                "amount_requested",
                "interest_rate",
                "usable_from",
                "usable_to",
                "usable_days",
                "purpose",
            ]
        )

    def clean(self):
        cleaned_data = super().clean()
        coop_member = cleaned_data.get("coop_member")
        product = cleaned_data.get("loan_product")
        if coop_member is None or product is None:
            return cleaned_data

        from .member_views import _get_open_application_for_product, ensure_member_user

        loan_user = ensure_member_user(coop_member)
        if loan_user is None:
            self.add_error("coop_member", "Could not resolve a user account for this member.")
            return cleaned_data

        existing = _get_open_application_for_product(loan_user, product.pk)
        if existing is not None:
            self.add_error(
                "loan_product",
                (
                    f"This member already has an ongoing {product.name} loan "
                    f"({existing.get_status_display()}). Choose a different loan product."
                ),
            )
        return cleaned_data


class SubmittedDocumentForm(forms.ModelForm):
    class Meta:
        model = models.SubmittedDocument
        fields = ["document_type", "file"]


class EligibilityVerificationForm(forms.ModelForm):
    class Meta:
        model = models.EligibilityVerification
        fields = ["membership_status_ok", "documents_complete", "remarks"]
        widgets = {
            "remarks": forms.Textarea(attrs={"rows": 3}),
        }


class CreditInvestigationForm(forms.ModelForm):
    class Meta:
        model = models.CreditInvestigation
        fields = [
            "repayment_capacity_score",
            "loan_purpose_assessment",
            "recommendation",
            "remarks",
        ]
        widgets = {
            "repayment_capacity_score": forms.NumberInput(
                attrs={"readonly": "readonly", "step": "0.1"}
            ),
            "loan_purpose_assessment": forms.Textarea(attrs={"rows": 3}),
            "remarks": forms.Textarea(attrs={"rows": 3}),
            "recommendation": forms.RadioSelect(),
        }
        labels = {
            "repayment_capacity_score": "Payment score (auto)",
        }
        help_texts = {
            "repayment_capacity_score": (
                "Starts at 100. −0.1 for each unpaid overdue installment on prior loans."
            ),
        }

    def __init__(self, *args, auto_score=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["recommendation"].required = True
        self.fields["recommendation"].choices = (
            models.CreditInvestigation.Recommendation.choices
        )
        if auto_score is not None:
            self.initial["repayment_capacity_score"] = auto_score
            self.fields["repayment_capacity_score"].initial = auto_score


class CommitteeReviewForm(forms.ModelForm):
    class Meta:
        model = models.CommitteeReview
        fields = ["reviewed_by", "decision", "remarks"]
        widgets = {
            "remarks": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Approver is auto-added from the logged-in user in the view.
        self.fields["reviewed_by"].required = False
        self.fields["decision"].required = False



class InsuranceEnrollmentForm(forms.ModelForm):
    premium_amount = MoneyField(
        min_value=0,
        max_digits=12,
        decimal_places=2,
        label="Premium amount",
        widget=money_input(min="0", placeholder="0.00"),
    )

    class Meta:
        model = models.InsuranceEnrollment
        fields = ["insurance_type", "premium_amount", "payment_mode"]
        widgets = {
            "insurance_type": forms.Select(attrs={"class": "loan-insurance-input"}),
            "payment_mode": forms.RadioSelect(),
        }
        help_texts = {
            "premium_amount": "Enter the insurance premium amount for this loan.",
            "payment_mode": "Choose whether the premium is collected now or added to the loan balance.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["insurance_type"].label = "Insurance type"
        self.fields["premium_amount"].label = "Premium amount"
        self.fields["payment_mode"].label = "Payment mode"
class LoanDocumentationForm(forms.ModelForm):
    HARD_COPY_MAX_BYTES = 12 * 1024 * 1024
    HARD_COPY_EXTENSIONS = ("pdf", "jpg", "jpeg", "png", "webp", "tif", "tiff")

    signing_method = forms.ChoiceField(
        choices=models.LoanDocumentation.SigningMethod.choices,
        widget=forms.RadioSelect,
        initial=models.LoanDocumentation.SigningMethod.DIGITAL,
        label="How was this contract signed?",
    )
    signed_hard_copy = forms.FileField(
        required=False,
        label="Upload signed hard copy",
        help_text="Scan or photo of the signed paper contract (PDF, JPG, PNG, WEBP, TIFF — max 12 MB).",
        validators=[FileExtensionValidator(allowed_extensions=list(HARD_COPY_EXTENSIONS))],
        widget=forms.FileInput(
            attrs={
                "accept": ".pdf,.jpg,.jpeg,.png,.webp,.tif,.tiff,application/pdf,image/*",
            }
        ),
    )
    borrower_signature_data = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"id": "id_borrower_signature_data"}),
    )
    personnel_signature_data = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"id": "id_personnel_signature_data"}),
    )
    spouse_signature_data = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"id": "id_spouse_signature_data"}),
    )
    prepared_by_signature_data = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"id": "id_prepared_by_signature_data"}),
    )
    comaker1_signature_data = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"id": "id_comaker1_signature_data"}),
    )
    comaker2_signature_data = forms.CharField(
        required=False,
        widget=forms.HiddenInput(attrs={"id": "id_comaker2_signature_data"}),
    )
    clear_borrower_signature = forms.BooleanField(required=False, widget=forms.HiddenInput)
    clear_personnel_signature = forms.BooleanField(required=False, widget=forms.HiddenInput)
    clear_spouse_signature = forms.BooleanField(required=False, widget=forms.HiddenInput)
    clear_prepared_by_signature = forms.BooleanField(required=False, widget=forms.HiddenInput)
    clear_comaker1_signature = forms.BooleanField(required=False, widget=forms.HiddenInput)
    clear_comaker2_signature = forms.BooleanField(required=False, widget=forms.HiddenInput)
    regenerate_contract = forms.BooleanField(
        required=False,
        initial=False,
        label="Regenerate system contract PDF from current loan details",
    )

    class Meta:
        model = models.LoanDocumentation
        fields = [
            "signing_method",
            "signed_hard_copy",
            "spouse_signer_name",
            "prepared_by_name",
            "comaker1_name",
            "comaker2_name",
        ]
        widgets = {
            "spouse_signer_name": forms.TextInput(
                attrs={
                    "id": "id_spouse_signer_name",
                    "placeholder": "Name",
                    "autocomplete": "name",
                }
            ),
            "prepared_by_name": forms.TextInput(
                attrs={
                    "id": "id_prepared_by_name",
                    "placeholder": "Name",
                    "autocomplete": "name",
                }
            ),
            "comaker1_name": forms.TextInput(
                attrs={
                    "id": "id_comaker1_name",
                    "placeholder": "Co-Maker 1 name",
                    "autocomplete": "name",
                }
            ),
            "comaker2_name": forms.TextInput(
                attrs={
                    "id": "id_comaker2_name",
                    "placeholder": "Co-Maker 2 name",
                    "autocomplete": "name",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        default_prepared_by = kwargs.pop("default_prepared_by_name", "")
        default_spouse = kwargs.pop("default_spouse_name", "")
        super().__init__(*args, **kwargs)
        instance = getattr(self, "instance", None)
        if instance and instance.signing_method:
            self.fields["signing_method"].initial = instance.signing_method
        self.fields["spouse_signer_name"].required = False
        self.fields["spouse_signer_name"].label = "Name"
        self.fields["prepared_by_name"].required = False
        self.fields["prepared_by_name"].label = "Name"
        self.fields["comaker1_name"].required = False
        self.fields["comaker1_name"].label = "Co-Maker 1 name"
        self.fields["comaker2_name"].required = False
        self.fields["comaker2_name"].label = "Co-Maker 2 name"
        if not (instance and instance.pk and instance.spouse_signer_name):
            if default_spouse and default_spouse != "—":
                self.fields["spouse_signer_name"].initial = default_spouse
        if not (instance and instance.pk and instance.prepared_by_name):
            if default_prepared_by:
                self.fields["prepared_by_name"].initial = default_prepared_by

    def clean_signed_hard_copy(self):
        uploaded = self.cleaned_data.get("signed_hard_copy")
        if not uploaded:
            return uploaded
        if getattr(uploaded, "size", 0) > self.HARD_COPY_MAX_BYTES:
            raise ValidationError("Hard-copy file is too large. Maximum size is 12 MB.")
        return uploaded

    def clean(self):
        cleaned = super().clean()
        instance = getattr(self, "instance", None)
        method = cleaned.get("signing_method") or models.LoanDocumentation.SigningMethod.DIGITAL

        if method == models.LoanDocumentation.SigningMethod.HARD_COPY:
            has_upload = bool(cleaned.get("signed_hard_copy"))
            has_existing = bool(instance and instance.signed_hard_copy)
            if not has_upload and not has_existing:
                self.add_error(
                    "signed_hard_copy",
                    "Upload a scan or photo of the signed paper contract.",
                )
            return cleaned

        has_borrower = bool(
            cleaned.get("borrower_signature_data")
            or (
                instance
                and instance.borrower_signature
                and not cleaned.get("clear_borrower_signature")
            )
        )
        has_personnel = bool(
            cleaned.get("personnel_signature_data")
            or (
                instance
                and instance.personnel_signature
                and not cleaned.get("clear_personnel_signature")
            )
        )
        if not has_borrower:
            raise forms.ValidationError(
                "The borrower must draw a signature before you can mark documentation complete."
            )
        if not has_personnel:
            raise forms.ValidationError(
                "Authorized personnel must also draw a signature."
            )
        return cleaned


class MemberSavingsAccountField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        product = getattr(obj, "product", None)
        product_name = product.name if product else "Savings"
        balance = Decimal(obj.balance or 0)
        return f"{obj.account_number} — {product_name} (balance ₱{balance:,.2f})"


class DisbursementForm(forms.ModelForm):
    amount_released = MoneyField(
        min_value=0,
        max_digits=12,
        decimal_places=2,
        label="Net amount released (₱)",
        widget=money_input(min="0", placeholder="0.00"),
    )
    months_pay = forms.IntegerField(
        min_value=1,
        label="Months to pay",
        help_text="Interest = principal × product rate × (months to pay ÷ 12).",
        widget=forms.NumberInput(attrs={"min": 1, "step": 1}),
    )
    savings_amount = MoneyField(
        min_value=0,
        max_digits=12,
        decimal_places=2,
        required=False,
        label="Savings (₱)",
        help_text="Withheld from the loan and deposited to the member's savings account.",
        widget=money_input(min="0", placeholder="0.00"),
    )
    interest_amount = MoneyField(
        min_value=0,
        max_digits=12,
        decimal_places=2,
        required=False,
        label="Interest (₱)",
        widget=money_input(min="0", placeholder="0.00"),
    )
    share_capital_amount = MoneyField(
        min_value=0,
        max_digits=12,
        decimal_places=2,
        required=False,
        label="Share capital (₱)",
        widget=money_input(min="0", placeholder="0.00"),
    )
    transaction_fee = MoneyField(
        min_value=0,
        max_digits=12,
        decimal_places=2,
        required=False,
        label="Service fee (₱)",
        widget=money_input(min="0", placeholder="0.00"),
    )
    insurance_amount = MoneyField(
        min_value=0,
        max_digits=12,
        decimal_places=2,
        required=False,
        label="Insurance (₱)",
        widget=money_input(min="0", placeholder="0.00"),
    )

    class Meta:
        model = models.Disbursement
        fields = [
            "months_pay",
            "interest_amount",
            "share_capital_amount",
            "transaction_fee",
            "insurance_amount",
            "savings_amount",
            "savings_account",
            "amount_released",
            "disbursement_method",
            "reference_number",
        ]
        labels = {
            "amount_released": "Net amount released (₱)",
            "months_pay": "Months to pay",
            "interest_amount": "Interest (₱)",
            "share_capital_amount": "Share capital (₱)",
            "transaction_fee": "Service fee (₱)",
            "insurance_amount": "Insurance (₱)",
            "savings_amount": "Savings (₱)",
            "savings_account": "Credit to member savings",
            "disbursement_method": "Disbursement method",
            "reference_number": "Reference number",
        }
        help_texts = {
            "amount_released": (
                "Cash/check/transfer given to the member after fees. "
                "Principal for repayment stays the full loan amount."
            ),
            "reference_number": "Optional check / transfer reference.",
        }
        widgets = {
            "disbursement_method": forms.RadioSelect(),
            "reference_number": forms.TextInput(
                attrs={"placeholder": "Check no., transfer ref., etc."}
            ),
        }

    def __init__(self, *args, amount_requested=None, interest_rate=None, term_months=None, uses_usable_days=False, savings_accounts=None, **kwargs):
        from . import services

        super().__init__(*args, **kwargs)
        self.amount_requested = amount_requested
        self.interest_rate = (
            Decimal(interest_rate)
            if interest_rate is not None
            else Decimal("0")
        )
        self.term_months = int(term_months or 12)
        self.uses_usable_days = bool(uses_usable_days)

        self.fields["disbursement_method"].required = True
        self.fields["disbursement_method"].choices = models.Disbursement.Method.choices
        self.fields["reference_number"].required = False
        from savings.models import MemberSavingsAccount

        self.fields["savings_amount"].initial = Decimal("0.00")
        account_qs = (
            savings_accounts
            if savings_accounts is not None
            else MemberSavingsAccount.objects.none()
        )
        current_account_id = getattr(self.instance, "savings_account_id", None)
        if current_account_id:
            account_qs = (
                account_qs | MemberSavingsAccount.objects.filter(pk=current_account_id)
            ).distinct().select_related("product")
        self.fields["savings_account"] = MemberSavingsAccountField(
            queryset=account_qs,
            required=False,
            label="Credit to member savings",
            empty_label="Select the member's savings account",
            help_text="The savings amount is deposited into this account when the loan is released.",
        )
        if current_account_id:
            self.initial.setdefault("savings_account", current_account_id)
        elif not self.is_bound:
            only = list(account_qs[:2])
            if len(only) == 1:
                self.initial["savings_account"] = only[0].pk

        # Computed fee fields are display-only; server recalculates on save.
        for name in (
            "interest_amount",
            "share_capital_amount",
            "transaction_fee",
            "insurance_amount",
            "amount_released",
        ):
            self.fields[name].widget.attrs["readonly"] = "readonly"
            self.fields[name].required = False

        if self.uses_usable_days:
            # Usable-days products: no coop withholdings; interest at payment.
            self.fields["months_pay"].required = False
            self.fields["months_pay"].widget = forms.HiddenInput()
            self.fields["savings_amount"].widget = forms.HiddenInput()
            self.fields["savings_account"].widget = forms.HiddenInput()
            self.fields["interest_amount"].widget = forms.HiddenInput()
            self.fields["share_capital_amount"].widget = forms.HiddenInput()
            self.fields["transaction_fee"].widget = forms.HiddenInput()
            self.fields["insurance_amount"].widget = forms.HiddenInput()
            self.fields["amount_released"].help_text = (
                "Full principal released. Interest is charged at payment using "
                "principal × rate × (usable days ÷ 360)."
            )

        if amount_requested is not None:
            principal = Decimal(amount_requested)
            months_pay = services.DEFAULT_DISBURSEMENT_MONTHS_PAY
            if self.instance and self.instance.pk and self.instance.months_pay:
                months_pay = int(self.instance.months_pay)
            self.fields["months_pay"].initial = months_pay

            savings = Decimal("0.00")
            if self.instance and self.instance.pk and not self.uses_usable_days:
                savings = Decimal(self.instance.savings_amount or 0)

            calc = services.compute_disbursement_deductions(
                principal,
                self.interest_rate,
                months_pay,
                savings=savings,
                uses_usable_days=self.uses_usable_days,
            )
            if not (self.instance and self.instance.pk):
                self.initial.setdefault("amount_released", calc["amount_released"])
                self.initial.setdefault("interest_amount", calc["interest_amount"])
                self.initial.setdefault(
                    "share_capital_amount", calc["share_capital_amount"]
                )
                self.initial.setdefault("transaction_fee", calc["service_fee_amount"])
                self.initial.setdefault("insurance_amount", calc["insurance_amount"])
                self.initial.setdefault("savings_amount", calc["savings_amount"])
                self.fields["amount_released"].initial = calc["amount_released"]
                self.fields["interest_amount"].initial = calc["interest_amount"]
                self.fields["share_capital_amount"].initial = calc[
                    "share_capital_amount"
                ]
                self.fields["transaction_fee"].initial = calc["service_fee_amount"]
                self.fields["insurance_amount"].initial = calc["insurance_amount"]

            self.fields["amount_released"].widget.attrs["data-principal"] = str(principal)
            if not self.uses_usable_days:
                self.fields["amount_released"].help_text = (
                    "Net cash to the member. Loan principal for repayment remains "
                    f"₱{principal:,.2f}."
                )
            self.deduction_preview = calc
        else:
            self.deduction_preview = None

        if not self.initial.get("disbursement_method") and not (
            self.instance and self.instance.pk and self.instance.disbursement_method
        ):
            self.fields["disbursement_method"].initial = models.Disbursement.Method.CASH

    def clean_savings_amount(self):
        amount = self.cleaned_data.get("savings_amount")
        return Decimal(amount or 0).quantize(TWO_PLACES)

    def clean_months_pay(self):
        months = self.cleaned_data.get("months_pay")
        if self.uses_usable_days:
            return int(months or self.term_months or 1)
        if months is None or months < 1:
            raise forms.ValidationError("Months to pay must be at least 1.")
        return int(months)

    def clean(self):
        from . import services

        cleaned = super().clean()
        if self.amount_requested is None:
            return cleaned

        principal = Decimal(self.amount_requested).quantize(TWO_PLACES)
        months_pay = cleaned.get("months_pay") or self.term_months
        savings = (
            Decimal("0.00")
            if self.uses_usable_days
            else (cleaned.get("savings_amount") or Decimal("0.00"))
        )

        calc = services.compute_disbursement_deductions(
            principal,
            self.interest_rate,
            months_pay,
            savings=savings,
            uses_usable_days=self.uses_usable_days,
        )

        # Always apply formula amounts (ignore tampered posted fee fields).
        cleaned["interest_amount"] = calc["interest_amount"]
        cleaned["share_capital_amount"] = calc["share_capital_amount"]
        cleaned["transaction_fee"] = calc["service_fee_amount"]
        cleaned["insurance_amount"] = calc["insurance_amount"]
        cleaned["savings_amount"] = calc["savings_amount"]
        if self.uses_usable_days or calc["savings_amount"] <= 0:
            cleaned["savings_account"] = None
        elif (
            cleaned.get("savings_account") is None
            and "savings_account" not in self.errors
        ):
            self.add_error(
                "savings_account",
                "Select the member's savings account. "
                "The savings amount is deposited there when the loan is released.",
            )
        cleaned["amount_released"] = calc["amount_released"]
        cleaned["other_deduction_amount"] = Decimal("0.00")
        cleaned["other_deduction_label"] = ""

        if calc["amount_released"] <= 0:
            raise ValidationError(
                "Deductions equal or exceed the loan principal. "
                "Reduce savings or months to pay so a net amount can be released."
            )
        self.deduction_preview = calc
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.other_deduction_amount = Decimal("0.00")
        instance.other_deduction_label = ""
        if commit:
            instance.save()
        return instance


class PaymentForm(forms.ModelForm):
    amount_paid = MoneyField(
        min_value=0,
        max_digits=12,
        decimal_places=2,
        label="Amount paid",
        widget=money_input(min="0.01", placeholder="0.00"),
    )
    use_usable_days = forms.CharField(
        required=False,
        initial="0",
        label="Use usable days",
        widget=forms.HiddenInput(attrs={"id": "pay-use-usable-days"}),
    )
    renewal_months_pay = forms.IntegerField(
        min_value=1,
        required=False,
        label="Months to pay",
        help_text="Interest = remaining principal × product rate × (months to pay ÷ 12).",
        widget=forms.NumberInput(
            attrs={"id": "pay-renewal-months", "min": 1, "step": 1}
        ),
    )
    renewal_savings = MoneyField(
        min_value=0,
        max_digits=12,
        decimal_places=2,
        required=False,
        label="Savings (₱)",
        help_text="Optional savings charged on the remaining principal.",
        widget=money_input(min="0", placeholder="0.00", id="pay-renewal-savings"),
    )

    class Meta:
        model = models.Payment
        fields = [
            "amount_paid",
            "payment_method",
            "or_number",
            "remarks",
            "usable_from",
            "usable_to",
            "usable_days",
        ]
        widgets = {
            "remarks": forms.Textarea(attrs={"rows": 2}),
            "usable_from": forms.DateInput(
                attrs={
                    "type": "date",
                    "id": "pay-usable-from",
                    "readonly": "readonly",
                    "tabindex": "-1",
                    "title": "Set automatically from the previous payment period (cannot be edited).",
                }
            ),
            "usable_to": forms.DateInput(
                attrs={"type": "date", "id": "pay-usable-to"}
            ),
            "usable_days": forms.HiddenInput(
                attrs={"id": "pay-usable-days"}
            ),
        }
        labels = {
            "amount_paid": "Amount paid",
            "or_number": "Official receipt (OR) number",
            "usable_from": "From",
            "usable_to": "To",
            "usable_days": "Usable days",
        }
        help_texts = {
            "or_number": "Leave blank to auto-generate a secure OR number for this payment.",
        }

    def __init__(self, *args, application=None, **kwargs):
        from decimal import Decimal

        from loans.services import _add_calendar_months

        super().__init__(*args, **kwargs)
        self.application = application
        self._usable_from_tampered = False
        self.usable_days_editable = bool(
            getattr(models.LoanSettings.get(), "usable_days_editable", False)
        )
        # Usable-days products start ON; normal loan products start OFF.
        if not self.is_bound:
            product_uses = bool(
                application
                and getattr(application, "loan_product", None)
                and getattr(application.loan_product, "uses_usable_days", False)
            )
            self.fields["use_usable_days"].initial = "1" if product_uses else "0"
        self.use_usable_days = self._resolve_use_usable_days()
        self.fields["or_number"].required = False
        self.fields["remarks"].required = False
        self.fields["usable_from"].required = False
        self.fields["usable_to"].required = False
        self.fields["usable_days"].required = False
        self.fields["renewal_months_pay"].required = False
        self.fields["renewal_savings"].required = False
        self.fields["renewal_savings"].initial = Decimal("0.00")

        remaining = Decimal("0.00")
        remaining_principal = Decimal("0.00")
        if application is not None:
            remaining = Decimal(application.total_outstanding_balance() or 0)
            remaining_principal = Decimal(
                application.remaining_principal_balance() or 0
            )
        self.remaining_balance = remaining
        self.remaining_principal = remaining_principal
        # Interest uses balance left to pay; stop only when nothing is owed.
        self.principal_fully_paid = remaining <= 0
        from loans.services import (
            compute_expired_loan_renewal_charges,
            is_loan_term_expired,
            product_interest_rate,
        )

        self.interest_rate = (
            Decimal(product_interest_rate(application) or 0)
            if application is not None
            else Decimal("0")
        )

        self.loan_expired = bool(
            application is not None and is_loan_term_expired(application)
        )
        self.renewal_calc = None
        if self.loan_expired and remaining_principal > 0:
            months_default = int(application.term_months or 1)
            if not self.is_bound:
                self.fields["renewal_months_pay"].initial = months_default
            else:
                try:
                    months_default = int(
                        self.data.get("renewal_months_pay") or months_default
                    )
                except (TypeError, ValueError):
                    pass
            savings_default = Decimal("0.00")
            if self.is_bound:
                try:
                    savings_default = Decimal(
                        str(self.data.get("renewal_savings") or "0") or "0"
                    )
                except Exception:
                    savings_default = Decimal("0.00")
            self.renewal_calc = compute_expired_loan_renewal_charges(
                remaining_principal,
                self.interest_rate,
                months_default,
                savings=savings_default,
            )
            self.fields["renewal_months_pay"].required = True
        else:
            self.fields["renewal_months_pay"].widget = forms.HiddenInput()
            self.fields["renewal_savings"].widget = forms.HiddenInput()

        # Auto-start next interest period from previous payment To (or application date).
        # To = one calendar month later (same rule as apply-page usable date calculation).
        if application is not None and not self.is_bound:
            start = application.next_usable_from_date()
            end = _add_calendar_months(start, 1)
            self.fields["usable_from"].initial = start
            self.fields["usable_to"].initial = end
            self.fields["usable_days"].initial = (end - start).days

        # Usable dates are required only when usable days are enabled for this payment.
        if remaining > 0 and self.use_usable_days:
            self.fields["usable_from"].required = True
            self.fields["usable_to"].required = True
            self.fields["usable_from"].widget.attrs["required"] = True
            self.fields["usable_to"].widget.attrs["required"] = True
            if application is not None:
                locked_from = application.next_usable_from_date()
                self.fields["usable_from"].initial = locked_from
                if self.is_bound:
                    submitted = self.data.get("usable_from")
                    if submitted and submitted != locked_from.isoformat():
                        self._usable_from_tampered = True
                    mutable = self.data.copy()
                    mutable["usable_from"] = locked_from.isoformat()
                    self.data = mutable
        else:
            self.fields["usable_from"].widget.attrs.pop("required", None)
            self.fields["usable_to"].widget.attrs.pop("required", None)

        # Days stay hidden — only From/To months are shown (usable interest ≠ savings).
        self.fields["usable_days"].required = False

        amount_field = self.fields["amount_paid"]
        amount_field.required = True
        if remaining > 0:
            from loans.services import (
                _add_calendar_months,
                period_interest_on_remaining_principal,
            )

            if self.use_usable_days and application is not None:
                start = application.next_usable_from_date()
                preview_days = (_add_calendar_months(start, 1) - start).days
            else:
                preview_days = 0
            preview_interest = (
                period_interest_on_remaining_principal(application, preview_days)
                if preview_days > 0
                else Decimal("0.00")
            )
            renewal_charges = Decimal("0.00")
            if self.renewal_calc:
                renewal_charges = Decimal(self.renewal_calc["total_charges"] or 0)
            max_amount = (remaining + preview_interest + renewal_charges).quantize(
                Decimal("0.01")
            )
            amount_field.widget.attrs.update(
                {
                    "step": "0.01",
                    "min": "0.01",
                    "max": str(max_amount),
                    "placeholder": "0.00",
                }
            )
            # Start empty of balance so staff enter the actual amount paid.
            amount_field.initial = Decimal("0.00")
            parts = [f"balance left ₱{remaining:,.2f}"]
            if renewal_charges > 0:
                parts.append(f"expired-loan charges ₱{renewal_charges:,.2f}")
            if preview_interest > 0:
                parts.append(f"period interest ₱{preview_interest:,.2f}")
            amount_field.help_text = (
                f"Maximum allowed: ₱{max_amount:,.2f} ({' + '.join(parts)})."
            )
            amount_field.label = "Amount paid (up to remaining balance)"
        else:
            amount_field.widget.attrs.update(
                {
                    "step": "0.01",
                    "min": "0.01",
                    "max": "0",
                    "disabled": True,
                }
            )
            amount_field.required = False
            amount_field.help_text = "This loan has no remaining balance to collect."
            for name in (
                "payment_method",
                "or_number",
                "remarks",
                "usable_from",
                "usable_to",
                "usable_days",
                "use_usable_days",
                "renewal_months_pay",
                "renewal_savings",
            ):
                self.fields[name].disabled = True
                self.fields[name].required = False

    def _resolve_use_usable_days(self):
        """True only when staff explicitly enabled usable days for this payment."""
        if self.is_bound:
            raw = self.data.get("use_usable_days", "0")
        else:
            raw = self.fields["use_usable_days"].initial or "0"
        return str(raw).strip().lower() not in ("", "0", "false", "off", "no")

    def clean_use_usable_days(self):
        raw = self.cleaned_data.get("use_usable_days", "0")
        return "1" if self._truthy_flag(raw) else "0"

    @staticmethod
    def _truthy_flag(raw):
        return str(raw or "").strip().lower() not in ("", "0", "false", "off", "no")

    def clean(self):
        from decimal import Decimal

        from loans.services import (
            compute_expired_loan_renewal_charges,
            period_interest_on_remaining_principal,
        )

        cleaned_data = super().clean()
        use_usable_days = self._truthy_flag(cleaned_data.get("use_usable_days", "0"))
        cleaned_data["use_usable_days"] = use_usable_days
        self.use_usable_days = use_usable_days

        usable_from = cleaned_data.get("usable_from")
        usable_to = cleaned_data.get("usable_to")
        period_interest = Decimal("0.00")
        renewal_charges = Decimal("0.00")
        remaining = Decimal(self.remaining_balance or 0)
        remaining_principal = Decimal(self.remaining_principal or 0)

        # Expired loan: charge renewal formula on remaining principal.
        if getattr(self, "loan_expired", False) and remaining_principal > 0:
            months_pay = cleaned_data.get("renewal_months_pay")
            if months_pay is None or int(months_pay) < 1:
                self.add_error(
                    "renewal_months_pay",
                    "Enter months to pay for the expired-loan renewal charges.",
                )
                months_pay = int(
                    getattr(self.application, "term_months", None) or 1
                )
            else:
                months_pay = int(months_pay)
            savings = cleaned_data.get("renewal_savings") or Decimal("0.00")
            calc = compute_expired_loan_renewal_charges(
                remaining_principal,
                self.interest_rate,
                months_pay,
                savings=savings,
            )
            self.renewal_calc = calc
            renewal_charges = Decimal(calc["total_charges"] or 0)
            cleaned_data["renewal_months_pay"] = months_pay
            cleaned_data["renewal_savings"] = calc["savings_amount"]
            cleaned_data["renewal_breakdown"] = calc

        if not use_usable_days:
            cleaned_data["usable_from"] = None
            cleaned_data["usable_to"] = None
            cleaned_data["usable_days"] = None
        else:
            if self.application is not None and remaining > 0:
                expected_from = self.application.next_usable_from_date()
                if getattr(self, "_usable_from_tampered", False):
                    self.add_error(
                        "usable_from",
                        "From date is set automatically and cannot be changed.",
                    )
                cleaned_data["usable_from"] = expected_from
                usable_from = expected_from

            if usable_from and usable_to:
                days = (usable_to - usable_from).days
                if days < 0:
                    self.add_error(
                        "usable_to", "To date must be on or after From date."
                    )
                else:
                    cleaned_data["usable_days"] = days
                    if (
                        self.application is not None
                        and days > 0
                        and Decimal(self.remaining_balance or 0) > 0
                    ):
                        period_interest = period_interest_on_remaining_principal(
                            self.application, days
                        )
            elif usable_from or usable_to:
                self.add_error(
                    "usable_to",
                    "Select both From and To dates for the interest period.",
                )

        total_extra = (period_interest + renewal_charges).quantize(Decimal("0.01"))
        cleaned_data["period_interest"] = total_extra
        cleaned_data["renewal_charges"] = renewal_charges
        self.period_interest = total_extra

        amount = cleaned_data.get("amount_paid")
        remaining = Decimal(self.remaining_balance or 0)
        uses_formula = False
        if self.application is not None:
            from loans.services import product_uses_usable_days

            uses_formula = product_uses_usable_days(self.application)
        if uses_formula and use_usable_days:
            # Amount entered is partial principal only. Interest is collected on top.
            max_allowed = remaining.quantize(Decimal("0.01"))
        else:
            max_allowed = (remaining + total_extra).quantize(Decimal("0.01"))
        if amount is not None and max_allowed > 0 and amount > max_allowed:
            if uses_formula and use_usable_days:
                self.add_error(
                    "amount_paid",
                    f"Partial pay cannot exceed ₱{max_allowed:,.2f} "
                    f"(balance left). Interest is added on top as total to pay.",
                )
            else:
                notes = []
                if renewal_charges > 0:
                    notes.append(f"expired-loan charges ₱{renewal_charges:,.2f}")
                if period_interest > 0:
                    notes.append(f"period interest ₱{period_interest:,.2f}")
                extra_note = f" + {' + '.join(notes)}" if notes else ""
                self.add_error(
                    "amount_paid",
                    f"Amount cannot exceed ₱{max_allowed:,.2f} "
                    f"(balance ₱{remaining:,.2f}{extra_note}).",
                )
        return cleaned_data

    def clean_amount_paid(self):
        from decimal import Decimal, InvalidOperation

        amount = self.cleaned_data.get("amount_paid")
        remaining = getattr(self, "remaining_balance", None)

        if remaining is None and self.application is not None:
            remaining = Decimal(self.application.total_outstanding_balance() or 0)

        if remaining is not None and remaining <= 0:
            raise forms.ValidationError("This loan is already fully paid.")

        if amount is None:
            raise forms.ValidationError("Enter the amount paid.")

        try:
            amount = Decimal(amount)
        except (InvalidOperation, TypeError, ValueError):
            raise forms.ValidationError("Enter a valid amount.")

        if amount <= 0:
            raise forms.ValidationError("Amount must be greater than zero.")

        return amount.quantize(Decimal("0.01"))
