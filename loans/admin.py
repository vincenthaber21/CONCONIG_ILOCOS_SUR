from django.contrib import admin
from django.shortcuts import redirect
from django.urls import reverse

from . import models


@admin.register(models.LoanSettings)
class LoanSettingsAdmin(admin.ModelAdmin):
    fieldsets = (
        (
            "Late payment",
            {
                "description": (
                    "Grace period after an installment due date before late-payment "
                    "interest is applied."
                ),
                "fields": ("grace_period_days",),
            },
        ),
        (
            "Loan eligibility",
            {
                "description": (
                    "Waiting period before a member can request a loan. A new member "
                    "(for example, only 1 week registered) cannot apply until this many "
                    "months have passed. Set to 0 to allow loans immediately."
                ),
                "fields": ("min_membership_months",),
            },
        ),
        (
            "Credit committee",
            {
                "description": (
                    "How many approvals are required at the Credit Committee stage. "
                    "Single approver mode makes it easy for one authorized user to "
                    "approve or reject a loan."
                ),
                "fields": ("committee_single_approver",),
            },
        ),
        (
            "Metadata",
            {
                "fields": ("updated_at",),
                "classes": ("collapse",),
            },
        ),
    )
    readonly_fields = ("updated_at",)

    def has_add_permission(self, request):
        return not models.LoanSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        settings_obj = models.LoanSettings.get()
        return redirect(
            reverse("admin:loans_loansettings_change", args=[settings_obj.pk])
        )


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


class LoanApplicationAuditLogInline(admin.TabularInline):
    model = models.LoanApplicationAuditLog
    extra = 0
    max_num = 0
    can_delete = False
    readonly_fields = (
        "action",
        "actor_label",
        "description",
        "metadata",
        "ip_address",
        "created_at",
    )
    fields = readonly_fields
    ordering = ("-created_at",)

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(models.LoanProduct)
class LoanProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "interest_rate",
        "interest_start_month",
        "min_amount",
        "max_amount",
        "term_months",
        "requires_collateral",
        "requires_insurance",
    )
    list_filter = ("requires_collateral", "requires_insurance")
    search_fields = ("name",)
    fieldsets = (
        (None, {"fields": ("name", "description")}),
        (
            "Interest",
            {
                "fields": ("interest_rate", "interest_start_month"),
                "description": (
                    "Interest is charged only when a member does not pay on or before "
                    "the installment due date, after the Loan Settings grace period. "
                    "On-time payments have ₱0 interest. Use Interest start month to keep "
                    "early installments interest-free even if they are paid late."
                ),
            },
        ),
        (
            "Amount, term & requirements",
            {
                "fields": (
                    "min_amount",
                    "max_amount",
                    "term_months",
                    "requires_collateral",
                    "requires_insurance",
                ),
                "description": (
                    "Term (months) is the fixed loan length for this product. "
                    "Members cannot change it when requesting a loan."
                ),
            },
        ),
    )

    def get_deleted_objects(self, objs, request):
        """Allow admins to delete products that still have related applications.

        Related loan applications (and their cascade children, including
        append-only audit logs) are deleted with the product. Audit logs are
        not deletable on their own, so clear that permission gate here.
        """
        deleted_objects, model_count, perms_needed, protected = super().get_deleted_objects(
            objs, request
        )
        if not (request.user.is_superuser or request.user.is_staff):
            return deleted_objects, model_count, perms_needed, protected

        audit_label = str(models.LoanApplicationAuditLog._meta.verbose_name)
        perms_needed.discard(audit_label)
        # PROTECT leftovers should not apply after CASCADE; keep empty for safety.
        protected = []
        return deleted_objects, model_count, perms_needed, protected

    def has_delete_permission(self, request, obj=None):
        return request.user.is_active and (
            request.user.is_superuser or request.user.is_staff
        )


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
    inlines = [AmortizationScheduleInline, PaymentInline, LoanApplicationAuditLogInline]
    actions = ["send_reminder"]

    def get_deleted_objects(self, objs, request):
        """Allow deleting applications even though audit logs are append-only.

        Audit log rows cannot be deleted on their own (see
        LoanApplicationAuditLogAdmin), but they cascade with the parent
        application. Without clearing that permission gate, Django admin
        blocks loan application deletion for every user.
        """
        deleted_objects, model_count, perms_needed, protected = super().get_deleted_objects(
            objs, request
        )
        audit_label = str(models.LoanApplicationAuditLog._meta.verbose_name)
        perms_needed.discard(audit_label)
        return deleted_objects, model_count, perms_needed, protected

    @admin.action(description="Send payment reminder to selected (overdue) applications")
    def send_reminder(self, request, queryset):
        from loans.notifications import notify_loan_member, resolve_loan_recipient_email
        from loans.services import overdue_cutoff_date

        sent = 0
        for application in queryset:
            overdue = application.amortization_schedules.filter(
                is_paid=False, due_date__lt=overdue_cutoff_date()
            )
            if not overdue.exists():
                continue
            notify_loan_member(application, "payment_reminder")
            if resolve_loan_recipient_email(application):
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
    list_display = (
        "application",
        "signing_method",
        "signed_by_borrower_at",
        "signed_by_authorized_personnel_at",
        "witnessed_by",
    )
    list_filter = ("signing_method",)
    readonly_fields = ("signed_hard_copy_uploaded_at", "signed_hard_copy_uploaded_by")


@admin.register(models.Disbursement)
class DisbursementAdmin(admin.ModelAdmin):
    list_display = (
        "application",
        "amount_released",
        "transaction_fee",
        "other_deduction_amount",
        "disbursement_method",
        "disbursement_date",
        "disbursed_by",
    )
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
        from loans.notifications import notify_loan_member, resolve_loan_recipient_email

        sent = 0
        for record in queryset:
            application = record.application
            notify_loan_member(
                application,
                "overdue",
                extra={
                    "days_overdue": record.days_overdue,
                    "amount_overdue": record.amount_overdue,
                },
            )
            if resolve_loan_recipient_email(application):
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


@admin.register(models.LoanApplicationAuditLog)
class LoanApplicationAuditLogAdmin(admin.ModelAdmin):
    list_display = ("application", "action", "actor_label", "created_at", "ip_address")
    list_filter = ("action", "created_at")
    search_fields = ("application__id", "actor_label", "description")
    readonly_fields = (
        "application",
        "action",
        "actor",
        "actor_label",
        "description",
        "metadata",
        "ip_address",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
