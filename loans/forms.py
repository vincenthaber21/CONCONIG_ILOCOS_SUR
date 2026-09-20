from decimal import Decimal, ROUND_HALF_UP

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
            "min_membership_months",
            "committee_single_approver",
        ]
        widgets = {
            "grace_period_days": forms.NumberInput(attrs={"min": 0, "step": 1}),
            "min_membership_months": forms.NumberInput(attrs={"min": 0, "step": 1}),
            "committee_single_approver": forms.CheckboxInput(),
        }
        labels = {
            "grace_period_days": "Late-payment grace period (days)",
            "min_membership_months": "Minimum membership (months)",
            "committee_single_approver": "Allow one-person committee approval",
        }
        help_texts = {
            "grace_period_days": (
                "How many days after the due date a member may still pay without "
                "late-payment interest. 0 means late interest starts the day after "
                "the due date."
            ),
            "min_membership_months": (
                "Minimum months a member must be registered before they can request a loan. "
                "Set to 0 to allow loan requests immediately."
            ),
            "committee_single_approver": (
                "When checked, any one authorized approver can approve or reject a loan. "
                "When unchecked, a majority of listed approvers is required."
            ),
        }


class LoanProductForm(forms.ModelForm):
    min_amount = MoneyField(min_value=0, max_digits=12, decimal_places=2, label="Minimum amount")
    max_amount = MoneyField(min_value=0, max_digits=12, decimal_places=2, label="Maximum amount")

    class Meta:
        model = models.LoanProduct
        fields = [
            "name",
            "description",
            "term_months",
            "interest_start_month",
            "min_amount",
            "max_amount",
        ]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "term_months": forms.NumberInput(attrs={"min": 1, "step": 1}),
            "interest_start_month": forms.NumberInput(attrs={"min": 1, "step": 1}),
        }
        labels = {
            "term_months": "Term (months)",
            "interest_start_month": "Late interest from month",
        }
        help_texts = {
            "term_months": (
                "How many monthly installments this product uses. "
                "Term only sets the number of months — it does not change interest calculation."
            ),
            "interest_start_month": (
                "Month number from which late interest can be charged "
                "(1 = first installment). Earlier months stay interest-free even if late. "
                "The interest % itself is set per application when applying."
            ),
        }

    def clean(self):
        cleaned_data = super().clean()
        min_amount = cleaned_data.get("min_amount")
        max_amount = cleaned_data.get("max_amount")
        if min_amount is not None and max_amount is not None and min_amount > max_amount:
            raise forms.ValidationError("Minimum amount cannot be greater than maximum amount.")
        term_months = cleaned_data.get("term_months")
        if term_months is not None and term_months < 1:
            self.add_error("term_months", "Term must be at least 1 month.")
        start_month = cleaned_data.get("interest_start_month")
        if start_month is not None and start_month < 1:
            self.add_error("interest_start_month", "Interest start month must be at least 1.")
        return cleaned_data

    def save(self, commit=True):
        from decimal import Decimal

        product = super().save(commit=False)
        # Interest % is entered per application; keep a DB default on the product.
        if getattr(product, "interest_rate", None) is None:
            product.interest_rate = Decimal("0")
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
            "term_months": forms.NumberInput(
                attrs={
                    "min": "1",
                    "step": "1",
                    "inputmode": "numeric",
                    "placeholder": "e.g. 12",
                    "id": "id_term_months",
                }
            ),
            "interest_rate": forms.NumberInput(
                attrs={
                    "step": "0.001",
                    "min": "0",
                    "inputmode": "decimal",
                    "placeholder": "e.g. 0.015",
                    "id": "id_interest_rate",
                }
            ),
            "usable_from": forms.DateInput(
                attrs={"type": "date", "id": "loan-usable-from"}
            ),
            "usable_to": forms.HiddenInput(attrs={"id": "loan-usable-to"}),
            "usable_days": forms.HiddenInput(attrs={"id": "loan-usable-days"}),
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
                "How many months to repay. This only sets the installment count — "
                "it does not change interest calculation."
            ),
            "interest_rate": (
                "Monthly rate as a decimal (e.g. 0.015 = 1.5%). "
                "Interest is computed when a payment is recorded, using the "
                "usable From/To dates on that payment. "
                "Daily interest = (rate ÷ 30) × remaining principal."
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["loan_product"].required = True
        self.fields["loan_product"].empty_label = "— Select a loan product —"
        self.fields["amount_requested"].required = True
        self.fields["amount_requested"].help_text = (
            "Choose a loan product first. You can only request an amount within that product's allowed range."
        )
        self.fields["term_months"].required = True
        self.fields["interest_rate"].required = True
        self.fields["usable_from"].required = True
        self.fields["usable_from"].label = "Application date"
        self.fields["usable_to"].required = False
        self.fields["usable_days"].required = False
        amount_widget = self.fields["amount_requested"].widget
        amount_widget.attrs.setdefault("readonly", "readonly")
        amount_widget.attrs.setdefault("id", "id_amount_requested")
        # Interest rate and term are editable; product selection only prefills defaults.
        self.fields["interest_rate"].widget.attrs.pop("readonly", None)
        self.fields["term_months"].widget.attrs.pop("readonly", None)

        product = self._resolve_selected_product()
        if product is not None:
            self._apply_product_amount_limits(product)
            self._apply_product_interest_default(product)
            self._apply_product_term_default(product)

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
        rate_field.widget.attrs.pop("readonly", None)
        rate_field.widget.attrs["placeholder"] = f"e.g. {product.interest_rate}"
        if not self.is_bound and not self.initial.get("interest_rate"):
            rate_field.initial = product.interest_rate

    def _apply_product_term_default(self, product):
        term_field = self.fields["term_months"]
        term_field.widget.attrs.pop("readonly", None)
        term_field.widget.attrs["placeholder"] = f"e.g. {product.term_months}"
        if not self.is_bound and not self.initial.get("term_months"):
            term_field.initial = product.term_months

    def clean_purpose(self):
        purpose = (self.cleaned_data.get("purpose") or "").strip()
        if not purpose:
            raise forms.ValidationError("Loan purpose is required.")
        return purpose

    def clean_term_months(self):
        term = self.cleaned_data.get("term_months")
        if term is None:
            raise forms.ValidationError("Please enter the loan term in months.")
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

    def clean(self):
        import calendar

        cleaned_data = super().clean()
        product = cleaned_data.get("loan_product")
        amount = cleaned_data.get("amount_requested")
        usable_from = cleaned_data.get("usable_from")

        if not product:
            self.add_error("loan_product", "Please select a loan product.")
            return cleaned_data
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

        # Application date only — end date is one calendar month later.
        if usable_from:
            month_index = usable_from.month  # +1 month (0-based: month-1+1)
            to_year = usable_from.year + month_index // 12
            to_month = month_index % 12 + 1
            to_day = min(usable_from.day, calendar.monthrange(to_year, to_month)[1])
            usable_to = usable_from.replace(year=to_year, month=to_month, day=to_day)
            cleaned_data["usable_to"] = usable_to
            cleaned_data["usable_days"] = (usable_to - usable_from).days
        else:
            self.add_error("usable_from", "Please select the application date.")

        return cleaned_data

    def save(self, commit=True):
        application = super().save(commit=False)
        # Term and interest are user-entered on apply; fall back to product only if blank.
        if application.loan_product_id:
            if not application.term_months:
                application.term_months = application.loan_product.term_months
            if application.interest_rate is None:
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
        # Staff must be able to type an amount / rate after choosing a product.
        self.fields["amount_requested"].widget.attrs.pop("readonly", None)
        self.fields["interest_rate"].widget.attrs.pop("readonly", None)
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
    clear_borrower_signature = forms.BooleanField(required=False, widget=forms.HiddenInput)
    clear_personnel_signature = forms.BooleanField(required=False, widget=forms.HiddenInput)
    regenerate_contract = forms.BooleanField(
        required=False,
        initial=False,
        label="Regenerate system contract PDF from current loan details",
    )

    class Meta:
        model = models.LoanDocumentation
        fields = ["signing_method", "signed_hard_copy", "witnessed_by"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["witnessed_by"].required = False
        self.fields["witnessed_by"].help_text = "Optional witness for the signing."
        instance = getattr(self, "instance", None)
        if instance and instance.signing_method:
            self.fields["signing_method"].initial = instance.signing_method

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


class DisbursementForm(forms.ModelForm):
    amount_released = MoneyField(
        min_value=0,
        max_digits=12,
        decimal_places=2,
        label="Net amount released (₱)",
        widget=money_input(min="0", placeholder="0.00"),
    )
    transaction_fee = MoneyField(
        min_value=0,
        max_digits=12,
        decimal_places=2,
        required=False,
        label="Transaction fee (₱)",
        widget=money_input(min="0", placeholder="0.00"),
    )
    other_deduction_amount = MoneyField(
        min_value=0,
        max_digits=12,
        decimal_places=2,
        required=False,
        label="Other deduction (₱)",
        widget=money_input(min="0", placeholder="0.00"),
    )

    class Meta:
        model = models.Disbursement
        fields = [
            "amount_released",
            "transaction_fee",
            "other_deduction_amount",
            "other_deduction_label",
            "disbursement_method",
            "reference_number",
        ]
        labels = {
            "amount_released": "Net amount released (₱)",
            "transaction_fee": "Transaction fee (₱)",
            "other_deduction_amount": "Other deduction (₱)",
            "other_deduction_label": "Other deduction description",
            "disbursement_method": "Disbursement method",
            "reference_number": "Reference number",
        }
        help_texts = {
            "amount_released": (
                "Cash/check/transfer given to the member after fees. "
                "Principal for repayment stays the full loan amount."
            ),
            "transaction_fee": "Optional fee withheld at disbursement (e.g. transfer charge).",
            "other_deduction_amount": "Optional additional fee withheld at disbursement.",
            "other_deduction_label": "Shown on the disbursement voucher when other deduction is used.",
            "reference_number": "Optional check / transfer reference.",
        }
        widgets = {
            "disbursement_method": forms.RadioSelect(),
            "other_deduction_label": forms.TextInput(
                attrs={"placeholder": "e.g. Processing fee, documentary stamp"}
            ),
            "reference_number": forms.TextInput(
                attrs={"placeholder": "Check no., transfer ref., etc."}
            ),
        }

    def __init__(self, *args, amount_requested=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.amount_requested = amount_requested
        self.fields["disbursement_method"].required = True
        self.fields["disbursement_method"].choices = models.Disbursement.Method.choices
        self.fields["transaction_fee"].initial = Decimal("0.00")
        self.fields["other_deduction_amount"].initial = Decimal("0.00")
        if amount_requested is not None:
            principal = Decimal(amount_requested)
            if not (self.instance and self.instance.pk):
                self.initial.setdefault("amount_released", principal)
                self.fields["amount_released"].initial = principal
            self.fields["amount_released"].widget.attrs["data-principal"] = str(principal)
            self.fields["amount_released"].help_text = (
                "Net cash to the member. Loan principal for repayment remains "
                f"₱{principal:,.2f}."
            )
        if not self.initial.get("disbursement_method") and not (
            self.instance and self.instance.pk and self.instance.disbursement_method
        ):
            self.fields["disbursement_method"].initial = models.Disbursement.Method.CASH
        self.fields["reference_number"].required = False
        self.fields["other_deduction_label"].required = False

    def clean_amount_released(self):
        amount = self.cleaned_data.get("amount_released")
        if amount is None:
            raise forms.ValidationError("Net amount released is required.")
        if amount < 0:
            raise forms.ValidationError("Net amount released cannot be negative.")
        if self.amount_requested is not None and amount > self.amount_requested:
            raise forms.ValidationError(
                "Net amount released cannot exceed the loan principal "
                f"(₱{self.amount_requested:,.2f})."
            )
        return amount

    def clean_transaction_fee(self):
        fee = self.cleaned_data.get("transaction_fee")
        return Decimal(fee or 0).quantize(TWO_PLACES)

    def clean_other_deduction_amount(self):
        amount = self.cleaned_data.get("other_deduction_amount")
        return Decimal(amount or 0).quantize(TWO_PLACES)

    def clean(self):
        cleaned = super().clean()
        if self.amount_requested is None:
            return cleaned

        released = cleaned.get("amount_released")
        if released is None:
            return cleaned

        transaction_fee = cleaned.get("transaction_fee") or Decimal("0.00")
        other_amount = cleaned.get("other_deduction_amount") or Decimal("0.00")
        other_label = (cleaned.get("other_deduction_label") or "").strip()
        principal = Decimal(self.amount_requested).quantize(TWO_PLACES)
        total = (released + transaction_fee + other_amount).quantize(
            TWO_PLACES, rounding=ROUND_HALF_UP
        )

        if total != principal:
            raise ValidationError(
                "Net amount released plus all deductions must equal the loan principal "
                f"(₱{principal:,.2f}). Current total: ₱{total:,.2f}."
            )
        if released <= 0 and (transaction_fee > 0 or other_amount > 0):
            raise ValidationError(
                "Net amount released must be greater than zero when fees are deducted."
            )
        if released <= 0:
            raise ValidationError("Net amount released must be greater than zero.")
        if other_amount > 0 and not other_label:
            self.add_error(
                "other_deduction_label",
                "Please describe the other deduction for the disbursement voucher.",
            )
        return cleaned


class PaymentForm(forms.ModelForm):
    amount_paid = MoneyField(
        min_value=0,
        max_digits=12,
        decimal_places=2,
        label="Amount paid",
        widget=money_input(min="0.01", placeholder="0.00"),
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
            "usable_days": forms.NumberInput(
                attrs={
                    "id": "pay-usable-days",
                    "min": "0",
                    "step": "1",
                    "readonly": "readonly",
                    "tabindex": "-1",
                    "inputmode": "numeric",
                    "title": "Computed as To − From (days)",
                }
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
        from datetime import timedelta
        from decimal import Decimal

        from django.utils import timezone

        super().__init__(*args, **kwargs)
        self.application = application
        self._usable_from_tampered = False
        self.fields["or_number"].required = False
        self.fields["remarks"].required = False
        self.fields["usable_from"].required = False
        self.fields["usable_to"].required = False
        self.fields["usable_days"].required = False

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
        self.interest_rate = (
            Decimal(application.effective_interest_rate() or 0)
            if application is not None
            else Decimal("0")
        )

        # Auto-start next interest period from previous payment To (or application date).
        if application is not None and not self.is_bound:
            start = application.next_usable_from_date()
            self.fields["usable_from"].initial = start
            self.fields["usable_to"].initial = start + timedelta(days=30)
            self.fields["usable_days"].initial = 30

        # Usable dates are required while any balance remains — interest is
        # computed from balance left to pay at payment time.
        if remaining > 0:
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

        amount_field = self.fields["amount_paid"]
        amount_field.required = True
        if remaining > 0:
            from loans.services import period_interest_on_remaining_principal

            preview_interest = period_interest_on_remaining_principal(
                application, 30
            )
            max_amount = (remaining + preview_interest).quantize(Decimal("0.01"))
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
            amount_field.help_text = (
                f"Maximum allowed: ₱{max_amount:,.2f} (balance left + period interest). "
                "Interest is based on balance left to pay, not the original loan amount."
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
            ):
                self.fields[name].disabled = True
                self.fields[name].required = False

    def clean(self):
        from decimal import Decimal

        from loans.services import period_interest_on_remaining_principal

        cleaned_data = super().clean()
        usable_from = cleaned_data.get("usable_from")
        usable_to = cleaned_data.get("usable_to")
        period_interest = Decimal("0.00")

        remaining = Decimal(self.remaining_balance or 0)
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
                self.add_error("usable_to", "To date must be on or after From date.")
            else:
                cleaned_data["usable_days"] = days
                if (
                    self.application is not None
                    and days > 0
                    and Decimal(self.remaining_balance or 0) > 0
                ):
                    # Interest on balance left to pay (not original loan amount).
                    period_interest = period_interest_on_remaining_principal(
                        self.application, days
                    )
        elif usable_from or usable_to:
            self.add_error(
                "usable_to",
                "Select both From and To dates for the interest period.",
            )

        cleaned_data["period_interest"] = period_interest
        self.period_interest = period_interest

        # Allow paying up to outstanding + newly accrued period interest.
        amount = cleaned_data.get("amount_paid")
        remaining = Decimal(self.remaining_balance or 0)
        max_allowed = (remaining + period_interest).quantize(Decimal("0.01"))
        if amount is not None and max_allowed > 0 and amount > max_allowed:
            interest_note = (
                f" + period interest ₱{period_interest:,.2f}"
                if period_interest > 0
                else ""
            )
            self.add_error(
                "amount_paid",
                f"Amount cannot exceed ₱{max_allowed:,.2f} "
                f"(balance ₱{remaining:,.2f}{interest_note}).",
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
