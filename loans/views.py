"""Class-based views implementing the loan origination pipeline.

Embedded in coop_kiosk: access is gated by the project's existing role
helpers (superuser / Django staff / Member roles admin|cashier|staff) via
``LoanStaffMixin`` rather than a separate custom User.role field.
"""

import base64
import uuid
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, View
from django.utils.decorators import method_decorator
from django_fsm import TransitionNotAllowed
from django.db import transaction as db_transaction

from helper.login_helper import (
    get_linked_member,
    is_admin_user,
    is_cashier_or_admin,
    is_committee_user,
    is_loan_officer_only_user,
    is_loan_officer_user,
)
from helper.receipt_helper import get_receipt_store_context

from . import forms, models, services
from .audit import record_loan_audit
from .member_views import (
    _get_open_application_for_product,
    _is_supporting_upload,
    _loan_request_eligibility,
    ensure_member_user,
    member_blocked_loan_products,
)


def _save_signature_data_url(field, data_url, prefix):
    """Decode a canvas data-URL and assign it to an ImageField."""
    if not data_url or not data_url.startswith("data:image"):
        return False
    try:
        header, encoded = data_url.split(",", 1)
    except ValueError:
        return False
    ext = "png"
    if "jpeg" in header or "jpg" in header:
        ext = "jpg"
    raw = base64.b64decode(encoded)
    filename = f"{prefix}_{uuid.uuid4().hex[:10]}.{ext}"
    field.save(filename, ContentFile(raw), save=False)
    return True


PIPELINE_STEPS = [
    ("DRAFT", "Application Draft"),
    ("SUBMITTED", "Submitted"),
    ("UNDER_VERIFICATION", "Eligibility Verification"),
    ("UNDER_INVESTIGATION", "Credit Investigation"),
    ("PENDING_COMMITTEE_APPROVAL", "Committee Review"),
    ("APPROVED", "Approved"),
    ("INSURANCE_ENROLLED", "Insurance Enrollment"),
    ("DOCUMENTATION_SIGNED", "Documentation Signed"),
    ("DISBURSED", "Disbursement"),
    ("ACTIVE", "Active / Repayment"),
    ("FULLY_PAID", "Fully Paid"),
    ("CLOSED", "Closed"),
]

# Ordered progression used to decide whether a step is still editable.
_STATUS_RANK = {
    "DRAFT": 0,
    "SUBMITTED": 1,
    "UNDER_VERIFICATION": 2,
    "VERIFICATION_FAILED": 2,  # terminal at verification stage
    "UNDER_INVESTIGATION": 3,
    "PENDING_COMMITTEE_APPROVAL": 4,
    "APPROVED": 5,
    "REJECTED": 5,  # terminal at committee stage
    "INSURANCE_ENROLLED": 6,
    "DOCUMENTATION_SIGNED": 7,
    "DISBURSED": 8,
    "ACTIVE": 9,
    "FULLY_PAID": 10,
    "CLOSED": 11,
}


def _status_rank(status):
    return _STATUS_RANK.get(status, -1)


def _pipeline_action_state(application, action_key):
    """Return open / locked / pending for a pipeline action.

    Once a step has been completed (application moved past it), it is locked
    so staff cannot edit that process again.
    """
    Status = models.LoanApplication.Status
    status = application.status
    rank = _status_rank(status)
    requires_insurance = bool(
        getattr(getattr(application, "loan_product", None), "requires_insurance", False)
    )

    rules = {
        "eligibility": {
            "open_statuses": {Status.SUBMITTED, Status.UNDER_VERIFICATION},
            "done_after_rank": 2,  # locked once past verification stage
            "label": "Eligibility",
        },
        "credit": {
            "open_statuses": {Status.UNDER_INVESTIGATION},
            "done_after_rank": 3,
            "label": "Credit investigation",
        },
        "committee": {
            "open_statuses": {Status.PENDING_COMMITTEE_APPROVAL},
            "done_after_rank": 4,
            "label": "Committee review",
        },
        "insurance": {
            "open_statuses": {Status.APPROVED} if requires_insurance else set(),
            "done_after_rank": 5 if requires_insurance else -1,
            "label": "Insurance",
            "skipped": not requires_insurance,
        },
        "documentation": {
            "open_statuses": (
                {Status.INSURANCE_ENROLLED}
                if requires_insurance
                else {Status.APPROVED, Status.INSURANCE_ENROLLED}
            ),
            "done_after_rank": 6,
            "label": "Documentation",
        },
        "disbursement": {
            "open_statuses": {Status.DOCUMENTATION_SIGNED},
            "done_after_rank": 7,
            "label": "Disbursement",
        },
        "payment_collect": {
            "open_statuses": {Status.DISBURSED, Status.ACTIVE},
            "done_after_rank": 9,
            "label": "Collect payment",
        },
    }

    rule = rules.get(action_key)
    if not rule:
        return {"key": action_key, "state": "locked", "reason": "Unknown action."}

    if rule.get("skipped"):
        return {
            "key": action_key,
            "state": "locked",
            "reason": "Not required for this loan product.",
            "label": rule["label"],
        }

    if status in rule["open_statuses"]:
        return {
            "key": action_key,
            "state": "open",
            "reason": "",
            "label": rule["label"],
        }

    done_after = rule["done_after_rank"]
    if done_after >= 0 and rank > done_after:
        return {
            "key": action_key,
            "state": "locked",
            "reason": "Completed and locked for security. Editing is not allowed.",
            "label": rule["label"],
        }

    # Special terminals
    if status == Status.VERIFICATION_FAILED and action_key == "eligibility":
        return {
            "key": action_key,
            "state": "locked",
            "reason": "Verification already failed and locked.",
            "label": rule["label"],
        }
    if status == Status.REJECTED and action_key == "committee":
        return {
            "key": action_key,
            "state": "locked",
            "reason": "Application already rejected and locked.",
            "label": rule["label"],
        }

    return {
        "key": action_key,
        "state": "pending",
        "reason": "Not available yet — complete earlier steps first.",
        "label": rule["label"],
    }


def _pipeline_actions_for(application):
    """Build staff pipeline action cards with lock state."""
    pk = application.pk
    specs = [
        ("eligibility", "loans:eligibility-verify", "bi-shield-check"),
        ("credit", "loans:credit-investigate", "bi-search"),
        ("committee", "loans:committee-review", "bi-people"),
        ("insurance", "loans:insurance-enroll", "bi-heart-pulse"),
        ("documentation", "loans:documentation-sign", "bi-pen"),
        ("disbursement", "loans:disburse", "bi-cash-stack"),
        ("payment_collect", "loans:payment-collect", "bi-receipt"),
    ]
    actions = []
    for key, url_name, icon in specs:
        info = _pipeline_action_state(application, key)
        actions.append(
            {
                **info,
                "url": reverse(url_name, kwargs={"pk": pk}),
                "icon": icon,
                "is_open": info["state"] == "open",
                "is_locked": info["state"] == "locked",
                "is_pending": info["state"] == "pending",
            }
        )
    return actions


