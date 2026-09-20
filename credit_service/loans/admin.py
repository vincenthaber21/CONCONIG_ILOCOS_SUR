from django.contrib import admin
from django.utils import timezone

from . import models


class AmortizationScheduleInline(admin.TabularInline):
    model = models.AmortizationSchedule
    extra = 0
    fields = (
        "installment_number",
        "due_date",
        "principal_due",
        "interest_due",
        "fees_due",
        "total_due",
        "is_paid",
    )


class PaymentInline(admin.TabularInline):
    model = models.Payment
    extra = 0
    fields = (
        "amount_paid",
        "payment_date",
        "payment_method",
        "or_number",
        "collected_by",
    )


@admin.register(models.LoanProduct)
class LoanProductAdmin(admin.ModelAdmin):
    list_display = ("name", "interest_rate", "min_amount", "max_amount", "requires_collateral", "requires_insurance")
    list_filter = ("requires_collateral", "requires_insurance")
    search_fields = ("name",)


@admin.register(models.LoanInquiry)
class LoanInquiryAdmin(admin.ModelAdmin):
    list_display = ("member", "loan_product", "staff_handled_by", "created_at")
    list_filter = ("loan_product",)
    search_fields = ("member__username", "member__first_name", "member__last_name")


@admin.register(models.LoanApplication)
class LoanApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "member",
        "loan_product",
        "amount_requested",
        "status",
        "submitted_at",
        "created_at",
    )
    list_filter = ("status", "loan_product")
    search_fields = ("member__username", "id")
    readonly_fields = ("status",)
    inlines = [AmortizationScheduleInline, PaymentInline]
    actions = ["send_reminder"]

    @admin.action(description="Send payment reminder to selected (overdue) applications")
    def send_reminder(self, request, queryset):
        from django.conf import settings
        from django.core.mail import send_mail

        sent = 0
        for application in queryset:
            overdue = application.amortization_schedules.filter(
                is_paid=False, due_date__lt=timezone.localdate()
            )
            if not overdue.exists():
                continue
            member_email = getattr(application.member, "email", "") or ""
            if member_email:
                send_mail(
                    "Payment reminder",
                    f"You have overdue installments on loan {application.id}.",
                    settings.DEFAULT_FROM_EMAIL,
                    [member_email],
                    fail_silently=True,
                )
                sent += 1
        self.message_user(request, f"Sent {sent} reminder(s).")


@admin.register(models.RequiredDocument)
class RequiredDocumentAdmin(admin.ModelAdmin):
    list_display = ("document_type", "loan_product", "is_mandatory")
    list_filter = ("loan_product", "is_mandatory")


@admin.register(models.SubmittedDocument)
class SubmittedDocumentAdmin(admin.ModelAdmin):
    list_display = ("application", "document_type", "is_verified", "uploaded_at")
    list_filter = ("is_verified", "document_type")


@admin.register(models.EligibilityVerification)
class EligibilityVerificationAdmin(admin.ModelAdmin):
    list_display = ("application", "verified_by", "membership_status_ok", "documents_complete", "verified_at")
    list_filter = ("membership_status_ok", "documents_complete")


@admin.register(models.CreditInvestigation)
class CreditInvestigationAdmin(admin.ModelAdmin):
    list_display = ("application", "evaluated_by", "repayment_capacity_score", "recommendation", "evaluated_at")
    list_filter = ("recommendation",)


@admin.register(models.CommitteeReview)
class CommitteeReviewAdmin(admin.ModelAdmin):
    list_display = ("application", "decision", "decision_date")
    list_filter = ("decision",)
    filter_horizontal = ("reviewed_by",)


@admin.register(models.InsuranceEnrollment)
class InsuranceEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("application", "insurance_type", "premium_amount", "payment_mode", "enrolled_at")
    list_filter = ("insurance_type", "payment_mode")


@admin.register(models.LoanDocumentation)
class LoanDocumentationAdmin(admin.ModelAdmin):
    list_display = ("application", "signed_by_borrower_at", "signed_by_authorized_personnel_at", "witnessed_by")


@admin.register(models.Disbursement)
class DisbursementAdmin(admin.ModelAdmin):
    list_display = ("application", "amount_released", "disbursement_method", "disbursement_date", "disbursed_by")
    list_filter = ("disbursement_method",)


@admin.register(models.Collateral)
class CollateralAdmin(admin.ModelAdmin):
    list_display = ("application", "description", "estimated_value", "is_released")
    list_filter = ("is_released",)


@admin.register(models.PaymentOption)
class PaymentOptionAdmin(admin.ModelAdmin):
    list_display = ("application", "option", "selected_at")
    list_filter = ("option",)


@admin.register(models.AmortizationSchedule)
class AmortizationScheduleAdmin(admin.ModelAdmin):
    list_display = ("application", "installment_number", "due_date", "total_due", "is_paid")
    list_filter = ("is_paid",)


@admin.register(models.LumpSumPayoff)
class LumpSumPayoffAdmin(admin.ModelAdmin):
    list_display = ("application", "maturity_date", "total_amount_due", "is_paid")
    list_filter = ("is_paid",)


@admin.register(models.Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("application", "amount_paid", "payment_method", "payment_date", "collected_by")
    list_filter = ("payment_method",)
    search_fields = ("or_number",)


@admin.register(models.DelinquencyRecord)
class DelinquencyRecordAdmin(admin.ModelAdmin):
    list_display = ("application", "days_overdue", "amount_overdue", "flagged_at", "resolved")
    list_filter = ("resolved",)
    actions = ["send_reminder"]

    @admin.action(description="Send reminder email for selected delinquencies")
    def send_reminder(self, request, queryset):
        from django.conf import settings
        from django.core.mail import send_mail

        sent = 0
        for record in queryset:
            member_email = getattr(record.application.member, "email", "") or ""
            if member_email:
                send_mail(
                    "Overdue loan payment reminder",
                    f"Your loan {record.application.id} is {record.days_overdue} days overdue.",
                    settings.DEFAULT_FROM_EMAIL,
                    [member_email],
                    fail_silently=True,
                )
                sent += 1
        self.message_user(request, f"Sent {sent} reminder(s).")


@admin.register(models.LoanSettlement)
class LoanSettlementAdmin(admin.ModelAdmin):
    list_display = ("application", "closure_date", "clearance_issued", "collateral_released")
    list_filter = ("clearance_issued", "collateral_released")


@admin.register(models.NotificationLog)
class NotificationLogAdmin(admin.ModelAdmin):
    list_display = ("application", "channel", "sent_at")
    list_filter = ("channel",)
