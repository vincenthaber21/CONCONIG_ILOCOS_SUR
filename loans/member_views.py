"""Member-facing loan request helpers and views.

Members reach these from /user-choice/ (not the staff dashboard). Works for
Django-authenticated users and RFID/PIN session-only members.
"""

from functools import wraps
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django_fsm import TransitionNotAllowed

from helper.login_helper import is_cashier_or_admin, member_or_login_required
from members.models import Member

from . import forms, models, services
from .audit import record_loan_audit

User = get_user_model()

# Terminal statuses — member may submit a new request after these.
_TERMINAL_STATUSES = (
    models.LoanApplication.Status.VERIFICATION_FAILED,
    models.LoanApplication.Status.REJECTED,
    models.LoanApplication.Status.FULLY_PAID,
    models.LoanApplication.Status.CLOSED,
)

# Statuses at/after committee approval — payment plan & interest details may show.
_APPROVED_OR_LATER = (
    models.LoanApplication.Status.APPROVED,
    models.LoanApplication.Status.INSURANCE_ENROLLED,
    models.LoanApplication.Status.DOCUMENTATION_SIGNED,
    models.LoanApplication.Status.DISBURSED,
    models.LoanApplication.Status.ACTIVE,
    models.LoanApplication.Status.FULLY_PAID,
    models.LoanApplication.Status.CLOSED,
)

# Member-facing origination pipeline (same order as staff, member-friendly labels).
_MEMBER_PIPELINE = (
    ("SUBMITTED", "Submitted"),
    ("UNDER_VERIFICATION", "Eligibility"),
    ("UNDER_INVESTIGATION", "Credit check"),
    ("PENDING_COMMITTEE_APPROVAL", "Committee"),
    ("APPROVED", "Approved"),
    ("INSURANCE_ENROLLED", "Insurance"),
    ("DOCUMENTATION_SIGNED", "Documents"),
    ("DISBURSED", "Funds released"),
    ("ACTIVE", "Repayment"),
    ("FULLY_PAID", "Fully paid"),
    ("CLOSED", "Closed"),
)

_STATUS_TO_PIPELINE_KEY = {
    "DRAFT": "SUBMITTED",
    "SUBMITTED": "SUBMITTED",
    "UNDER_VERIFICATION": "UNDER_VERIFICATION",
    "VERIFICATION_FAILED": "UNDER_VERIFICATION",
    "UNDER_INVESTIGATION": "UNDER_INVESTIGATION",
    "PENDING_COMMITTEE_APPROVAL": "PENDING_COMMITTEE_APPROVAL",
    "APPROVED": "APPROVED",
    "REJECTED": "PENDING_COMMITTEE_APPROVAL",
    "INSURANCE_ENROLLED": "INSURANCE_ENROLLED",
    "DOCUMENTATION_SIGNED": "DOCUMENTATION_SIGNED",
    "DISBURSED": "DISBURSED",
    "ACTIVE": "ACTIVE",
    "FULLY_PAID": "FULLY_PAID",
    "CLOSED": "CLOSED",
}

_HIDDEN_MEMBER_AUDIT_ACTIONS = frozenset(
    {
        models.LoanApplicationAuditLog.Action.STEP_ACCESS_BLOCKED,
        models.LoanApplicationAuditLog.Action.SECURITY_ACTION_BLOCKED,
        models.LoanApplicationAuditLog.Action.COMMITTEE_VOTE,
    }
)


def _related_or_none(instance, name):
    """Return a reverse OneToOne, or None when the related row does not exist."""
    try:
        return getattr(instance, name)
    except ObjectDoesNotExist:
        return None


def _display_fact(value):
    """Format a process-stage fact for member templates."""
    if value is None or value == "":
        return "—"
    if hasattr(value, "hour"):
        try:
            if timezone.is_aware(value):
                value = timezone.localtime(value)
        except (ValueError, TypeError, OverflowError):
            pass
        return value.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")
    if hasattr(value, "year") and hasattr(value, "month"):
        return value.strftime("%b %d, %Y").replace(" 0", " ")
    return str(value)