class PipelineStepLockMixin:
    """Block access to pipeline steps that are already completed/locked."""

    pipeline_action_key = None

    def dispatch(self, request, *args, **kwargs):
        if self.pipeline_action_key and "pk" in kwargs:
            application = get_object_or_404(models.LoanApplication, pk=kwargs["pk"])
            info = _pipeline_action_state(application, self.pipeline_action_key)
            if info["state"] != "open":
                record_loan_audit(
                    application,
                    models.LoanApplicationAuditLog.Action.STEP_ACCESS_BLOCKED,
                    actor=request.user if request.user.is_authenticated else None,
                    description=(
                        f"Blocked access to pipeline step “{info.get('label', self.pipeline_action_key)}”: "
                        f"{info['reason'] or 'step is locked'}."
                    ),
                    metadata={
                        "step": self.pipeline_action_key,
                        "state": info["state"],
                        "application_status": application.status,
                    },
                    request=request,
                )
                messages.warning(
                    request,
                    info["reason"]
                    or (
                        f"{info.get('label', 'This step')} is locked and cannot "
                        "be edited for security."
                    ),
                )
                return redirect("loans:application-detail", pk=application.pk)
        return super().dispatch(request, *args, **kwargs)


def _is_loan_staff(user):
    """Loan-pipeline staff: dashboard staff, loan officers, or superuser."""
    return bool(
        user
        and user.is_authenticated
        and (
            user.is_superuser
            or is_cashier_or_admin(user)
            or is_loan_officer_only_user(user)
        )
    )


def _staff_approver_label(user):
    member = get_linked_member(user)
    if member:
        return member.full_name
    name = user.get_full_name().strip()
    return name or user.username


def _is_loan_committee(user):
    """Credit committee members who may approve or reject pending loan applications."""
    return bool(user and user.is_authenticated and is_committee_user(user))


def _can_access_loans(user):
    """Full loan staff or credit-committee members (read/review access)."""
    return bool(user and user.is_authenticated and (_is_loan_staff(user) or _is_loan_committee(user)))


_COMMITTEE_PIPELINE_KEYS = frozenset({"committee", "payment_collect"})


def _pipeline_actions_for_committee(application):
    """Committee members see review plus payment collection."""
    return [
        a for a in _pipeline_actions_for(application)
        if a.get("key") in _COMMITTEE_PIPELINE_KEYS
    ]


_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".jfif"}
_PDF_EXTENSIONS = {".pdf"}


def _document_preview_kind(file_field):
    """Return 'image', 'pdf', or 'file' for inline preview rendering."""
    name = (getattr(file_field, "name", "") or "").lower()
    for ext in _IMAGE_EXTENSIONS:
        if name.endswith(ext):
            return "image"
    for ext in _PDF_EXTENSIONS:
        if name.endswith(ext):
            return "pdf"
    return "file"


def _documents_for_review(application):
    """Annotate submitted documents with preview metadata for templates."""
    documents = []
    for doc in application.submitted_documents.all():
        filename = doc.file.name.rsplit("/", 1)[-1] if doc.file else ""
        documents.append(
            {
                "obj": doc,
                "filename": filename or doc.document_type,
                "kind": _document_preview_kind(doc.file) if doc.file else "file",
                "url": doc.file.url if doc.file else "",
            }
        )
    return documents


