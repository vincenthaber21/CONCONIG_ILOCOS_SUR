"""Loan origination, underwriting, disbursement and servicing models.

The lifecycle of a LoanApplication is modelled as a finite state machine
using django-fsm-2. Every other model in this module hangs off a
LoanApplication and represents one stage of the cooperative's credit
pipeline (eligibility verification, credit investigation, committee
review, insurance enrollment, documentation, disbursement, repayment and
delinquency tracking).

This app is embedded inside the coop_kiosk project and uses the project's
default ``auth.User`` model (referenced via settings.AUTH_USER_MODEL).
"""

import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone
from django_fsm import FSMField, transition

User = settings.AUTH_USER_MODEL


# ---------------------------------------------------------------------------
# Shared abstract base models (self-contained; no separate `core` app needed)
# ---------------------------------------------------------------------------


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class BaseModel(UUIDModel, TimeStampedModel):
    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Loan servicing settings (singleton)
# ---------------------------------------------------------------------------


class LoanSettings(models.Model):
    """Singleton settings for loan servicing (pk=1)."""

    grace_period_days = models.PositiveIntegerField(
        default=0,
        help_text=(
            "Days after an installment due date before late-payment interest applies. "
            "Example: 5 means a member can still pay without late interest until 5 days "
            "after the due date. Set to 0 to charge late interest starting the day after "
            "the due date."
        ),
    )
    min_membership_months = models.PositiveIntegerField(
        default=3,
        help_text=(
            "Minimum months a member must be registered before they can request a loan. "
            "Example: 3 means a member who joined only 1 week ago cannot apply yet. "
            "Set to 0 to allow loan requests immediately."
        ),
    )
    committee_single_approver = models.BooleanField(
        default=True,
        help_text=(
            "When enabled, one authorized approver (admin, loan officer, staff, or "
            "credit committee) can approve or reject a loan. When disabled, a majority "
            "of listed approvers is required."
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Loan Settings"
        verbose_name_plural = "Loan Settings"

    def __str__(self):
        days = int(self.grace_period_days or 0)
        if days == 1:
            return "Loan settings — 1 day grace period"
        return f"Loan settings — {days} days grace period"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass  # Prevent deletion

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(
            pk=1,
            defaults={
                "grace_period_days": 0,
                "min_membership_months": 3,
                "committee_single_approver": True,
            },
        )
        return obj


# ---------------------------------------------------------------------------
# Catalog / intake
# ---------------------------------------------------------------------------


class LoanProduct(BaseModel):
    """A loan product/offering members can apply for."""

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    interest_rate = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=Decimal("0"),
        help_text=(
            "Legacy product default late-payment interest rate as a monthly decimal "
            "(e.g. 0.015 = 1.5%). The rate used for each loan is set on the application "
            "at apply time. Daily interest = (rate ÷ 30) × principal."
        ),
    )
    interest_start_month = models.PositiveIntegerField(
        default=1,
        help_text=(
            "First installment month that can receive late interest if unpaid past due "
            "(1 = first month). Earlier months stay interest-free even when late."
        ),
    )
    min_amount = models.DecimalField(max_digits=12, decimal_places=2)
    max_amount = models.DecimalField(max_digits=12, decimal_places=2)
    term_months = models.PositiveIntegerField(
        default=12,
        help_text="Fixed repayment term in months for this product (set by admin only).",
    )
    requires_collateral = models.BooleanField(default=False)
    requires_insurance = models.BooleanField(default=False)

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
        LoanProduct, on_delete=models.CASCADE, related_name="applications"
    )
    amount_requested = models.DecimalField(max_digits=12, decimal_places=2)
    purpose = models.TextField(blank=True)
    term_months = models.PositiveIntegerField(default=12)
    interest_rate = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        null=True,
        blank=True,
        help_text=(
            "Interest rate as a monthly decimal (e.g. 0.015 = 1.5%) "
            "for this application. Daily interest = (rate ÷ 30) × remaining principal. "
            "Interest is computed when a payment is recorded with usable dates, "
            "not at apply time. Falls back to the loan product rate when blank."
        ),
    )
    usable_from = models.DateField(
        null=True,
        blank=True,
        help_text="Application date. First payment interest period starts here.",
    )
    usable_to = models.DateField(
        null=True,
        blank=True,
        help_text="Kept for history. Interest is computed at payment time, not apply time.",
    )
    usable_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Calendar span stored at apply time. Interest is not charged from "
            "this value; staff enter usable dates when recording a payment."
        ),
    )
    status = FSMField(default=Status.DRAFT, choices=Status.choices, protected=True)
    submitted_at = models.DateTimeField(null=True, blank=True)

    def effective_interest_rate(self):
        """Rate used for interest: application override, else product default."""
        if self.interest_rate is not None:
            return self.interest_rate
        if self.loan_product_id:
            return self.loan_product.interest_rate
        return Decimal("0")

    def recorded_period_interest(self):
        """Interest charged so far — only from recorded payments, never at apply time."""
        return self.payments.aggregate(total=models.Sum("period_interest"))[
            "total"
        ] or Decimal("0.00")

    def interest_balance_breakdown(self):
        """Principal plus interest actually charged on payments.

        Interest is not computed until staff records a payment with usable dates.
        """
        principal = Decimal(self.amount_requested or 0)
        interest = Decimal(self.recorded_period_interest() or 0)
        return {
            "interest_per_day": Decimal("0"),
            "interest": interest.quantize(Decimal("0.01")),
            "usable_days": 0,
            "current_balance": (principal + interest).quantize(Decimal("0.01")),
        }

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
        pass

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

    # -- Helpers --------------------------------------------------------

    def total_paid_amount(self):
        """Sum of all recorded payments for this loan."""
        return self.payments.aggregate(total=models.Sum("amount_paid"))[
            "total"
        ] or Decimal("0")

    def remaining_principal_balance(self):
        """Unpaid principal after recorded payments (member-friendly).

        Payments reduce principal for interest purposes. Once cumulative
        payments cover ``amount_requested``, remaining principal is ₱0 and
        no further interest should accrue — even if interest balance remains.
        """
        if self.status in {self.Status.FULLY_PAID, self.Status.CLOSED}:
            return Decimal("0.00")

        principal = Decimal(self.amount_requested or 0)
        paid = Decimal(self.total_paid_amount() or 0)
        remaining = principal - paid
        return remaining if remaining > 0 else Decimal("0.00")

    def is_principal_fully_paid(self):
        """True when payments have covered the original loan principal."""
        return self.remaining_principal_balance() <= 0

    def total_obligation_amount(self):
        """Gross amount owed before subtracting payments.

        Interest is charged only when a payment records a usable-days period::
            principal + sum(payment period interest)

        Until the first payment, the obligation is principal only.
        """
        principal = Decimal(self.amount_requested or 0)
        interest = Decimal(self.recorded_period_interest() or 0)
        return (principal + interest).quantize(Decimal("0.01"))

    def next_usable_from_date(self):
        """Start date for the next interest period (previous payment's To).

        The first payment starts from the application date so staff can enter
        the usable period when they collect, not when the loan is applied.
        """
        last_payment = (
            self.payments.filter(usable_to__isnull=False)
            .order_by("-payment_date", "-id")
            .first()
        )
        if last_payment and last_payment.usable_to:
            return last_payment.usable_to
        if self.usable_from:
            return self.usable_from
        return timezone.localdate()

    def total_outstanding_balance(self):
        """Balance still left to pay after recorded payments."""
        if self.status in {self.Status.FULLY_PAID, self.Status.CLOSED}:
            return Decimal("0.00")

        lump_sum = getattr(self, "lump_sum_payoff", None)
        if lump_sum is not None and lump_sum.is_paid:
            return Decimal("0.00")

        remaining = self.total_obligation_amount() - self.total_paid_amount()
        return remaining if remaining > 0 else Decimal("0.00")

    def notify_applicant(self):
        from .notifications import notify_loan_status_change

        return notify_loan_status_change(self, self.status)


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
    repayment_capacity_score = models.DecimalField(
        max_digits=6,
        decimal_places=1,
        default=Decimal("100.0"),
        help_text=(
            "Starts at 100. Reduced by 0.1 for each unpaid overdue installment "
            "on the member's previous loan applications."
        ),
    )
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
    staff_signature = models.ImageField(
        upload_to="loan_signatures/staff_decisions/%Y/%m/",
        blank=True,
        null=True,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Committee review for {self.application_id}: {self.decision}"


class LoanCommitteeVote(TimeStampedModel):
    """Individual admin / loan-officer vote before a loan may be approved."""

    class Vote(models.TextChoices):
        APPROVE = "APPROVE", "Approve"
        REJECT = "REJECT", "Reject"

    application = models.ForeignKey(
        LoanApplication,
        on_delete=models.CASCADE,
        related_name="committee_votes",
    )
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="loan_committee_votes",
    )
    vote = models.CharField(max_length=10, choices=Vote.choices)
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at"]
        unique_together = [("application", "user")]

    def __str__(self):
        return f"{self.user_id} → {self.vote} on {self.application_id}"


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
    class SigningMethod(models.TextChoices):
        DIGITAL = "DIGITAL", "On-screen signatures"
        HARD_COPY = "HARD_COPY", "Uploaded signed hard copy"

    application = models.OneToOneField(
        LoanApplication, on_delete=models.CASCADE, related_name="documentation"
    )
    agreement_file = models.FileField(upload_to="loan_agreements/%Y/%m/", blank=True)
    signing_method = models.CharField(
        max_length=20,
        choices=SigningMethod.choices,
        default=SigningMethod.DIGITAL,
        help_text="How the contract was executed: drawn on screen or scanned paper original.",
    )
    signed_hard_copy = models.FileField(
        upload_to="loan_hard_copies/%Y/%m/",
        blank=True,
        null=True,
        help_text="Scanned or photographed signed paper contract kept for security.",
    )
    signed_hard_copy_uploaded_at = models.DateTimeField(null=True, blank=True)
    signed_hard_copy_uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_loan_hard_copies",
    )
    borrower_signature = models.ImageField(
        upload_to="loan_signatures/%Y/%m/", blank=True, null=True
    )
    personnel_signature = models.ImageField(
        upload_to="loan_signatures/%Y/%m/", blank=True, null=True
    )
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
    amount_released = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        help_text="Net cash/check/transfer given to the member after deductions.",
    )
    transaction_fee = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Transaction or service fee withheld at disbursement.",
    )
    other_deduction_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text="Other fees withheld at disbursement (e.g. processing fee).",
    )
    other_deduction_label = models.CharField(
        max_length=120,
        blank=True,
        help_text="Description of the other deduction, shown on the disbursement voucher.",
    )
    disbursed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="disbursements_made"
    )
    disbursement_date = models.DateTimeField(default=timezone.now)
    disbursement_method = models.CharField(max_length=20, choices=Method.choices)
    reference_number = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ["-disbursement_date"]

    @property
    def principal_amount(self):
        """Loan principal the member repays (requested amount)."""
        if self.application_id:
            return Decimal(self.application.amount_requested or 0)
        return Decimal("0.00")

    @property
    def total_deductions(self):
        return Decimal(self.transaction_fee or 0) + Decimal(self.other_deduction_amount or 0)

    @property
    def voucher_number(self):
        """Stable disbursement voucher reference for receipts."""
        day = timezone.localdate(self.disbursement_date)
        return f"LDV-{day:%Y%m%d}-{self.pk:06d}"

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
    usable_from = models.DateField(
        null=True,
        blank=True,
        help_text="Start of the interest period covered by this payment.",
    )
    usable_to = models.DateField(
        null=True,
        blank=True,
        help_text="End of the interest period covered by this payment.",
    )
    usable_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="To − From. Used to compute period interest on the balance.",
    )
    period_interest = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
        help_text=(
            "Interest for this usable-days period on balance left to pay: "
            "(rate ÷ 30) × outstanding balance × usable_days (rounded). "
            "₱0 when the loan has no remaining balance."
        ),
    )

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