def _member_pipeline_steps(application):
    """Build the same loan pipeline the staff desk uses, for member tracking."""
    requires_insurance = bool(
        getattr(getattr(application, "loan_product", None), "requires_insurance", False)
    )
    catalog = [
        step
        for step in _MEMBER_PIPELINE
        if requires_insurance or step[0] != "INSURANCE_ENROLLED"
    ]
    current_key = _STATUS_TO_PIPELINE_KEY.get(application.status, "SUBMITTED")
    if not requires_insurance and current_key == "INSURANCE_ENROLLED":
        current_key = "DOCUMENTATION_SIGNED"
    keys = [key for key, _label in catalog]
    try:
        current_index = keys.index(current_key)
    except ValueError:
        current_index = 0

    failed = application.status in {
        models.LoanApplication.Status.VERIFICATION_FAILED,
        models.LoanApplication.Status.REJECTED,
    }
    settled = application.status in {
        models.LoanApplication.Status.FULLY_PAID,
        models.LoanApplication.Status.CLOSED,
    }

    steps = []
    for index, (key, label) in enumerate(catalog):
        is_current = index == current_index
        is_done = index < current_index or (settled and is_current)
        steps.append(
            {
                "key": key,
                "label": label,
                "completed": is_done and not (failed and is_current),
                "current": is_current,
                "failed": is_current and failed,
                "waiting": index > current_index,
                "skipped": False,
            }
        )
    return steps


def _member_status_guidance(application, requires_insurance=False):
    """Plain-language 'where you are / what happens next' copy for members."""
    Status = models.LoanApplication.Status
    mapping = {
        Status.DRAFT: (
            "info",
            "Saved as draft",
            "This request is not yet in the staff review queue. Please contact the cooperative office if you already submitted it.",
            "No action needed from you right now.",
        ),
        Status.SUBMITTED: (
            "info",
            "Request received",
            "Staff have your loan request. Next they will verify your membership and the documents you uploaded.",
            "Please wait. You will see the next step here as soon as staff begin eligibility verification.",
        ),
        Status.UNDER_VERIFICATION: (
            "info",
            "Eligibility check in progress",
            "Staff are confirming that your membership period and supporting documents meet cooperative requirements.",
            "Please wait. You do not need to resubmit unless staff contact you.",
        ),
        Status.VERIFICATION_FAILED: (
            "danger",
            "Did not pass verification",
            "Staff could not verify eligibility or the required documents for this request.",
            "Please visit the cooperative office for details. You may submit a new request after the issues are resolved.",
        ),
        Status.UNDER_INVESTIGATION: (
            "info",
            "Credit investigation in progress",
            "Your documents passed verification. A credit officer is now reviewing repayment capacity and loan purpose.",
            "Please wait. The credit committee reviews the application after this step.",
        ),
        Status.PENDING_COMMITTEE_APPROVAL: (
            "info",
            "With the credit committee",
            "Credit investigation is complete. Authorized approvers are now deciding on your loan.",
            "Please wait for the committee decision. You will see Approved or Rejected here once it is recorded.",
        ),
        Status.APPROVED: (
            "ok",
            "Your loan is approved",
            (
                "The credit committee approved this loan. Staff will enroll required insurance next, then prepare the loan agreement for signing."
                if requires_insurance
                else "The credit committee approved this loan. Staff will prepare the loan agreement for you to sign next."
            ),
            "Please be ready to visit the office to sign the loan agreement when staff ask you to.",
        ),
        Status.REJECTED: (
            "danger",
            "Application was not approved",
            "The credit committee did not approve this loan request.",
            "Please contact the cooperative office if you have questions. You may apply again after this request is closed.",
        ),
        Status.INSURANCE_ENROLLED: (
            "ok",
            "Insurance enrolled",
            "Required credit insurance has been enrolled for this loan. Documentation and signing is next.",
            "Please be ready to sign the loan agreement at the cooperative office.",
        ),
        Status.DOCUMENTATION_SIGNED: (
            "ok",
            "Documents signed",
            "The loan agreement is on file. Staff can now release the loan proceeds.",
            "Please wait for disbursement. You will see the amount and method here once funds are released.",
        ),
        Status.DISBURSED: (
            "ok",
            "Funds released",
            "The loan amount has been released. Your monthly repayment schedule is now in effect.",
            "Pay each installment on or before the due date at the cooperative office.",
        ),
        Status.ACTIVE: (
            "ok",
            "Loan is active — repayment",
            "Funds have been released and this loan is in repayment. Interest is charged only when a due date is missed after the grace period.",
            "Pay on time at the cooperative office and keep your official receipts.",
        ),
        Status.FULLY_PAID: (
            "ok",
            "Fully paid",
            "All amounts due on this loan have been settled. Thank you for completing repayment.",
            "Staff may issue a clearance record and close the account.",
        ),
        Status.CLOSED: (
            "ok",
            "Loan account closed",
            "This loan is closed. Collateral, if any, has been released and a clearance record is on file.",
            "Keep this page as confirmation of settlement.",
        ),
    }
    tone, title, body, next_step = mapping.get(
        application.status,
        (
            "info",
            application.get_status_display(),
            "Your loan application is being processed.",
            "Please wait for the next staff update.",
        ),
    )
    return {"tone": tone, "title": title, "body": body, "next_step": next_step}