class LoanStaffMixin(LoginRequiredMixin):
    """Require an authenticated staff/admin/cashier user for pipeline actions."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not _is_loan_staff(request.user):
            raise PermissionDenied("Loan staff access is required for this action.")
        return super().dispatch(request, *args, **kwargs)


class LoanCommitteeAccessMixin(LoginRequiredMixin):
    """Allow full loan staff or credit-committee members."""

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not _can_access_loans(request.user):
            raise PermissionDenied("Loan access is required for this action.")
        return super().dispatch(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# Loan products (catalog management from the dashboard, no Django admin needed)
# ---------------------------------------------------------------------------


class LoanSettingsView(LoanStaffMixin, View):
    """Staff-facing loan settings (grace period and eligibility)."""

    template_name = "loans/loan_settings.html"

    def get(self, request):
        form = forms.LoanSettingsForm(instance=models.LoanSettings.get())
        return render(request, self.template_name, {"form": form})

    def post(self, request):
        settings_obj = models.LoanSettings.get()
        form = forms.LoanSettingsForm(request.POST, instance=settings_obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Loan settings saved.")
            return redirect("loan_settings")
        return render(request, self.template_name, {"form": form})


class LoanProductListView(LoanStaffMixin, ListView):
    model = models.LoanProduct
    template_name = "loans/loanproduct_list.html"
    context_object_name = "products"
    paginate_by = 25

    def get_queryset(self):
        return (
            models.LoanProduct.objects.annotate(
                application_count=Count("applications")
            ).order_by("name")
        )


class LoanProductCreateView(LoanStaffMixin, CreateView):
    model = models.LoanProduct
    form_class = forms.LoanProductForm
    template_name = "loans/loanproduct_form.html"
    success_url = reverse_lazy("loans:product-list")

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Loan product "{self.object.name}" created.')
        return response


# ---------------------------------------------------------------------------
# Intake
# ---------------------------------------------------------------------------


class LoanInquiryCreateView(LoginRequiredMixin, CreateView):
    model = models.LoanInquiry
    form_class = forms.LoanInquiryForm
    template_name = "loans/loaninquiry_form.html"
    success_url = reverse_lazy("loans:application-create")

    def form_valid(self, form):
        form.instance.member = self.request.user
        response = super().form_valid(form)
        messages.success(self.request, "Inquiry recorded. You may now proceed to apply.")
        return response


class LoanApplicationCreateView(LoanStaffMixin, CreateView):
    """Staff walk-in application — same flow as the member New Loan Application."""

    model = models.LoanApplication
    form_class = forms.StaffLoanApplicationForm
    template_name = "loans/loanapplication_form.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        products = models.LoanProduct.objects.all().order_by("name")
        context["products"] = products
        context["is_staff_desk"] = True
        context["product_limits_json"] = {
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
        from members.models import Member

        member_qs = (
            Member.objects.filter(is_active=True, member_role__slug="member", user__isnull=False)
            .select_related("user")
            .only(
                "id",
                "first_name",
                "last_name",
                "user_id",
                "date_joined",
                "created_at",
                "user__username",
                "user__date_joined",
            )
        )
        members_by_user_id = {member.user_id: member for member in member_qs}
        open_applications = (
            models.LoanApplication.objects.filter(member_id__in=members_by_user_id.keys())
            .exclude(
                status__in=(
                    models.LoanApplication.Status.VERIFICATION_FAILED,
                    models.LoanApplication.Status.REJECTED,
                    models.LoanApplication.Status.FULLY_PAID,
                    models.LoanApplication.Status.CLOSED,
                )
            )
            .select_related("loan_product")
            .order_by("member_id", "-created_at")
        )
        member_blocked_products = {}
        for application in open_applications:
            member = members_by_user_id.get(application.member_id)
            if member is None:
                continue
            member_key = str(member.pk)
            member_blocked_products.setdefault(member_key, []).append(
                {
                    "product_id": str(application.loan_product_id),
                    "product_name": application.loan_product.name,
                    "status": application.get_status_display(),
                }
            )
        member_waiting = {}
        for member in members_by_user_id.values():
            waiting = services.member_loan_waiting_period(member, user=member.user)
            if waiting.get("allowed"):
                continue
            required_months = int(waiting.get("required_months") or 0)
            month_word = "month" if required_months == 1 else "months"
            eligible = waiting.get("eligible_on")
            if eligible is not None:
                eligible = timezone.localtime(eligible) if timezone.is_aware(eligible) else eligible
                eligible_display = eligible.strftime("%B %d, %Y")
            else:
                eligible_display = ""
            member_waiting[str(member.pk)] = {
                "message": (
                    f"New members cannot request a loan until they have been a member "
                    f"for {required_months} {month_word}."
                ),
                "required_months": required_months,
                "eligible_on_display": eligible_display,
            }
        context["member_blocked_products_json"] = member_blocked_products
        context["member_waiting_json"] = member_waiting
        context.setdefault("documents_error", "")
        return context

    def form_valid(self, form):
        coop_member = form.cleaned_data["coop_member"]
        loan_user = ensure_member_user(coop_member)
        if loan_user is None:
            form.add_error("coop_member", "Could not resolve a user account for this member.")
            return self.form_invalid(form)

        loan_product = form.cleaned_data["loan_product"]
        open_application = _get_open_application_for_product(loan_user, loan_product)
        if open_application is not None:
            messages.info(
                self.request,
                f"{coop_member.full_name} already has an ongoing {loan_product.name} loan. "
                "Open that application or choose a different loan product.",
            )
            return redirect("loans:application-detail", pk=open_application.pk)

        _can_request, waiting = _loan_request_eligibility(
            loan_user, coop_member, loan_product=loan_product
        )
        if not waiting["allowed"]:
            form.add_error("coop_member", waiting["message"])
            return self.form_invalid(form)

        uploaded_files = self.request.FILES.getlist("documents")
        supporting_files = [f for f in uploaded_files if _is_supporting_upload(f)]
        documents_error = ""
        if not uploaded_files:
            documents_error = "Please upload at least one supporting file."
        elif not supporting_files:
            documents_error = (
                "Only images and common documents are accepted "
                "(JPG, PNG, PDF, DOC, DOCX, XLS, XLSX, and similar)."
            )
        if documents_error:
            form.add_error(None, documents_error)
            return self.form_invalid(form)

        form.instance.member = loan_user
        response = super().form_valid(form)
        record_loan_audit(
            self.object,
            models.LoanApplicationAuditLog.Action.APPLICATION_CREATED,
            actor=self.request.user,
            description=(
                f"Staff created loan application for {coop_member.full_name} — "
                f"{self.object.loan_product.name} "
                f"(₱{self.object.amount_requested:,.2f}, {self.object.term_months} months)."
            ),
            metadata={
                "loan_product_id": str(self.object.loan_product_id),
                "amount_requested": str(self.object.amount_requested),
                "interest_rate": str(self.object.interest_rate),
                "term_months": self.object.term_months,
                "channel": "staff_desk",
                "coop_member_id": coop_member.pk,
            },
            request=self.request,
        )
        for uploaded_file in supporting_files:
            doc = models.SubmittedDocument.objects.create(
                application=self.object,
                document_type=uploaded_file.name,
                file=uploaded_file,
            )
            record_loan_audit(
                self.object,
                models.LoanApplicationAuditLog.Action.DOCUMENT_UPLOADED,
                actor=self.request.user,
                description=f"Supporting document uploaded: {uploaded_file.name}.",
                metadata={"document_id": doc.pk, "document_type": uploaded_file.name},
                request=self.request,
            )
        try:
            self.object.submit()
            self.object.save(update_fields=["status", "submitted_at"])
            record_loan_audit(
                self.object,
                models.LoanApplicationAuditLog.Action.APPLICATION_SUBMITTED,
                actor=self.request.user,
                description="Loan application submitted for staff review.",
                metadata={
                    "submitted_at": self.object.submitted_at.isoformat(),
                    "channel": "staff_desk",
                },
                request=self.request,
            )
            messages.success(self.request, "Loan application submitted successfully.")
        except TransitionNotAllowed:
            messages.warning(self.request, "Application saved as draft.")
        return response

    def get_success_url(self):
        return reverse("loans:application-detail", kwargs={"pk": self.object.pk})


# ---------------------------------------------------------------------------
# Underwriting pipeline
# ---------------------------------------------------------------------------


class EligibilityVerificationView(LoanStaffMixin, PipelineStepLockMixin, View):
    template_name = "loans/eligibilityverification_form.html"
    pipeline_action_key = "eligibility"

    def get(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = getattr(application, "eligibility_verification", None)
        form = forms.EligibilityVerificationForm(instance=instance)
        maturity = services.application_membership_maturity(application)
        return self._render(request, application, form, maturity=maturity)

    def post(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = getattr(application, "eligibility_verification", None)
        # Explicit Pass / Fail buttons override checkbox ambiguity.
        action = (request.POST.get("action") or "").strip().lower()
        maturity = services.application_membership_maturity(application)
        if action == "pass" and not maturity.get("allowed"):
            messages.error(
                request,
                maturity.get("message")
                or "Cannot pass verification: member has not met the minimum membership period.",
            )
            form = forms.EligibilityVerificationForm(request.POST, instance=instance)
            return self._render(request, application, form, maturity=maturity)

        form = forms.EligibilityVerificationForm(request.POST, instance=instance)
        if form.is_valid():
            verification = form.save(commit=False)
            verification.application = application
            verification.verified_by = request.user
            verification.verified_at = timezone.now()
            if action == "pass":
                verification.membership_status_ok = True
                verification.documents_complete = True
            elif action == "fail":
                # Keep posted values but force a failed outcome if both somehow true.
                if verification.membership_status_ok and verification.documents_complete:
                    verification.documents_complete = False
            verification.save()

            record_loan_audit(
                application,
                models.LoanApplicationAuditLog.Action.ELIGIBILITY_REVIEW,
                actor=request.user,
                description=(
                    "Eligibility verification passed — proceeding to credit investigation."
                    if verification.passed
                    else "Eligibility verification failed."
                ),
                metadata={
                    "passed": verification.passed,
                    "membership_status_ok": verification.membership_status_ok,
                    "documents_complete": verification.documents_complete,
                    "remarks": verification.remarks,
                    "action": action or "save",
                },
                request=request,
            )

            try:
                if application.status == models.LoanApplication.Status.SUBMITTED:
                    application.begin_verification()
                    application.save(update_fields=["status"])
                if application.status == models.LoanApplication.Status.UNDER_VERIFICATION:
                    application.complete_verification(verification.passed)
                    application.save(update_fields=["status"])
                messages.success(
                    request,
                    "Eligibility passed — moved to credit investigation."
                    if verification.passed
                    else "Eligibility failed — application marked verification failed.",
                )
            except TransitionNotAllowed:
                messages.warning(
                    request,
                    "Verification saved, but the application is not in a verifiable state.",
                )
            return redirect("loans:application-detail", pk=application.pk)
        return self._render(request, application, form)

    def _render(self, request, application, form, maturity=None):
        return render(
            request,
            self.template_name,
            {
                "application": application,
                "form": form,
                "documents": _documents_for_review(application),
                "membership_maturity": maturity or services.application_membership_maturity(application),
                "loan_history": services.member_loan_history(
                    application.member, exclude_application=application
                ),
            },
        )


class CreditInvestigationView(LoanStaffMixin, PipelineStepLockMixin, View):
    template_name = "loans/creditinvestigation_form.html"
    pipeline_action_key = "credit"

    def get(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = getattr(application, "credit_investigation", None)
        score_info = services.compute_repayment_capacity_score(
            application.member, exclude_application=application
        )
        form = forms.CreditInvestigationForm(
            instance=instance, auto_score=score_info["score"]
        )
        return self._render(request, application, form, score_info)

    def post(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = getattr(application, "credit_investigation", None)
        score_info = services.compute_repayment_capacity_score(
            application.member, exclude_application=application
        )
        form = forms.CreditInvestigationForm(
            request.POST, instance=instance, auto_score=score_info["score"]
        )
        if form.is_valid():
            investigation = form.save(commit=False)
            investigation.application = application
            investigation.evaluated_by = request.user
            investigation.evaluated_at = timezone.now()
            # Always use the auto-computed payment score (ignore manual edits).
            investigation.repayment_capacity_score = score_info["score"]
            investigation.save()

            record_loan_audit(
                application,
                models.LoanApplicationAuditLog.Action.CREDIT_INVESTIGATION,
                actor=request.user,
                description=(
                    f"Credit investigation recorded — recommendation: "
                    f"{investigation.get_recommendation_display()}."
                ),
                metadata={
                    "repayment_capacity_score": str(investigation.repayment_capacity_score),
                    "recommendation": investigation.recommendation,
                    "remarks": investigation.remarks,
                },
                request=request,
            )

            try:
                application.submit_for_committee()
                application.save(update_fields=["status"])
                messages.success(request, "Credit investigation recorded — sent to committee.")
            except TransitionNotAllowed:
                messages.warning(
                    request,
                    "Investigation saved, but the application is not under investigation.",
                )
            return redirect("loans:application-detail", pk=application.pk)
        return self._render(request, application, form, score_info)

    def _render(self, request, application, form, score_info=None):
        return render(
            request,
            self.template_name,
            {
                "application": application,
                "form": form,
                "score_info": score_info,
            },
        )


class CommitteeReviewView(LoanCommitteeAccessMixin, PipelineStepLockMixin, View):
    template_name = "loans/committeereview_form.html"
    pipeline_action_key = "committee"

    def get(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        outcome = services.try_finalize_committee_approval(
            application, actor=request.user, request=request
        )
        if outcome == "approved":
            messages.success(
                request,
                "Committee approval complete. Loan is now Approved — proceed to the next pipeline step.",
            )
            return redirect("loans:application-detail", pk=application.pk)
        if outcome == "rejected":
            messages.warning(request, "Committee rejected this loan application.")
            return redirect("loans:application-detail", pk=application.pk)

        instance = getattr(application, "committee_review", None)
        form = forms.CommitteeReviewForm(instance=instance)
        return self._render(request, application, form)

    def post(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        action = (request.POST.get("action") or "").strip().lower()
        remarks = (request.POST.get("remarks") or "").strip()
        instance = getattr(application, "committee_review", None)
        form = forms.CommitteeReviewForm(instance=instance)

        if action == "proceed":
            if not services.user_can_committee_vote(request.user):
                messages.error(
                    request,
                    "Only authorized approvers may finalize committee approval.",
                )
                return self._render(request, application, form)

            approval_status = services.committee_approval_status(
                application, current_user=request.user
            )
            if not approval_status["can_proceed"]:
                need_msg = (
                    "one approval"
                    if approval_status.get("single_approver")
                    else "majority approval"
                )
                messages.error(
                    request,
                    f"Cannot proceed yet — {need_msg} and membership maturity are required.",
                )
                return self._render(request, application, form)

            outcome = services.try_finalize_committee_approval(
                application, remarks=remarks, actor=request.user, request=request
            )
            if outcome == "approved":
                messages.success(
                    request,
                    "Committee approval confirmed. Loan is now Approved — proceed to the next step.",
                )
                return redirect("loans:application-detail", pk=application.pk)
            messages.error(request, "Could not finalize approval. Refresh and try again.")
            return self._render(request, application, form)

        if not services.user_can_committee_vote(request.user):
            messages.error(
                request,
                "Only admins, loan officers, staff, and credit committee members may record votes.",
            )
            return self._render(request, application, form)

        if action == "approve":
            maturity = services.application_membership_maturity(application)
            if not maturity.get("allowed"):
                messages.error(
                    request,
                    maturity.get("message")
                    or "Cannot approve: member has not met the minimum membership period.",
                )
                return self._render(request, application, form, maturity=maturity)

            try:
                outcome = services.record_committee_vote(
                    application,
                    request.user,
                    models.LoanCommitteeVote.Vote.APPROVE,
                    remarks=remarks,
                    request=request,
                )
            except TransitionNotAllowed as exc:
                messages.error(request, str(exc))
                return self._render(request, application, form)
            except PermissionDenied as exc:
                messages.error(request, str(exc))
                return self._render(request, application, form)

            if outcome == "approved":
                messages.success(
                    request,
                    "Committee approval complete. Loan is now Approved — proceed to the next pipeline step.",
                )
            else:
                approval_status = services.committee_approval_status(
                    application, current_user=request.user
                )
                needed = approval_status["votes_needed"]
                if approval_status["majority_reached"]:
                    messages.success(
                        request,
                        "Your approval was recorded. Threshold met — use Proceed to next step to finalize.",
                    )
                elif approval_status.get("single_approver"):
                    messages.success(
                        request,
                        "Your approval was recorded.",
                    )
                elif approval_status["pending_approvers"]:
                    waiting = ", ".join(
                        item["name"] for item in approval_status["pending_approvers"]
                    )
                    messages.success(
                        request,
                        f"Your approval was recorded ({approval_status['total_approved']}/{needed} needed for majority). Still waiting for: {waiting}.",
                    )
                else:
                    messages.success(request, "Your approval was recorded.")
            return redirect("loans:application-detail", pk=application.pk)

        if action == "reject":
            try:
                outcome = services.record_committee_vote(
                    application,
                    request.user,
                    models.LoanCommitteeVote.Vote.REJECT,
                    remarks=remarks,
                    request=request,
                )
                if outcome == "rejected":
                    messages.warning(
                        request,
                        "Committee rejected this loan. Applicant has been notified.",
                    )
                else:
                    messages.info(request, "Your rejection was recorded.")
            except TransitionNotAllowed as exc:
                messages.error(request, str(exc))
                return self._render(request, application, form)
            except PermissionDenied as exc:
                messages.error(request, str(exc))
                return self._render(request, application, form)
            return redirect("loans:application-detail", pk=application.pk)

        return self._render(request, application, form)

    def _render(self, request, application, form, maturity=None):
        approval_status = services.committee_approval_status(
            application,
            current_user=request.user,
        )
        return render(
            request,
            self.template_name,
            {
                "application": application,
                "form": form,
                "membership_maturity": maturity or approval_status["maturity"],
                "committee_approval": approval_status,
            },
        )


class LoanApproveView(LoanStaffMixin, View):
    """Direct approve is disabled — staff must use the pipeline steps."""

    def post(self, request, pk):
        record_loan_audit(
            get_object_or_404(models.LoanApplication, pk=pk),
            models.LoanApplicationAuditLog.Action.SECURITY_ACTION_BLOCKED,
            actor=request.user,
            description="Attempted direct loan approval — blocked by security policy.",
            metadata={"attempted_action": "direct_approve"},
            request=request,
        )
        messages.warning(
            request,
            "Direct approval is disabled for security. Complete each pipeline step in order.",
        )
        return redirect("loans:application-detail", pk=pk)


class LoanRejectView(LoanStaffMixin, View):
    """Direct reject is disabled — use eligibility or committee review in the pipeline."""

    def post(self, request, pk):
        record_loan_audit(
            get_object_or_404(models.LoanApplication, pk=pk),
            models.LoanApplicationAuditLog.Action.SECURITY_ACTION_BLOCKED,
            actor=request.user,
            description="Attempted direct loan rejection — blocked by security policy.",
            metadata={"attempted_action": "direct_reject"},
            request=request,
        )
        messages.warning(
            request,
            "Use the pipeline steps to fail verification or reject at committee review.",
        )
        return redirect("loans:application-detail", pk=pk)


class InsuranceEnrollmentView(LoanStaffMixin, PipelineStepLockMixin, View):
    template_name = "loans/insuranceenrollment_form.html"
    pipeline_action_key = "insurance"

    def get(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = getattr(application, "insurance_enrollment", None)
        form = forms.InsuranceEnrollmentForm(instance=instance)
        return self._render(request, application, form)

    def post(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = getattr(application, "insurance_enrollment", None)
        form = forms.InsuranceEnrollmentForm(request.POST, instance=instance)
        if form.is_valid():
            enrollment = form.save(commit=False)
            enrollment.application = application
            enrollment.enrolled_at = timezone.now()
            enrollment.save()

            record_loan_audit(
                application,
                models.LoanApplicationAuditLog.Action.INSURANCE_ENROLLED,
                actor=request.user,
                description=(
                    f"Insurance enrolled ({enrollment.get_insurance_type_display()}, "
                    f"premium ₱{enrollment.premium_amount:,.2f})."
                ),
                metadata={
                    "insurance_type": enrollment.insurance_type,
                    "premium_amount": str(enrollment.premium_amount),
                    "payment_mode": enrollment.payment_mode,
                },
                request=request,
            )

            try:
                application.enroll_insurance()
                application.save(update_fields=["status"])
                messages.success(request, "Insurance enrollment recorded.")
            except TransitionNotAllowed:
                messages.warning(request, "Enrollment saved, but the application is not approved for insurance.")
            return redirect("loans:application-detail", pk=application.pk)
        return self._render(request, application, form)

    def _render(self, request, application, form):
        return render(request, self.template_name, {"application": application, "form": form})


class LoanDocumentationView(LoanStaffMixin, PipelineStepLockMixin, View):
    template_name = "loans/loandocumentation_form.html"
    pipeline_action_key = "documentation"

    def _get_documentation(self, application):
        return models.LoanDocumentation.objects.filter(application=application).first()

    def get(self, request, pk):
        application = get_object_or_404(
            models.LoanApplication.objects.select_related("loan_product", "member"),
            pk=pk,
        )
        documentation = self._get_documentation(application)
        if documentation is None or not documentation.agreement_file:
            documentation = services.generate_loan_agreement(application, documentation)
        form = forms.LoanDocumentationForm(instance=documentation)
        return self._render(request, application, form, documentation)

    def post(self, request, pk):
        application = get_object_or_404(
            models.LoanApplication.objects.select_related("loan_product", "member"),
            pk=pk,
        )
        documentation = self._get_documentation(application)
        if documentation is None:
            documentation = services.generate_loan_agreement(application)
        form = forms.LoanDocumentationForm(
            request.POST, request.FILES, instance=documentation
        )
        if form.is_valid():
            documentation = form.save(commit=False)
            documentation.application = application
            now = timezone.now()
            signing_method = form.cleaned_data.get("signing_method")
            documentation.signing_method = signing_method
            hard_copy_file = form.cleaned_data.get("signed_hard_copy")

            if signing_method == models.LoanDocumentation.SigningMethod.HARD_COPY:
                if hard_copy_file:
                    documentation.signed_hard_copy = hard_copy_file
                    documentation.signed_hard_copy_uploaded_at = now
                    documentation.signed_hard_copy_uploaded_by = request.user
                documentation.signed_by_borrower_at = (
                    documentation.signed_by_borrower_at or now
                )
                documentation.signed_by_authorized_personnel_at = (
                    documentation.signed_by_authorized_personnel_at or now
                )
                documentation.save()
                if form.cleaned_data.get("regenerate_contract") or not documentation.agreement_file:
                    documentation = services.generate_loan_agreement(application, documentation)
            else:
                if form.cleaned_data.get("clear_borrower_signature") and documentation.borrower_signature:
                    documentation.borrower_signature.delete(save=False)
                    documentation.borrower_signature = None
                    documentation.signed_by_borrower_at = None

                if form.cleaned_data.get("clear_personnel_signature") and documentation.personnel_signature:
                    documentation.personnel_signature.delete(save=False)
                    documentation.personnel_signature = None
                    documentation.signed_by_authorized_personnel_at = None

                borrower_data = form.cleaned_data.get("borrower_signature_data")
                if borrower_data:
                    _save_signature_data_url(
                        documentation.borrower_signature,
                        borrower_data,
                        f"borrower_{application.pk}",
                    )
                    documentation.signed_by_borrower_at = now
                elif documentation.borrower_signature and not documentation.signed_by_borrower_at:
                    documentation.signed_by_borrower_at = now

                personnel_data = form.cleaned_data.get("personnel_signature_data")
                if personnel_data:
                    _save_signature_data_url(
                        documentation.personnel_signature,
                        personnel_data,
                        f"personnel_{application.pk}",
                    )
                    documentation.signed_by_authorized_personnel_at = now
                elif documentation.personnel_signature and not documentation.signed_by_authorized_personnel_at:
                    documentation.signed_by_authorized_personnel_at = now

                documentation.save()
                documentation = services.generate_loan_agreement(application, documentation)

            hard_copy_name = ""
            if documentation.signed_hard_copy:
                hard_copy_name = documentation.signed_hard_copy.name.split("/")[-1]
            record_loan_audit(
                application,
                (
                    models.LoanApplicationAuditLog.Action.SIGNED_HARD_COPY_UPLOADED
                    if signing_method == models.LoanDocumentation.SigningMethod.HARD_COPY
                    else models.LoanApplicationAuditLog.Action.DOCUMENTATION_SIGNED
                ),
                actor=request.user,
                description=(
                    f"Signed paper contract uploaded for security: {hard_copy_name}."
                    if signing_method == models.LoanDocumentation.SigningMethod.HARD_COPY
                    else "Loan payment contract signed on screen and documentation saved."
                ),
                metadata={
                    "signing_method": signing_method,
                    "borrower_signed_at": (
                        documentation.signed_by_borrower_at.isoformat()
                        if documentation.signed_by_borrower_at
                        else None
                    ),
                    "personnel_signed_at": (
                        documentation.signed_by_authorized_personnel_at.isoformat()
                        if documentation.signed_by_authorized_personnel_at
                        else None
                    ),
                    "has_agreement_file": bool(documentation.agreement_file),
                    "has_signed_hard_copy": bool(documentation.signed_hard_copy),
                    "hard_copy_filename": hard_copy_name,
                },
                request=request,
            )

            try:
                application.sign_documents()
                application.save(update_fields=["status"])
                messages.success(
                    request,
                    "Signed hard copy stored securely. Documentation is complete."
                    if signing_method == models.LoanDocumentation.SigningMethod.HARD_COPY
                    else "Payment contract signed and loan documentation recorded.",
                )
            except TransitionNotAllowed:
                messages.warning(
                    request,
                    "Contract saved, but the application is not ready for documentation signing.",
                )
            return redirect("loans:application-detail", pk=application.pk)
        return self._render(request, application, form, documentation)

    def _render(self, request, application, form, documentation=None):
        contract = services.build_loan_agreement_context(application)
        return render(
            request,
            self.template_name,
            {
                "application": application,
                "form": form,
                "documentation": documentation,
                "contract": contract,
            },
        )


class DisbursementView(LoanStaffMixin, PipelineStepLockMixin, View):
    template_name = "loans/disbursement_form.html"
    pipeline_action_key = "disbursement"

    def _get_disbursement(self, application):
        return models.Disbursement.objects.filter(application=application).first()

    def get(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = self._get_disbursement(application)
        form = forms.DisbursementForm(
            instance=instance,
            amount_requested=application.amount_requested,
        )
        return self._render(request, application, form)

    def post(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = self._get_disbursement(application)
        form = forms.DisbursementForm(
            request.POST,
            instance=instance,
            amount_requested=application.amount_requested,
        )
        if form.is_valid():
            disbursement = form.save(commit=False)
            disbursement.application = application
            disbursement.disbursed_by = request.user
            disbursement.disbursement_date = timezone.now()
            disbursement.save()

            record_loan_audit(
                application,
                models.LoanApplicationAuditLog.Action.DISBURSEMENT,
                actor=request.user,
                description=(
                    f"Loan disbursed: principal ₱{application.amount_requested:,.2f}, "
                    f"net released ₱{disbursement.amount_released:,.2f} via "
                    f"{disbursement.get_disbursement_method_display()}."
                ),
                metadata={
                    "principal_amount": str(application.amount_requested),
                    "amount_released": str(disbursement.amount_released),
                    "transaction_fee": str(disbursement.transaction_fee),
                    "other_deduction_amount": str(disbursement.other_deduction_amount),
                    "other_deduction_label": disbursement.other_deduction_label,
                    "total_deductions": str(disbursement.total_deductions),
                    "disbursement_method": disbursement.disbursement_method,
                    "reference_number": disbursement.reference_number,
                },
                request=request,
            )

            try:
                application.disburse()
                application.save(update_fields=["status"])
                services.ensure_monthly_repayment_schedule(
                    application, actor=request.user, request=request
                )
                messages.success(
                    request,
                    (
                        f"Loan disbursed. Principal ₱{application.amount_requested:,.2f}; "
                        f"net released ₱{disbursement.amount_released:,.2f}. "
                        "Print the disbursement voucher for the member."
                    ),
                )
            except TransitionNotAllowed:
                messages.warning(request, "Disbursement saved, but the application documentation is not signed.")
                return redirect("loans:application-detail", pk=application.pk)
            return redirect("loans:disbursement-receipt", pk=application.pk)
        return self._render(request, application, form)

    def _render(self, request, application, form):
        return render(
            request,
            self.template_name,
            {
                "application": application,
                "form": form,
                "requested_amount": application.amount_requested,
                "principal_amount": application.amount_requested,
            },
        )


class DisbursementReceiptView(LoanCommitteeAccessMixin, View):
    """Printable disbursement voucher showing principal, deductions, and net released."""

    template_name = "loans/disbursement_receipt.html"

    def get(self, request, pk):
        application = get_object_or_404(
            models.LoanApplication.objects.select_related(
                "loan_product",
                "member",
                "disbursement__disbursed_by",
            ),
            pk=pk,
        )
        disbursement = getattr(application, "disbursement", None)
        if disbursement is None:
            messages.error(request, "This loan has not been disbursed yet.")
            return redirect("loans:application-detail", pk=application.pk)

        member = application.member
        member_name = (
            member.get_full_name()
            if hasattr(member, "get_full_name")
            else str(member)
        ) or str(member)
        disbursed_by = disbursement.disbursed_by
        disbursed_by_name = (
            (disbursed_by.get_full_name() or disbursed_by.username)
            if disbursed_by
            else "—"
        )
        store_ctx = get_receipt_store_context(request)

        return render(
            request,
            self.template_name,
            {
                "application": application,
                "disbursement": disbursement,
                "member_name": member_name,
                "disbursed_by_name": disbursed_by_name,
                **store_ctx,
            },
        )


class PaymentOptionSelectView(LoanCommitteeAccessMixin, View):
    """Removed duplicate step — repayment uses the loan term (monthly amortization)."""

    def get(self, request, pk):
        return redirect("loans:payment-collect", pk=pk)

    def post(self, request, pk):
        return redirect("loans:payment-collect", pk=pk)


class PaymentCollectionView(LoanCommitteeAccessMixin, PipelineStepLockMixin, View):
    template_name = "loans/payment_list.html"
    pipeline_action_key = "payment_collect"

    def get(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        services.ensure_monthly_repayment_schedule(
            application, actor=request.user, request=request
        )
        form = forms.PaymentForm(application=application)
        return self._render(request, application, form)

    def post(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        services.ensure_monthly_repayment_schedule(
            application, actor=request.user, request=request
        )
        form = forms.PaymentForm(request.POST, application=application)
        if form.is_valid():
            payment = services.record_payment(
                application=application,
                amount=form.cleaned_data["amount_paid"],
                collected_by=request.user,
                payment_method=form.cleaned_data["payment_method"],
                or_number=form.cleaned_data.get("or_number", ""),
                remarks=form.cleaned_data.get("remarks", ""),
                usable_from=form.cleaned_data.get("usable_from"),
                usable_to=form.cleaned_data.get("usable_to"),
                usable_days=form.cleaned_data.get("usable_days"),
                period_interest=form.cleaned_data.get("period_interest"),
                request=request,
            )
            messages.success(
                request,
                f"Payment recorded. Official receipt {payment.or_number} issued.",
            )
            return redirect(_payment_receipt_url(application.pk, payment.pk))
        return self._render(request, application, form)

    def _render(self, request, application, form):
        payments = list(
            application.payments.select_related(
                "collected_by", "applied_to_installment"
            ).all()
        )
        services.ensure_payment_or_numbers(payments)
        for payment in payments:
            payment.receipt_url = _payment_receipt_url(application.pk, payment.pk)
        return render(
            request,
            self.template_name,
            {
                "application": application,
                "form": form,
                "payments": payments,
                "outstanding_balance": application.total_outstanding_balance(),
                "remaining_principal": application.remaining_principal_balance(),
                "principal_fully_paid": application.is_principal_fully_paid(),
                "interest_rate": application.effective_interest_rate(),
                "next_usable_from": application.next_usable_from_date(),
                "payment_receipts_all_url": _payment_receipts_all_url(application.pk),
            },
        )


def _payment_receipt_url(application_pk, payment_id):
    try:
        return reverse(
            "loans:payment-receipt",
            kwargs={"pk": application_pk, "payment_id": payment_id},
        )
    except Exception:
        return f"/dashboard/loans/steps/{application_pk}/payments/{payment_id}/receipt/"


def _payment_receipts_all_url(application_pk):
    try:
        return reverse("loans:payment-receipts-all", kwargs={"pk": application_pk})
    except Exception:
        return f"/dashboard/loans/steps/{application_pk}/payments/receipts/"


class PaymentReceiptView(LoanCommitteeAccessMixin, View):
    """Printable official receipt for a single loan payment (audit/security)."""

    template_name = "loans/payment_receipt.html"

    def get(self, request, pk, payment_id):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        payment = get_object_or_404(
            models.Payment.objects.select_related(
                "collected_by",
                "applied_to_installment",
                "application__loan_product",
                "application__member",
                "application__disbursement",
            ),
            pk=payment_id,
            application=application,
        )
        services.allocate_or_number(payment)
        receipt_detail = services.build_payment_receipt_context(application, payment)
        store_ctx = get_receipt_store_context(request)
        member = application.member
        member_name = (
            member.get_full_name()
            if hasattr(member, "get_full_name")
            else str(member)
        ) or str(member)
        collector = payment.collected_by
        collector_name = (
            (collector.get_full_name() or collector.username) if collector else "—"
        )

        return render(
            request,
            self.template_name,
            {
                "application": application,
                "payment": payment,
                "member_name": member_name,
                "collector_name": collector_name,
                "outstanding_balance": receipt_detail["outstanding_after"],
                "receipt_detail": receipt_detail,
                "single": True,
                **store_ctx,
            },
        )


class PaymentReceiptBatchView(LoanCommitteeAccessMixin, View):
    """Printable official receipts for all payments on a loan application."""

    template_name = "loans/payment_receipt.html"

    def get(self, request, pk):
        application = get_object_or_404(
            models.LoanApplication.objects.select_related(
                "loan_product", "member", "disbursement"
            ),
            pk=pk,
        )
        payments = list(
            application.payments.select_related(
                "collected_by", "applied_to_installment"
            ).order_by("payment_date", "id")
        )
        services.ensure_payment_or_numbers(payments)
        for pay in payments:
            pay.receipt_detail = services.build_payment_receipt_context(application, pay)

        store_ctx = get_receipt_store_context(request)
        member = application.member
        member_name = (
            member.get_full_name()
            if hasattr(member, "get_full_name")
            else str(member)
        ) or str(member)

        return render(
            request,
            self.template_name,
            {
                "application": application,
                "payments": payments,
                "member_name": member_name,
                "outstanding_balance": application.total_outstanding_balance(),
                "single": False,
                **store_ctx,
            },
        )


# ---------------------------------------------------------------------------
# Read views
# ---------------------------------------------------------------------------


class LoanApplicationDetailView(LoanCommitteeAccessMixin, DetailView):
    model = models.LoanApplication
    template_name = "loans/loanapplication_detail.html"
    context_object_name = "application"

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        Status = models.LoanApplication.Status
        if self.object.status == Status.PENDING_COMMITTEE_APPROVAL:
            outcome = services.try_finalize_committee_approval(
                self.object, actor=request.user, request=request
            )
            if outcome == "approved":
                messages.success(
                    request,
                    "Committee approval complete. Loan is now Approved — proceed to the next pipeline step.",
                )
                return redirect("loans:application-detail", pk=self.object.pk)
            if outcome == "rejected":
                messages.warning(request, "Committee rejected this loan application.")
                return redirect("loans:application-detail", pk=self.object.pk)
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        application = self.object
        Status = models.LoanApplication.Status
        status_order = [key for key, _ in PIPELINE_STEPS]
        try:
            current_index = status_order.index(application.status)
        except ValueError:
            current_index = -1

        steps = []
        for index, (key, label) in enumerate(PIPELINE_STEPS):
            steps.append(
                {
                    "key": key,
                    "label": label,
                    "completed": index < current_index,
                    "current": index == current_index,
                }
            )

        # Status-aware next actions (primary CTA first).
        next_actions = []
        if application.status == Status.SUBMITTED:
            next_actions = [
                {
                    "label": "Verify Eligibility (Pass)",
                    "url": reverse("loans:eligibility-verify", kwargs={"pk": application.pk}),
                    "primary": True,
                },
            ]
        elif application.status == Status.UNDER_VERIFICATION:
            next_actions = [
                {
                    "label": "Complete Eligibility Verification",
                    "url": reverse("loans:eligibility-verify", kwargs={"pk": application.pk}),
                    "primary": True,
                },
            ]
        elif application.status == Status.UNDER_INVESTIGATION:
            next_actions = [
                {
                    "label": "Submit Credit Investigation",
                    "url": reverse("loans:credit-investigate", kwargs={"pk": application.pk}),
                    "primary": True,
                },
            ]
        elif application.status == Status.PENDING_COMMITTEE_APPROVAL:
            committee_status = services.committee_approval_status(
                application, current_user=self.request.user
            )
            if committee_status["can_proceed"]:
                next_actions = [
                    {
                        "label": "Proceed to next step",
                        "url": reverse("loans:committee-review", kwargs={"pk": application.pk}),
                        "primary": True,
                    },
                ]
            else:
                next_actions = [
                    {
                        "label": "Committee Review — Approve / Reject",
                        "url": reverse("loans:committee-review", kwargs={"pk": application.pk}),
                        "primary": True,
                    },
                ]
        elif application.status == Status.APPROVED:
            if application.loan_product.requires_insurance:
                next_actions = [
                    {
                        "label": "Enroll Insurance",
                        "url": reverse("loans:insurance-enroll", kwargs={"pk": application.pk}),
                        "primary": True,
                    },
                ]
            else:
                next_actions = [
                    {
                        "label": "Sign Documentation",
                        "url": reverse("loans:documentation-sign", kwargs={"pk": application.pk}),
                        "primary": True,
                    },
                ]
        elif application.status == Status.INSURANCE_ENROLLED:
            next_actions = [
                {
                    "label": "Sign Documentation",
                    "url": reverse("loans:documentation-sign", kwargs={"pk": application.pk}),
                    "primary": True,
                },
            ]
        elif application.status == Status.DOCUMENTATION_SIGNED:
            next_actions = [
                {
                    "label": "Disburse Loan",
                    "url": reverse("loans:disburse", kwargs={"pk": application.pk}),
                    "primary": True,
                },
            ]
        elif application.status in {Status.DISBURSED, Status.ACTIVE}:
            next_actions = [
                {
                    "label": "Collect Payment",
                    "url": reverse("loans:payment-collect", kwargs={"pk": application.pk}),
                    "primary": True,
                },
            ]

        membership_maturity = services.application_membership_maturity(application)
        user = self.request.user
        is_committee = _is_loan_committee(user)
        is_staff = _is_loan_staff(user)
        pipeline_review_statuses = {
            Status.SUBMITTED,
            Status.UNDER_VERIFICATION,
            Status.UNDER_INVESTIGATION,
            Status.PENDING_COMMITTEE_APPROVAL,
        }
        show_security_review = (
            is_staff
            and application.status in pipeline_review_statuses
        )

        context["pipeline_steps"] = steps
        context["outstanding_balance"] = application.total_outstanding_balance()
        context["total_paid"] = application.total_paid_amount()
        context["total_obligation"] = application.total_obligation_amount()
        context["interest_breakdown"] = application.interest_balance_breakdown()
        if is_committee and not is_staff:
            if application.status in {
                Status.PENDING_COMMITTEE_APPROVAL,
                Status.DISBURSED,
                Status.ACTIVE,
            }:
                context["next_actions"] = next_actions
            else:
                context["next_actions"] = []
        else:
            context["next_actions"] = next_actions
        context["show_security_review"] = show_security_review
        context["membership_maturity"] = membership_maturity
        context["staff_reviewer_name"] = _staff_approver_label(user)
        context["staff_reviewer_role"] = (
            get_linked_member(user).get_role_display()
            if get_linked_member(user)
            else "Staff"
        )
        context["is_loan_staff"] = is_staff
        context["is_loan_committee"] = is_committee
        context["is_loan_officer"] = is_loan_officer_user(user)
        if application.status == Status.PENDING_COMMITTEE_APPROVAL:
            context["committee_approval"] = services.committee_approval_status(
                application,
                current_user=user,
            )
        if is_staff:
            context["pipeline_actions"] = _pipeline_actions_for(application)
        elif is_committee:
            context["pipeline_actions"] = _pipeline_actions_for_committee(application)
        else:
            context["pipeline_actions"] = []
        context["documents"] = _documents_for_review(application)

        # Payment contract identity panel (for staff security / verification).
        documentation = models.LoanDocumentation.objects.filter(
            application=application
        ).first()
        contract_ready_statuses = {
            Status.APPROVED,
            Status.INSURANCE_ENROLLED,
            Status.DOCUMENTATION_SIGNED,
            Status.DISBURSED,
            Status.ACTIVE,
            Status.FULLY_PAID,
            Status.CLOSED,
        }
        if application.status in contract_ready_statuses:
            if documentation is None or not documentation.agreement_file:
                documentation = services.generate_loan_agreement(
                    application, documentation
                )
        context["documentation"] = documentation
        context["contract"] = services.build_loan_agreement_context(application)
        context["show_contract"] = application.status in contract_ready_statuses
        if is_staff:
            context["audit_logs"] = list(
                application.audit_logs.select_related("actor").all()[:200]
            )
        else:
            context["audit_logs"] = []
        return context


class LoanApplicationListView(LoanCommitteeAccessMixin, ListView):
    model = models.LoanApplication
    template_name = "loans/loanapplication_list.html"
    context_object_name = "applications"
    paginate_by = 25

    def _base_queryset(self):
        queryset = models.LoanApplication.objects.select_related("member", "loan_product")
        user = self.request.user
        if not _can_access_loans(user):
            queryset = queryset.filter(member=user)
        return queryset

    def get_queryset(self):
        queryset = self._base_queryset()
        Status = models.LoanApplication.Status
        acquired_statuses = (
            Status.DISBURSED,
            Status.ACTIVE,
            Status.FULLY_PAID,
            Status.CLOSED,
        )

        search_query = (self.request.GET.get("search") or "").strip()
        status_filter = (self.request.GET.get("status") or "all").strip().lower()
        valid_status_keys = {s.value.lower() for s in Status} | {"all", "acquired", "pending"}
        if status_filter not in valid_status_keys:
            status_filter = "all"

        if status_filter == "acquired":
            queryset = queryset.filter(status__in=acquired_statuses)
        elif status_filter == "pending":
            queryset = queryset.exclude(
                status__in=acquired_statuses
                + (Status.REJECTED, Status.VERIFICATION_FAILED, Status.DRAFT)
            )
        elif status_filter != "all":
            queryset = queryset.filter(status=status_filter.upper())

        if search_query:
            queryset = queryset.filter(
                Q(member__username__icontains=search_query)
                | Q(member__first_name__icontains=search_query)
                | Q(member__last_name__icontains=search_query)
                | Q(member__email__icontains=search_query)
                | Q(loan_product__name__icontains=search_query)
                | Q(purpose__icontains=search_query)
            )

        return queryset.order_by("-created_at")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        Status = models.LoanApplication.Status
        acquired_statuses = (
            Status.DISBURSED,
            Status.ACTIVE,
            Status.FULLY_PAID,
            Status.CLOSED,
        )
        base = self._base_queryset()
        context["search_query"] = (self.request.GET.get("search") or "").strip()
        context["status_filter"] = (self.request.GET.get("status") or "all").strip().lower()
        context["total_count"] = base.count()
        context["acquired_count"] = base.filter(status__in=acquired_statuses).count()
        context["active_count"] = base.filter(status=Status.ACTIVE).count()
        context["pending_count"] = base.exclude(
            status__in=acquired_statuses
            + (Status.REJECTED, Status.VERIFICATION_FAILED, Status.DRAFT)
        ).count()
        context["status_choices"] = Status.choices
        return context


@method_decorator(require_POST, name="dispatch")
class LoanApplicationDeleteView(LoginRequiredMixin, View):
    """Permanently delete a loan application. Admin role only; written to audit trail."""

    def post(self, request, pk):
        if not is_admin_user(request.user):
            return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

        application = get_object_or_404(
            models.LoanApplication.objects.select_related("member", "loan_product"),
            pk=pk,
        )

        app_id = str(application.pk)
        member_name = (
            application.member.get_full_name()
            or application.member.username
            or "Unknown"
        )
        product_name = application.loan_product.name if application.loan_product_id else ""
        amount = f"{application.amount_requested:,.2f}"
        status = application.status
        status_display = application.get_status_display()

        try:
            with db_transaction.atomic():
                # Website audit must be written before delete — loan audit rows cascade away.
                from admin_panel.audit import mark_audit_recorded, record_audit

                record_audit(
                    "LOAN",
                    actor=request.user,
                    description=(
                        f'Deleted loan application {app_id} '
                        f'({member_name}, {product_name}, ₱{amount}, {status_display})'
                    ),
                    request=request,
                    object_type="LoanApplication",
                    object_id=app_id,
                    metadata={
                        "member": member_name,
                        "product": product_name,
                        "amount": amount,
                        "status": status,
                    },
                )
                mark_audit_recorded(request)
                application.delete()
        except Exception:
            return JsonResponse(
                {
                    "success": False,
                    "error": (
                        "Could not delete this loan application. "
                        "It may still be linked to other records."
                    ),
                },
                status=400,
            )

        return JsonResponse(
            {
                "success": True,
                "message": f'Loan application for "{member_name}" deleted successfully.',
            }
        )
