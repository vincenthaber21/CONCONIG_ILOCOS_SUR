"""Loan origination, underwriting, disbursement and servicing models.

The lifecycle of a LoanApplication is modelled as a finite state machine
using django-fsm-2. Every other model in this module hangs off a
LoanApplication and represents one stage of the cooperative's credit
pipeline (eligibility verification, credit investigation, committee
review, insurance enrollment, documentation, disbursement, repayment and
delinquency tracking).
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django_fsm import FSMField, transition

from core.models import BaseModel, TimeStampedModel

User = settings.AUTH_USER_MODEL


# ---------------------------------------------------------------------------
# Catalog / intake
# ---------------------------------------------------------------------------


class LoanProduct(BaseModel):
    """A loan product/offering members can apply for."""

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    interest_rate = models.DecimalField(
        max_digits=6, decimal_places=3, help_text="Annual interest rate, percent."
    )
    min_amount = models.DecimalField(max_digits=12, decimal_places=2)
    max_amount = models.DecimalField(max_digits=12, decimal_places=2)
    requires_collateral = models.BooleanField(default=False)
    requires_insurance = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class LoanInquiry(TimeStampedModel):
    """A pre-application inquiry logged by staff or the member."""

    member = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="loan_inquiries"
    )
    loan_product = models.ForeignKey(
        LoanProduct,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inquiries",
    )
    notes = models.TextField(blank=True)
    staff_handled_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="handled_inquiries",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Inquiry by {self.member} on {self.created_at:%Y-%m-%d}"


# ---------------------------------------------------------------------------
# Core application + FSM
# ---------------------------------------------------------------------------


class LoanApplication(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        SUBMITTED = "SUBMITTED", "Submitted"
        UNDER_VERIFICATION = "UNDER_VERIFICATION", "Under Verification"
        VERIFICATION_FAILED = "VERIFICATION_FAILED", "Verification Failed"
        UNDER_INVESTIGATION = "UNDER_INVESTIGATION", "Under Investigation"
        PENDING_COMMITTEE_APPROVAL = (
            "PENDING_COMMITTEE_APPROVAL",
            "Pending Committee Approval",
        )
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        INSURANCE_ENROLLED = "INSURANCE_ENROLLED", "Insurance Enrolled"
        DOCUMENTATION_SIGNED = "DOCUMENTATION_SIGNED", "Documentation Signed"
        DISBURSED = "DISBURSED", "Disbursed"
        ACTIVE = "ACTIVE", "Active"
        FULLY_PAID = "FULLY_PAID", "Fully Paid"
        CLOSED = "CLOSED", "Closed"

    member = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="loan_applications"
    )
    loan_product = models.ForeignKey(
        LoanProduct, on_delete=models.PROTECT, related_name="applications"
    )
    amount_requested = models.DecimalField(max_digits=12, decimal_places=2)
    purpose = models.TextField(blank=True)
    term_months = models.PositiveIntegerField(default=12)
    status = FSMField(default=Status.DRAFT, choices=Status.choices, protected=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        permissions = [
            ("can_verify", "Can verify loan application eligibility"),
            ("can_investigate", "Can perform credit investigation"),
            ("can_approve", "Can approve/reject loan applications (committee)"),
            ("can_disburse", "Can disburse approved loans"),
            ("can_collect_payment", "Can collect loan repayments"),
        ]

    def __str__(self):
        return f"Loan #{str(self.id)[:8]} - {self.member} ({self.status})"

    # -- FSM transitions ----------------------------------------------------

    @transition(field=status, source=Status.DRAFT, target=Status.SUBMITTED)
    def submit(self):
        self.submitted_at = timezone.now()

    @transition(
        field=status, source=Status.SUBMITTED, target=Status.UNDER_VERIFICATION
    )
    def begin_verification(self):
        pass

    @transition(
        field=status,
        source=Status.UNDER_VERIFICATION,
        target=Status.UNDER_INVESTIGATION,
        conditions=[lambda self: True],
    )
    def _complete_verification_passed(self):
        pass

    @transition(
        field=status,
        source=Status.UNDER_VERIFICATION,
        target=Status.VERIFICATION_FAILED,
    )
    def _complete_verification_failed(self):
        pass

    def complete_verification(self, passed):
        """Move out of UNDER_VERIFICATION based on the verification outcome."""
        if passed:
            self._complete_verification_passed()
        else:
            self._complete_verification_failed()

    def verify(self, passed):
        """Convenience: begin verification then immediately resolve it."""
        self.begin_verification()
        self.complete_verification(passed)

    @transition(
        field=status,
        source=Status.UNDER_INVESTIGATION,
        target=Status.PENDING_COMMITTEE_APPROVAL,
    )
    def submit_for_committee(self):
        pass

    @transition(
        field=status, source=Status.PENDING_COMMITTEE_APPROVAL, target=Status.APPROVED
    )
    def approve(self):
        pass

    @transition(
        field=status, source=Status.PENDING_COMMITTEE_APPROVAL, target=Status.REJECTED
    )
    def reject(self):
        self.notify_applicant()

    @transition(
        field=status, source=Status.APPROVED, target=Status.INSURANCE_ENROLLED
    )
    def enroll_insurance(self):
        pass

    @transition(
        field=status,
        source=[Status.INSURANCE_ENROLLED, Status.APPROVED],
        target=Status.DOCUMENTATION_SIGNED,
    )
    def prepare_documentation(self):
        pass

    @transition(
        field=status,
        source=[Status.INSURANCE_ENROLLED, Status.APPROVED],
        target=Status.DOCUMENTATION_SIGNED,
    )
    def sign_documents(self):
        pass

    @transition(
        field=status, source=Status.DOCUMENTATION_SIGNED, target=Status.DISBURSED
    )
    def _disburse(self):
        pass

    @transition(field=status, source=Status.DISBURSED, target=Status.ACTIVE)
    def activate(self):
        pass

    def disburse(self):
        """Convenience: mark disbursed then immediately activate the loan."""
        self._disburse()
        self.activate()

    @transition(field=status, source=Status.ACTIVE, target=Status.FULLY_PAID)
    def mark_fully_paid(self):
        pass

    @transition(field=status, source=Status.FULLY_PAID, target=Status.CLOSED)
    def close_account(self):
        from . import services

        services.generate_clearance_certificate(self)
        for collateral in self.collaterals.filter(is_released=False):
            collateral.is_released = True
            collateral.released_at = timezone.now()
            collateral.release_notes = collateral.release_notes or "Released on loan closure."
            collateral.save(update_fields=["is_released", "released_at", "release_notes"])
        self.notify_applicant()

    # -- Helpers --------------------------------------------------------

    def total_outstanding_balance(self):
        """Sum of unpaid amortization installments (or lump sum) still due."""
        installment_total = self.amortization_schedules.filter(is_paid=False).aggregate(
            total=models.Sum("total_due")
        )["total"] or Decimal("0")

        lump_sum = getattr(self, "lump_sum_payoff", None)
        if lump_sum and not lump_sum.is_paid:
            installment_total += lump_sum.total_amount_due

        return installment_total

    def notify_applicant(self):
        from . import services

        return services.notify_applicant_of_disapproval(self)


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


class RequiredDocument(TimeStampedModel):
    loan_product = models.ForeignKey(
        LoanProduct, on_delete=models.CASCADE, related_name="required_documents"
    )
    document_type = models.CharField(max_length=100)
    is_mandatory = models.BooleanField(default=True)

    class Meta:
        ordering = ["loan_product", "document_type"]

    def __str__(self):
        return f"{self.document_type} ({self.loan_product})"


class SubmittedDocument(TimeStampedModel):
    application = models.ForeignKey(
        LoanApplication, on_delete=models.CASCADE, related_name="submitted_documents"
    )
    document_type = models.CharField(max_length=100)
    file = models.FileField(upload_to="loan_documents/%Y/%m/")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    is_verified = models.BooleanField(default=False)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.document_type} for {self.application_id}"


# ---------------------------------------------------------------------------
# Verification / investigation / committee
# ---------------------------------------------------------------------------


class EligibilityVerification(TimeStampedModel):
    application = models.OneToOneField(
        LoanApplication, on_delete=models.CASCADE, related_name="eligibility_verification"
    )
    verified_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="verifications_done"
    )
    membership_status_ok = models.BooleanField(default=False)
    documents_complete = models.BooleanField(default=False)
    remarks = models.TextField(blank=True)
    verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Eligibility check for {self.application_id}"

    @property
    def passed(self):
        return self.membership_status_ok and self.documents_complete


class CreditInvestigation(TimeStampedModel):
    class Recommendation(models.TextChoices):
        RECOMMEND_APPROVE = "RECOMMEND_APPROVE", "Recommend Approve"
        RECOMMEND_DENY = "RECOMMEND_DENY", "Recommend Deny"

    application = models.OneToOneField(
        LoanApplication, on_delete=models.CASCADE, related_name="credit_investigation"
    )
    evaluated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="investigations_done"
    )
    repayment_capacity_score = models.PositiveSmallIntegerField(default=0)
    loan_purpose_assessment = models.TextField(blank=True)
    recommendation = models.CharField(max_length=30, choices=Recommendation.choices)
    remarks = models.TextField(blank=True)
    evaluated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Investigation for {self.application_id}"


class CommitteeReview(TimeStampedModel):
    class Decision(models.TextChoices):
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    application = models.OneToOneField(
        LoanApplication, on_delete=models.CASCADE, related_name="committee_review"
    )
    reviewed_by = models.ManyToManyField(User, related_name="committee_reviews")
    decision = models.CharField(max_length=20, choices=Decision.choices)
    decision_date = models.DateTimeField(null=True, blank=True)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Committee review for {self.application_id}: {self.decision}"


# ---------------------------------------------------------------------------
# Insurance / documentation / disbursement / collateral
# ---------------------------------------------------------------------------


class InsuranceEnrollment(TimeStampedModel):
    class InsuranceType(models.TextChoices):
        CREDIT_LIFE = "CREDIT_LIFE", "Credit Life"

    class PaymentMode(models.TextChoices):
        COLLECTED = "COLLECTED", "Collected Upfront"
        FINANCED = "FINANCED", "Financed Into Loan"

    application = models.OneToOneField(
        LoanApplication, on_delete=models.CASCADE, related_name="insurance_enrollment"
    )
    insurance_type = models.CharField(
        max_length=30, choices=InsuranceType.choices, default=InsuranceType.CREDIT_LIFE
    )
    premium_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    payment_mode = models.CharField(max_length=20, choices=PaymentMode.choices)
    enrolled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Insurance for {self.application_id}"


class LoanDocumentation(TimeStampedModel):
    application = models.OneToOneField(
        LoanApplication, on_delete=models.CASCADE, related_name="documentation"
    )
    agreement_file = models.FileField(upload_to="loan_agreements/%Y/%m/", blank=True)
    signed_by_borrower_at = models.DateTimeField(null=True, blank=True)
    signed_by_authorized_personnel_at = models.DateTimeField(null=True, blank=True)
    witnessed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="witnessed_documentations",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Documentation for {self.application_id}"


class Disbursement(TimeStampedModel):
    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        CHECK = "CHECK", "Check"
        BANK_TRANSFER = "BANK_TRANSFER", "Bank Transfer"

    application = models.OneToOneField(
        LoanApplication, on_delete=models.CASCADE, related_name="disbursement"
    )
    amount_released = models.DecimalField(max_digits=12, decimal_places=2)
    disbursed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="disbursements_made"
    )
    disbursement_date = models.DateTimeField(default=timezone.now)
    disbursement_method = models.CharField(max_length=20, choices=Method.choices)
    reference_number = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["-disbursement_date"]

    def __str__(self):
        return f"Disbursement for {self.application_id}: {self.amount_released}"


class Collateral(TimeStampedModel):
    application = models.ForeignKey(
        LoanApplication, on_delete=models.CASCADE, related_name="collaterals"
    )
    description = models.TextField()
    estimated_value = models.DecimalField(max_digits=12, decimal_places=2)
    is_released = models.BooleanField(default=False)
    release_notes = models.TextField(blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Collateral for {self.application_id}"


# ---------------------------------------------------------------------------
# Repayment
# ---------------------------------------------------------------------------


class PaymentOption(TimeStampedModel):
    class Option(models.TextChoices):
        LUMP_SUM = "LUMP_SUM", "Lump Sum"
        MONTHLY_AMORTIZATION = "MONTHLY_AMORTIZATION", "Monthly Amortization"

    application = models.OneToOneField(
        LoanApplication, on_delete=models.CASCADE, related_name="payment_option"
    )
    option = models.CharField(max_length=30, choices=Option.choices)
    selected_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Payment option for {self.application_id}: {self.option}"


class AmortizationSchedule(TimeStampedModel):
    application = models.ForeignKey(
        LoanApplication, on_delete=models.CASCADE, related_name="amortization_schedules"
    )
    installment_number = models.PositiveIntegerField()
    due_date = models.DateField()
    principal_due = models.DecimalField(max_digits=12, decimal_places=2)
    interest_due = models.DecimalField(max_digits=12, decimal_places=2)
    fees_due = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    total_due = models.DecimalField(max_digits=12, decimal_places=2)
    is_paid = models.BooleanField(default=False)

    class Meta:
        ordering = ["application", "installment_number"]
        unique_together = ("application", "installment_number")

    def __str__(self):
        return f"Installment #{self.installment_number} for {self.application_id}"


class LumpSumPayoff(TimeStampedModel):
    application = models.OneToOneField(
        LoanApplication, on_delete=models.CASCADE, related_name="lump_sum_payoff"
    )
    maturity_date = models.DateField()
    total_amount_due = models.DecimalField(max_digits=12, decimal_places=2)
    is_paid = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Lump sum payoff for {self.application_id}"


class Payment(TimeStampedModel):
    class Method(models.TextChoices):
        CASH = "CASH", "Cash"
        CHECK = "CHECK", "Check"
        ONLINE = "ONLINE", "Online"
        DEDUCTION = "DEDUCTION", "Payroll/Share Deduction"

    application = models.ForeignKey(
        LoanApplication, on_delete=models.CASCADE, related_name="payments"
    )
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2)
    payment_date = models.DateTimeField(default=timezone.now)
    collected_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="payments_collected"
    )
    payment_method = models.CharField(max_length=20, choices=Method.choices)
    or_number = models.CharField(max_length=50, blank=True)
    applied_to_installment = models.ForeignKey(
        AmortizationSchedule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="payments",
    )
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-payment_date"]

    def __str__(self):
        return f"Payment of {self.amount_paid} for {self.application_id}"


class DelinquencyRecord(TimeStampedModel):
    application = models.ForeignKey(
        LoanApplication, on_delete=models.CASCADE, related_name="delinquency_records"
    )
    days_overdue = models.PositiveIntegerField(default=0)
    amount_overdue = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0"))
    flagged_at = models.DateTimeField(default=timezone.now)
    follow_up_notes = models.TextField(blank=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ["-flagged_at"]

    def __str__(self):
        return f"Delinquency for {self.application_id} ({self.days_overdue} days)"


class LoanSettlement(TimeStampedModel):
    application = models.OneToOneField(
        LoanApplication, on_delete=models.CASCADE, related_name="settlement"
    )
    closed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="settlements_closed"
    )
    closure_date = models.DateTimeField(default=timezone.now)
    clearance_issued = models.BooleanField(default=False)
    clearance_document = models.FileField(
        upload_to="clearance_certificates/%Y/%m/", blank=True
    )
    collateral_released = models.BooleanField(default=False)
    collateral_release_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-closure_date"]

    def __str__(self):
        return f"Settlement for {self.application_id}"


class NotificationLog(TimeStampedModel):
    application = models.ForeignKey(
        LoanApplication, on_delete=models.CASCADE, related_name="notification_logs"
    )
    channel = models.CharField(max_length=30, default="EMAIL")
    message = models.TextField()
    sent_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-sent_at"]

    def __str__(self):
        return f"Notification for {self.application_id} via {self.channel}"