def _member_process_stages(application, pipeline_steps):
    """Stage cards with dates and facts so members can see what already happened."""
    eligibility = _related_or_none(application, "eligibility_verification")
    investigation = _related_or_none(application, "credit_investigation")
    committee = _related_or_none(application, "committee_review")
    insurance = _related_or_none(application, "insurance_enrollment")
    documentation = _related_or_none(application, "documentation")
    disbursement = _related_or_none(application, "disbursement")
    committee_votes = None
    if application.status == models.LoanApplication.Status.PENDING_COMMITTEE_APPROVAL:
        committee_votes = services.committee_approval_status(application)

    facts_by_key = {
        "SUBMITTED": [
            ("Submitted", application.submitted_at or application.created_at),
            ("Amount", f"₱{application.amount_requested:,.2f}"),
            ("Term", f"{application.term_months} months"),
        ],
        "UNDER_VERIFICATION": [],
        "UNDER_INVESTIGATION": [],
        "PENDING_COMMITTEE_APPROVAL": [],
        "APPROVED": [],
        "INSURANCE_ENROLLED": [],
        "DOCUMENTATION_SIGNED": [],
        "DISBURSED": [],
        "ACTIVE": [],
        "FULLY_PAID": [],
        "CLOSED": [],
    }

    if eligibility:
        facts_by_key["UNDER_VERIFICATION"] = [
            ("Membership", "Met" if eligibility.membership_status_ok else "Not met"),
            ("Documents", "Complete" if eligibility.documents_complete else "Incomplete"),
            ("Result", "Passed" if eligibility.passed else "Did not pass"),
            ("Checked", eligibility.verified_at),
        ]
        if eligibility.remarks and application.status == models.LoanApplication.Status.VERIFICATION_FAILED:
            facts_by_key["UNDER_VERIFICATION"].append(("Notes", eligibility.remarks))

    if investigation and application.status not in {
        models.LoanApplication.Status.SUBMITTED,
        models.LoanApplication.Status.UNDER_VERIFICATION,
        models.LoanApplication.Status.VERIFICATION_FAILED,
    }:
        facts_by_key["UNDER_INVESTIGATION"] = [
            ("Recommendation", investigation.get_recommendation_display()),
            ("Evaluated", investigation.evaluated_at),
        ]

    if committee_votes and application.status == models.LoanApplication.Status.PENDING_COMMITTEE_APPROVAL:
        if committee_votes.get("single_approver"):
            vote_label = (
                f"{committee_votes['total_approved']} of {committee_votes['votes_needed']} "
                f"approval{'' if committee_votes['votes_needed'] == 1 else 's'}"
            )
        else:
            vote_label = (
                f"{committee_votes['total_approved']} of {committee_votes['votes_needed']} "
                "needed for majority"
            )
        facts_by_key["PENDING_COMMITTEE_APPROVAL"] = [
            ("Approvals recorded", vote_label),
        ]
    if committee:
        facts_by_key["PENDING_COMMITTEE_APPROVAL"] = [
            ("Decision", committee.get_decision_display()),
            ("Decided", committee.decision_date),
        ]
        if committee.remarks:
            facts_by_key["PENDING_COMMITTEE_APPROVAL"].append(("Notes", committee.remarks))
        if committee.decision == models.CommitteeReview.Decision.APPROVED:
            facts_by_key["APPROVED"] = [
                ("Approved on", committee.decision_date),
            ]

    if insurance:
        facts_by_key["INSURANCE_ENROLLED"] = [
            ("Cover", insurance.get_insurance_type_display()),
            ("Premium", f"₱{insurance.premium_amount:,.2f}"),
            ("Payment", insurance.get_payment_mode_display()),
            ("Enrolled", insurance.enrolled_at),
        ]

    if documentation:
        if documentation.signing_method == models.LoanDocumentation.SigningMethod.HARD_COPY and documentation.signed_hard_copy:
            sign_status = "Hard copy on file"
        elif documentation.signed_by_borrower_at and documentation.signed_by_authorized_personnel_at:
            sign_status = "Fully signed"
        elif documentation.signed_by_borrower_at or documentation.signed_by_authorized_personnel_at:
            sign_status = "Partially signed"
        else:
            sign_status = "Awaiting signatures"
        facts_by_key["DOCUMENTATION_SIGNED"] = [
            ("Signatures", sign_status),
            ("You signed", documentation.signed_by_borrower_at or "Not yet"),
            ("Cooperative signed", documentation.signed_by_authorized_personnel_at or "Not yet"),
            ("Method", documentation.get_signing_method_display()),
        ]

    if disbursement:
        facts_by_key["DISBURSED"] = [
            ("Loan principal", f"₱{application.amount_requested:,.2f}"),
            ("Net amount released", f"₱{disbursement.amount_released:,.2f}"),
        ]
        if disbursement.transaction_fee and disbursement.transaction_fee > 0:
            facts_by_key["DISBURSED"].append(
                ("Transaction fee", f"₱{disbursement.transaction_fee:,.2f}")
            )
        if (
            disbursement.other_deduction_amount
            and disbursement.other_deduction_amount > 0
        ):
            label = disbursement.other_deduction_label or "Other deduction"
            facts_by_key["DISBURSED"].append(
                (label, f"₱{disbursement.other_deduction_amount:,.2f}")
            )
        facts_by_key["DISBURSED"].extend(
            [
                ("Method", disbursement.get_disbursement_method_display()),
                ("Released", disbursement.disbursement_date),
                ("Reference", disbursement.reference_number or "—"),
            ]
        )
        facts_by_key["ACTIVE"] = [
            ("Repayment started", disbursement.disbursement_date),
            ("Term", f"{application.term_months} months"),
        ]

    if application.status == models.LoanApplication.Status.FULLY_PAID:
        facts_by_key["FULLY_PAID"] = [("Settled", "All amounts due have been paid")]
    if application.status == models.LoanApplication.Status.CLOSED:
        facts_by_key["CLOSED"] = [("Account", "Closed and cleared")]

    descriptions = {
        "SUBMITTED": "Your request and supporting images were received by the cooperative.",
        "UNDER_VERIFICATION": "Staff confirm membership eligibility and that required documents are complete.",
        "UNDER_INVESTIGATION": "A credit officer reviews repayment capacity and the purpose of this loan.",
        "PENDING_COMMITTEE_APPROVAL": "Authorized approvers vote to approve or reject the application.",
        "APPROVED": "Committee approval is recorded. Insurance (if required) and documentation follow.",
        "INSURANCE_ENROLLED": "Required credit-life cover is enrolled before documents are signed.",
        "DOCUMENTATION_SIGNED": "You and authorized personnel sign the loan agreement.",
        "DISBURSED": "The approved amount is released to you.",
        "ACTIVE": "You repay on the monthly schedule. Pay on time to avoid late interest.",
        "FULLY_PAID": "The loan balance is settled.",
        "CLOSED": "The account is closed and any collateral is released.",
    }

    stages = []
    for step in pipeline_steps:
        key = step["key"]
        if step["failed"]:
            state = "failed"
        elif step["completed"]:
            state = "done"
        elif step["current"]:
            state = "current"
        else:
            state = "waiting"
        stages.append(
            {
                **step,
                "state": state,
                "description": descriptions.get(key, ""),
                "facts": [
                    (label, _display_fact(value))
                    for label, value in (facts_by_key.get(key) or [])
                ],
            }
        )
    return stages


