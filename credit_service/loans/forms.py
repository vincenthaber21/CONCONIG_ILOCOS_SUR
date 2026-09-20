from django import forms

from . import models


class LoanInquiryForm(forms.ModelForm):
    class Meta:
        model = models.LoanInquiry
        fields = ["loan_product", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class LoanApplicationForm(forms.ModelForm):
    class Meta:
        model = models.LoanApplication
        fields = ["loan_product", "amount_requested", "purpose", "term_months"]
        widgets = {
            "purpose": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned_data = super().clean()
        product = cleaned_data.get("loan_product")
        amount = cleaned_data.get("amount_requested")
        if product and amount is not None:
            if amount < product.min_amount or amount > product.max_amount:
                raise forms.ValidationError(
                    f"Amount must be between {product.min_amount} and {product.max_amount} "
                    f"for {product.name}."
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
            "loan_purpose_assessment": forms.Textarea(attrs={"rows": 3}),
            "remarks": forms.Textarea(attrs={"rows": 3}),
        }


class CommitteeReviewForm(forms.ModelForm):
    class Meta:
        model = models.CommitteeReview
        fields = ["reviewed_by", "decision", "remarks"]
        widgets = {
            "remarks": forms.Textarea(attrs={"rows": 3}),
        }


class InsuranceEnrollmentForm(forms.ModelForm):
    class Meta:
        model = models.InsuranceEnrollment
        fields = ["insurance_type", "premium_amount", "payment_mode"]


class LoanDocumentationForm(forms.ModelForm):
    class Meta:
        model = models.LoanDocumentation
        fields = [
            "agreement_file",
            "signed_by_borrower_at",
            "signed_by_authorized_personnel_at",
            "witnessed_by",
        ]
        widgets = {
            "signed_by_borrower_at": forms.DateTimeInput(attrs={"type": "datetime-local"}),
            "signed_by_authorized_personnel_at": forms.DateTimeInput(
                attrs={"type": "datetime-local"}
            ),
        }


class DisbursementForm(forms.ModelForm):
    class Meta:
        model = models.Disbursement
        fields = ["amount_released", "disbursement_method", "reference_number"]


class PaymentOptionForm(forms.ModelForm):
    class Meta:
        model = models.PaymentOption
        fields = ["option"]


class PaymentForm(forms.ModelForm):
    class Meta:
        model = models.Payment
        fields = [
            "amount_paid",
            "payment_method",
            "or_number",
            "applied_to_installment",
            "remarks",
        ]
        widgets = {
            "remarks": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, application=None, **kwargs):
        super().__init__(*args, **kwargs)
        if application is not None:
            self.fields["applied_to_installment"].queryset = (
                application.amortization_schedules.filter(is_paid=False)
            )
        self.fields["applied_to_installment"].required = False