class LoanApplicationAuditLog(TimeStampedModel):
    """Immutable audit trail for a single loan application.

    Every significant action (status change, review, payment, blocked access)
    is recorded here for security and accountability. Rows are append-only.
    """

    class Action(models.TextChoices):
        APPLICATION_CREATED = "APPLICATION_CREATED", "Application Created"
        APPLICATION_SUBMITTED = "APPLICATION_SUBMITTED", "Application Submitted"
        STATUS_CHANGED = "STATUS_CHANGED", "Status Changed"
        ELIGIBILITY_REVIEW = "ELIGIBILITY_REVIEW", "Eligibility Review"
        CREDIT_INVESTIGATION = "CREDIT_INVESTIGATION", "Credit Investigation"
        COMMITTEE_VOTE = "COMMITTEE_VOTE", "Committee Vote"
        COMMITTEE_FINALIZED = "COMMITTEE_FINALIZED", "Committee Finalized"
        INSURANCE_ENROLLED = "INSURANCE_ENROLLED", "Insurance Enrolled"
        DOCUMENTATION_SIGNED = "DOCUMENTATION_SIGNED", "Documentation Signed"
        SIGNED_HARD_COPY_UPLOADED = "SIGNED_HARD_COPY_UPLOADED", "Signed Hard Copy Uploaded"
        DISBURSEMENT = "DISBURSEMENT", "Disbursement"
        PAYMENT_OPTION = "PAYMENT_OPTION", "Payment Option Selected"
        PAYMENT_RECORDED = "PAYMENT_RECORDED", "Payment Recorded"
        DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED", "Document Uploaded"
        STEP_ACCESS_BLOCKED = "STEP_ACCESS_BLOCKED", "Blocked Step Access"
        SECURITY_ACTION_BLOCKED = "SECURITY_ACTION_BLOCKED", "Blocked Security Action"
        NOTIFICATION_SENT = "NOTIFICATION_SENT", "Notification Sent"

    application = models.ForeignKey(
        LoanApplication,
        on_delete=models.CASCADE,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=40, choices=Action.choices, db_index=True)
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="loan_audit_entries",
    )
    actor_label = models.CharField(max_length=200)
    description = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Loan Application Audit Log"
        verbose_name_plural = "Loan Application Audit Logs"
        indexes = [
            models.Index(fields=["application", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.get_action_display()} on {self.application_id} at {self.created_at:%Y-%m-%d %H:%M}"