def _member_activity_logs(application):
    """Status history members may see — no blocked-access or vote internals."""
    return list(
        application.audit_logs.select_related("actor")
        .exclude(action__in=_HIDDEN_MEMBER_AUDIT_ACTIONS)[:80]
    )


def _get_open_applications(loan_user):
    """Return all non-terminal loan applications for this member."""
    return (
        models.LoanApplication.objects.filter(member=loan_user)
        .exclude(status__in=_TERMINAL_STATUSES)
        .select_related("loan_product")
        .order_by("-created_at")
    )


def _get_open_application(loan_user):
    """Return the member's latest non-terminal loan application, if any."""
    return _get_open_applications(loan_user).first()


def _get_open_application_for_product(loan_user, loan_product):
    """Return an ongoing application for the same loan product, if any."""
    product_id = getattr(loan_product, "pk", loan_product)
    return _get_open_applications(loan_user).filter(loan_product_id=product_id).first()


def _get_blocked_product_ids(loan_user):
    """Loan product IDs that already have an ongoing application for this member."""
    return set(_get_open_applications(loan_user).values_list("loan_product_id", flat=True))


def member_blocked_loan_products(loan_user):
    """Blocked products with labels for staff/member loan forms."""
    blocked = []
    for application in _get_open_applications(loan_user):
        blocked.append(
            {
                "product_id": str(application.loan_product_id),
                "product_name": application.loan_product.name,
                "status": application.get_status_display(),
                "application_pk": str(application.pk),
            }
        )
    return blocked


def _loan_request_eligibility(loan_user, loan_member, open_application=None, loan_product=None):
    """Whether this member may start a new loan request right now."""
    waiting = services.member_loan_waiting_period(loan_member, user=loan_user)
    if loan_product is not None:
        product_blocked = _get_open_application_for_product(loan_user, loan_product) is not None
        can_request = waiting["allowed"] and not product_blocked
    else:
        blocked_ids = _get_blocked_product_ids(loan_user)
        product_ids = models.LoanProduct.objects.values_list("pk", flat=True)
        has_available_product = any(product_id not in blocked_ids for product_id in product_ids)
        can_request = waiting["allowed"] and has_available_product
    return can_request, waiting


def _get_active_member(request):
    """Return the Member for this request, or None."""
    if request.user.is_authenticated:
        try:
            return Member.objects.get(user=request.user, is_active=True)
        except (Member.DoesNotExist, Member.MultipleObjectsReturned):
            pass
    member_id = request.session.get("member_id")
    if member_id:
        try:
            return Member.objects.get(id=member_id, is_active=True)
        except Member.DoesNotExist:
            return None
    return None


def ensure_member_user(member):
    """Return a Django User for loan FKs, creating one if the member has none."""
    if member is None:
        return None
    if member.user_id:
        return member.user

    base_username = (member.username or f"member{member.id}").strip() or f"member{member.id}"
    username = base_username[:140]
    if User.objects.filter(username=username).exclude(pk=getattr(member.user, "pk", None)).exists():
        username = f"m{member.id}_{username}"[:150]

    user = User(
        username=username,
        first_name=member.first_name or "",
        last_name=member.last_name or "",
        email=member.email or "",
        is_active=True,
    )
    user.set_unusable_password()
    user.save()
    member.user = user
    member.save(update_fields=["user"])
    return user


def ensure_loan_user(request):
    """
    Resolve a Django User for loan FKs.

    Session-only members get a linked inactive-login User created on demand so
    LoanApplication.member (auth.User) can be filled.
    """
    if request.user.is_authenticated:
        return request.user, _get_active_member(request)

    member = _get_active_member(request)
    if member is None:
        return None, None
    return ensure_member_user(member), member


def member_loan_required(view_func):
    """Allow members; send cashiers/admins to the staff loans desk."""

    @wraps(view_func)
    @member_or_login_required
    def _wrapped(request, *args, **kwargs):
        if request.user.is_authenticated and is_cashier_or_admin(request.user):
            return redirect("loans_overview")
        user, member = ensure_loan_user(request)
        if user is None:
            messages.warning(request, "Please log in to request a loan.")
            return redirect("root_login")
        request.loan_user = user
        request.loan_member = member
        return view_func(request, *args, **kwargs)

    return _wrapped


@member_loan_required
def member_loan_list(request):
    """List this member's applications, products, and complete payment history."""
    applications = list(
        models.LoanApplication.objects.filter(member=request.loan_user)
        .select_related("loan_product")
        .order_by("-created_at")
    )
    for application in applications:
        application.pipeline_steps = _member_pipeline_steps(application)
        application.current_pipeline_step = next(
            (step["label"] for step in application.pipeline_steps if step["current"]),
            application.get_status_display(),
        )
        if application.status in _APPROVED_OR_LATER:
            plan = services.estimate_payment_schedule(
                application.amount_requested,
                application.effective_interest_rate(),
                application.term_months,
                application.loan_product.interest_start_month,
            )
            application.monthly_payment = plan["monthly_payment"]
            application.total_payment = plan["total_payment"]
            application.total_interest = plan["total_interest"]
            application.show_loan_financials = True
        else:
            application.monthly_payment = None
            application.total_payment = None
            application.total_interest = None
            application.show_loan_financials = False
    payments = (
        models.Payment.objects.filter(application__member=request.loan_user)
        .select_related(
            "application",
            "application__loan_product",
            "applied_to_installment",
        )
        .order_by("-payment_date")
    )
    total_paid = payments.aggregate(total=Sum("amount_paid"))["total"] or 0
    products = models.LoanProduct.objects.all().order_by("name")
    open_application = _get_open_application(request.loan_user)
    open_applications = list(_get_open_applications(request.loan_user))
    for application in open_applications:
        application.current_pipeline_step = next(
            (step["label"] for step in _member_pipeline_steps(application) if step["current"]),
            application.get_status_display(),
        )
    blocked_product_ids = _get_blocked_product_ids(request.loan_user)
    can_request_loan, waiting = _loan_request_eligibility(
        request.loan_user, request.loan_member
    )
    display_name = (
        request.loan_member.full_name
        if request.loan_member
        else (request.loan_user.get_full_name() or request.loan_user.username)
    )
    return render(
        request,
        "loans/member/loan_list.html",
        {
            "applications": applications,
            "payments": payments,
            "total_paid": total_paid,
            "products": products,
            "display_name": display_name,
            "member": request.loan_member,
            "open_application": open_application,
            "open_applications": open_applications,
            "blocked_product_ids": blocked_product_ids,
            "can_request_loan": can_request_loan,
            "loan_waiting": waiting,
        },
    )


_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".jfif")
_DOCUMENT_EXTENSIONS = (
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".csv",
    ".txt",
    ".rtf",
    ".odt",
    ".ods",
    ".ppt",
    ".pptx",
)
_SUPPORTING_EXTENSIONS = _IMAGE_EXTENSIONS + _DOCUMENT_EXTENSIONS
_DOCUMENT_CONTENT_TYPES = (
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/rtf",
    "text/plain",
    "text/csv",
    "text/rtf",
)


def _is_image_upload(uploaded_file):
    """True if the uploaded file looks like an image by content type or extension."""
    content_type = (getattr(uploaded_file, "content_type", "") or "").lower()
    if content_type.startswith("image/"):
        return True
    name = (getattr(uploaded_file, "name", "") or "").lower()
    return name.endswith(_IMAGE_EXTENSIONS)


def _is_supporting_upload(uploaded_file):
    """True if the file is an allowed supporting image or document."""
    if _is_image_upload(uploaded_file):
        return True
    content_type = (getattr(uploaded_file, "content_type", "") or "").lower()
    if content_type in _DOCUMENT_CONTENT_TYPES:
        return True
    name = (getattr(uploaded_file, "name", "") or "").lower()
    return name.endswith(_DOCUMENT_EXTENSIONS)


@member_loan_required
def member_loan_request(request):
    """Submit a new loan application (member self-service).

    Members may hold one ongoing application per loan product. Duplicate
    requests for the same product are blocked; other products stay available.
    At least one supporting file upload (image or document) is required.
    """
    _can_request, waiting = _loan_request_eligibility(
        request.loan_user, request.loan_member
    )
    if not waiting["allowed"]:
        messages.warning(request, waiting["message"])
        return redirect("member_loan_list")
    if not _can_request:
        messages.info(
            request,
            "You already have ongoing loans for every available loan product. "
            "Track them below — you can apply again after one is closed, rejected, or fully paid.",
        )
        return redirect("member_loan_list")

    products = models.LoanProduct.objects.all().order_by("name")
    if not products.exists():
        messages.warning(
            request,
            "No loan products are available yet. Please contact the cooperative office.",
        )
        return redirect("member_loan_list")

    blocked_products = member_blocked_loan_products(request.loan_user)
    documents_error = ""

    if request.method == "POST":
        form = forms.LoanApplicationForm(request.POST)
        loan_product = form.data.get("loan_product")
        if loan_product:
            open_application = _get_open_application_for_product(
                request.loan_user, loan_product
            )
            if open_application is not None:
                messages.info(
                    request,
                    f"You already have an ongoing {open_application.loan_product.name} loan request. "
                    "Choose a different loan product or track the existing one.",
                )
                return redirect("member_loan_detail", pk=open_application.pk)

        _can_request, waiting = _loan_request_eligibility(
            request.loan_user,
            request.loan_member,
            loan_product=loan_product,
        )
        if not waiting["allowed"]:
            messages.warning(request, waiting["message"])
            return redirect("member_loan_list")
        if not _can_request:
            messages.info(
                request,
                "That loan product already has an ongoing request for your account.",
            )
            return redirect("member_loan_list")

        uploaded_files = request.FILES.getlist("documents")
        supporting_files = [f for f in uploaded_files if _is_supporting_upload(f)]

        if not uploaded_files:
            documents_error = "Please upload at least one supporting file."
        elif not supporting_files:
            documents_error = (
                "Only images and common documents are accepted "
                "(JPG, PNG, PDF, DOC, DOCX, XLS, XLSX, and similar)."
            )

        if form.is_valid() and not documents_error:
            application = form.save(commit=False)
            application.member = request.loan_user
            application.save()

            record_loan_audit(
                application,
                models.LoanApplicationAuditLog.Action.APPLICATION_CREATED,
                actor=request.loan_user,
                description=(
                    f"Member loan request created for {application.loan_product.name} "
                    f"(₱{application.amount_requested:,.2f}, {application.term_months} months)."
                ),
                metadata={
                    "loan_product_id": str(application.loan_product_id),
                    "amount_requested": str(application.amount_requested),
                    "interest_rate": str(application.interest_rate),
                    "term_months": application.term_months,
                    "channel": "member_portal",
                },
                request=request,
            )

            for uploaded_file in supporting_files:
                doc = models.SubmittedDocument.objects.create(
                    application=application,
                    document_type=uploaded_file.name,
                    file=uploaded_file,
                )
                record_loan_audit(
                    application,
                    models.LoanApplicationAuditLog.Action.DOCUMENT_UPLOADED,
                    actor=request.loan_user,
                    description=f"Supporting document uploaded: {uploaded_file.name}.",
                    metadata={
                        "document_id": doc.pk,
                        "document_type": uploaded_file.name,
                        "channel": "member_portal",
                    },
                    request=request,
                )

            try:
                application.submit()
                application.save(update_fields=["status", "submitted_at"])
                record_loan_audit(
                    application,
                    models.LoanApplicationAuditLog.Action.APPLICATION_SUBMITTED,
                    actor=request.loan_user,
                    description="Member submitted loan request for staff review.",
                    metadata={
                        "submitted_at": application.submitted_at.isoformat(),
                        "channel": "member_portal",
                    },
                    request=request,
                )
                messages.success(
                    request,
                    "Your loan request was submitted. Staff will review your application.",
                )
            except TransitionNotAllowed:
                messages.warning(request, "Application saved as draft. Please contact staff.")
            return redirect("member_loan_detail", pk=application.pk)
    else:
        initial = {}
        product_id = request.GET.get("product")
        if product_id:
            initial["loan_product"] = product_id
        form = forms.LoanApplicationForm(initial=initial)

    display_name = (
        request.loan_member.full_name
        if request.loan_member
        else (request.loan_user.get_full_name() or request.loan_user.username)
    )
    product_limits = {
        str(product.pk): {
            "name": product.name,
            "min_amount": str(product.min_amount),
            "max_amount": str(product.max_amount),
            "term_months": product.term_months,
            "interest_rate": str(product.interest_rate),
            "interest_start_month": product.interest_start_month,
        }
        for product in products
    }
    return render(
        request,
        "loans/member/loan_request.html",
        {
            "form": form,
            "products": products,
            "product_limits_json": product_limits,
            "blocked_products_json": blocked_products,
            "display_name": display_name,
            "member": request.loan_member,
            "documents_error": documents_error,
        },
    )


@member_loan_required
def member_loan_detail(request, pk):
    """Read-only status page for the member's own application."""
    application = get_object_or_404(
        models.LoanApplication.objects.select_related(
            "loan_product",
            "eligibility_verification",
            "credit_investigation",
            "committee_review",
            "insurance_enrollment",
            "documentation",
            "disbursement",
        ),
        pk=pk,
        member=request.loan_user,
    )
    documents = application.submitted_documents.all()
    payments = application.payments.select_related("applied_to_installment").all()
    can_request_loan, waiting = _loan_request_eligibility(
        request.loan_user, request.loan_member
    )
    show_loan_financials = application.status in _APPROVED_OR_LATER
    requires_insurance = bool(application.loan_product.requires_insurance)
    pipeline_steps = _member_pipeline_steps(application)
    process_stages = _member_process_stages(application, pipeline_steps)
    status_guidance = _member_status_guidance(application, requires_insurance)
    documentation = _related_or_none(application, "documentation")
    contract = None
    show_contract = application.status in _APPROVED_OR_LATER
    if show_contract:
        contract = services.build_loan_agreement_context(application)
    activity_logs = _member_activity_logs(application)
    collaterals = list(application.collaterals.all())

    payment_plan = None
    plan_is_estimate = False
    outstanding_balance = Decimal("0.00")
    total_obligation = Decimal("0.00")
    interest_rate = Decimal(application.effective_interest_rate() or 0)
    # Monthly decimal rate from DB (e.g. 0.015), same as staff payments.
    monthly_interest_rate = interest_rate.quantize(Decimal("0.0001"))
    interest_breakdown = application.interest_balance_breakdown()
    interest_charged_so_far = Decimal(interest_breakdown.get("interest") or 0)
    uses_period_interest = interest_rate > 0 or interest_charged_so_far > 0

    # Payment plan / interest details only after admin (committee) approval.
    if show_loan_financials:
        total_paid = application.total_paid_amount()
        total_obligation = application.total_obligation_amount()
        outstanding_balance = application.total_outstanding_balance()
        interest_charged_so_far = Decimal(application.recorded_period_interest() or 0)
        interest_breakdown = application.interest_balance_breakdown()

        # Prefer the real amortization schedule when present; otherwise estimate.
        if application.amortization_schedules.exists():
            services.refresh_schedule_interest(application)

        schedule_rows = list(application.amortization_schedules.order_by("installment_number"))
        if schedule_rows:
            payment_plan = {
                "rows": [
                    {
                        "month": row.installment_number,
                        "principal_due": row.principal_due,
                        "interest_due": row.interest_due,
                        "total_due": row.total_due,
                        "has_interest": row.interest_due > 0,
                        "is_paid": row.is_paid,
                        "due_date": row.due_date,
                        "is_overdue": (not row.is_paid)
                        and services.is_installment_past_grace(row.due_date),
                    }
                    for row in schedule_rows
                ],
                "total_principal": sum((r.principal_due for r in schedule_rows), Decimal("0")),
                "total_interest": interest_charged_so_far,
                "total_payment": total_obligation,
                "term_months": application.term_months,
                "monthly_payment": (
                    (sum((r.principal_due for r in schedule_rows), Decimal("0")) / application.term_months).quantize(
                        Decimal("0.01")
                    )
                    if application.term_months
                    else Decimal("0.00")
                ),
                "late_interest_rate": application.effective_interest_rate(),
                "late_interest_from_month": application.loan_product.interest_start_month,
            }
            plan_is_estimate = False
        else:
            payment_plan = services.estimate_payment_schedule(
                application.amount_requested,
                application.effective_interest_rate(),
                application.term_months,
                application.loan_product.interest_start_month,
            )
            plan_is_estimate = True

        services.attach_missed_payment_costs(payment_plan)
        services.allocate_payments_to_schedule(payment_plan, total_paid)
        # Keep totals from the loan record (usable-days interest), not schedule-only math.
        payment_plan["total_interest"] = interest_charged_so_far
        payment_plan["total_if_on_time"] = total_obligation
        payment_plan["total_payment"] = total_obligation
    else:
        total_paid = Decimal("0.00")

    return render(
        request,
        "loans/member/loan_detail.html",
        {
            "application": application,
            "documents": documents,
            "payments": payments,
            "payment_plan": payment_plan,
            "plan_is_estimate": plan_is_estimate,
            "show_loan_financials": show_loan_financials,
            "outstanding_balance": outstanding_balance,
            "total_paid": total_paid,
            "total_obligation": total_obligation,
            "interest_breakdown": interest_breakdown,
            "uses_period_interest": uses_period_interest,
            "member": request.loan_member,
            "can_request_loan": can_request_loan,
            "loan_waiting": waiting,
            "interest_rate": interest_rate,
            "monthly_interest_rate": monthly_interest_rate,
            "interest_charged_so_far": interest_charged_so_far,
            "pipeline_steps": pipeline_steps,
            "process_stages": process_stages,
            "status_guidance": status_guidance,
            "documentation": documentation,
            "contract": contract,
            "show_contract": show_contract,
            "activity_logs": activity_logs,
            "collaterals": collaterals,
            "requires_insurance": requires_insurance,
        },
    )
