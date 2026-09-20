"""Class-based views implementing the loan origination pipeline."""

from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, TemplateView, View
from django_fsm import TransitionNotAllowed

from accounts.models import User
from . import forms, models, services

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


class RoleRequiredMixin:
    """Restrict a view to users with one of the given roles (or superusers)."""

    allowed_roles = ()

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_superuser and self.allowed_roles:
            if getattr(request.user, "role", None) not in self.allowed_roles:
                raise PermissionDenied("You do not have the required role for this action.")
        return super().dispatch(request, *args, **kwargs)


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


class LoanApplicationCreateView(LoginRequiredMixin, CreateView):
    model = models.LoanApplication
    form_class = forms.LoanApplicationForm
    template_name = "loans/loanapplication_form.html"

    def form_valid(self, form):
        form.instance.member = self.request.user
        response = super().form_valid(form)
        document_files = self.request.FILES.getlist("documents")
        for uploaded_file in document_files:
            models.SubmittedDocument.objects.create(
                application=self.object,
                document_type=uploaded_file.name,
                file=uploaded_file,
            )
        try:
            self.object.submit()
            self.object.save(update_fields=["status", "submitted_at"])
            messages.success(self.request, "Loan application submitted successfully.")
        except TransitionNotAllowed:
            messages.warning(self.request, "Application saved as draft.")
        return response

    def get_success_url(self):
        return reverse("loans:application-detail", kwargs={"pk": self.object.pk})


# ---------------------------------------------------------------------------
# Underwriting pipeline
# ---------------------------------------------------------------------------


class EligibilityVerificationView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "loans.can_verify"
    template_name = "loans/eligibilityverification_form.html"

    def get(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = getattr(application, "eligibility_verification", None)
        form = forms.EligibilityVerificationForm(instance=instance)
        return self._render(request, application, form)

    def post(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = getattr(application, "eligibility_verification", None)
        form = forms.EligibilityVerificationForm(request.POST, instance=instance)
        if form.is_valid():
            verification = form.save(commit=False)
            verification.application = application
            verification.verified_by = request.user
            verification.verified_at = timezone.now()
            verification.save()

            if application.status == models.LoanApplication.Status.SUBMITTED:
                application.begin_verification()
            application.complete_verification(verification.passed)
            application.save(update_fields=["status"])

            messages.success(request, "Eligibility verification recorded.")
            return redirect("loans:application-detail", pk=application.pk)
        return self._render(request, application, form)

    def _render(self, request, application, form):
        from django.shortcuts import render

        return render(
            request,
            self.template_name,
            {"application": application, "form": form},
        )


class CreditInvestigationView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "loans.can_investigate"
    template_name = "loans/creditinvestigation_form.html"

    def get(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = getattr(application, "credit_investigation", None)
        form = forms.CreditInvestigationForm(instance=instance)
        return self._render(request, application, form)

    def post(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = getattr(application, "credit_investigation", None)
        form = forms.CreditInvestigationForm(request.POST, instance=instance)
        if form.is_valid():
            investigation = form.save(commit=False)
            investigation.application = application
            investigation.evaluated_by = request.user
            investigation.evaluated_at = timezone.now()
            investigation.save()

            application.submit_for_committee()
            application.save(update_fields=["status"])

            messages.success(request, "Credit investigation recorded.")
            return redirect("loans:application-detail", pk=application.pk)
        return self._render(request, application, form)

    def _render(self, request, application, form):
        from django.shortcuts import render

        return render(
            request,
            self.template_name,
            {"application": application, "form": form},
        )


class CommitteeReviewView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "loans.can_approve"
    template_name = "loans/committeereview_form.html"

    def get(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = getattr(application, "committee_review", None)
        form = forms.CommitteeReviewForm(instance=instance)
        return self._render(request, application, form)

    def post(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = getattr(application, "committee_review", None)
        form = forms.CommitteeReviewForm(request.POST, instance=instance)
        if form.is_valid():
            review = form.save(commit=False)
            review.application = application
            review.decision_date = timezone.now()
            review.save()
            form.save_m2m()

            if review.decision == models.CommitteeReview.Decision.APPROVED:
                application.approve()
            else:
                application.reject()
            application.save(update_fields=["status"])

            messages.success(request, "Committee decision recorded.")
            return redirect("loans:application-detail", pk=application.pk)
        return self._render(request, application, form)

    def _render(self, request, application, form):
        from django.shortcuts import render

        return render(
            request,
            self.template_name,
            {"application": application, "form": form},
        )


class InsuranceEnrollmentView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "loans.can_approve"
    template_name = "loans/insuranceenrollment_form.html"

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

            application.enroll_insurance()
            application.save(update_fields=["status"])

            messages.success(request, "Insurance enrollment recorded.")
            return redirect("loans:application-detail", pk=application.pk)
        return self._render(request, application, form)

    def _render(self, request, application, form):
        from django.shortcuts import render

        return render(
            request,
            self.template_name,
            {"application": application, "form": form},
        )


class LoanDocumentationView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "loans.can_approve"
    template_name = "loans/loandocumentation_form.html"

    def get(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = getattr(application, "documentation", None)
        form = forms.LoanDocumentationForm(instance=instance)
        return self._render(request, application, form)

    def post(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = getattr(application, "documentation", None)
        form = forms.LoanDocumentationForm(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            documentation = form.save(commit=False)
            documentation.application = application
            documentation.save()

            application.sign_documents()
            application.save(update_fields=["status"])

            messages.success(request, "Loan documentation signed.")
            return redirect("loans:application-detail", pk=application.pk)
        return self._render(request, application, form)

    def _render(self, request, application, form):
        from django.shortcuts import render

        return render(
            request,
            self.template_name,
            {"application": application, "form": form},
        )


class DisbursementView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "loans.can_disburse"
    template_name = "loans/disbursement_form.html"

    def get(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = getattr(application, "disbursement", None)
        form = forms.DisbursementForm(instance=instance)
        return self._render(request, application, form)

    def post(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = getattr(application, "disbursement", None)
        form = forms.DisbursementForm(request.POST, instance=instance)
        if form.is_valid():
            disbursement = form.save(commit=False)
            disbursement.application = application
            disbursement.disbursed_by = request.user
            disbursement.disbursement_date = timezone.now()
            disbursement.save()

            application.disburse()
            application.save(update_fields=["status"])

            services.generate_amortization_schedule(application)

            messages.success(request, "Loan disbursed and activated.")
            return redirect("loans:application-detail", pk=application.pk)
        return self._render(request, application, form)

    def _render(self, request, application, form):
        from django.shortcuts import render

        return render(
            request,
            self.template_name,
            {"application": application, "form": form},
        )


class PaymentOptionSelectView(LoginRequiredMixin, View):
    template_name = "loans/paymentoption_form.html"

    def get(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = getattr(application, "payment_option", None)
        form = forms.PaymentOptionForm(instance=instance)
        return self._render(request, application, form)

    def post(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        instance = getattr(application, "payment_option", None)
        form = forms.PaymentOptionForm(request.POST, instance=instance)
        if form.is_valid():
            option = form.save(commit=False)
            option.application = application
            option.selected_at = timezone.now()
            option.save()

            if option.option == models.PaymentOption.Option.MONTHLY_AMORTIZATION:
                services.generate_amortization_schedule(application)
            else:
                models.LumpSumPayoff.objects.update_or_create(
                    application=application,
                    defaults={
                        "maturity_date": timezone.localdate()
                        + timedelta(days=30 * application.term_months),
                        "total_amount_due": application.amount_requested,
                    },
                )

            messages.success(request, "Payment option saved.")
            return redirect("loans:application-detail", pk=application.pk)
        return self._render(request, application, form)

    def _render(self, request, application, form):
        from django.shortcuts import render

        return render(
            request,
            self.template_name,
            {"application": application, "form": form},
        )


class PaymentCollectionView(LoginRequiredMixin, PermissionRequiredMixin, View):
    permission_required = "loans.can_collect_payment"
    template_name = "loans/payment_list.html"

    def get(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        form = forms.PaymentForm(application=application)
        return self._render(request, application, form)

    def post(self, request, pk):
        application = get_object_or_404(models.LoanApplication, pk=pk)
        form = forms.PaymentForm(request.POST, application=application)
        if form.is_valid():
            services.record_payment(
                application=application,
                amount=form.cleaned_data["amount_paid"],
                collected_by=request.user,
                payment_method=form.cleaned_data["payment_method"],
                or_number=form.cleaned_data.get("or_number", ""),
                remarks=form.cleaned_data.get("remarks", ""),
            )
            messages.success(request, "Payment recorded.")
            return redirect("loans:payment-collect", pk=application.pk)
        return self._render(request, application, form)

    def _render(self, request, application, form):
        from django.shortcuts import render

        return render(
            request,
            self.template_name,
            {
                "application": application,
                "form": form,
                "payments": application.payments.all(),
                "outstanding_balance": application.total_outstanding_balance(),
            },
        )


# ---------------------------------------------------------------------------
# Read views
# ---------------------------------------------------------------------------


class LoanApplicationDetailView(LoginRequiredMixin, DetailView):
    model = models.LoanApplication
    template_name = "loans/loanapplication_detail.html"
    context_object_name = "application"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        application = self.object
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

        context["pipeline_steps"] = steps
        context["outstanding_balance"] = application.total_outstanding_balance()
        return context


class LoanApplicationListView(LoginRequiredMixin, ListView):
    model = models.LoanApplication
    template_name = "loans/loanapplication_list.html"
    context_object_name = "applications"
    paginate_by = 25

    def get_queryset(self):
        queryset = super().get_queryset().select_related("member", "loan_product")
        user = self.request.user
        if user.role == User.Role.MEMBER and not user.is_superuser:
            queryset = queryset.filter(member=user)
        return queryset


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "dashboard.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        status_counts = dict(
            models.LoanApplication.objects.values_list("status").annotate(count=Count("id"))
        )
        funnel_labels = [label for _, label in PIPELINE_STEPS]
        funnel_values = [status_counts.get(key, 0) for key, _ in PIPELINE_STEPS]

        today = timezone.localdate()
        month_start = today.replace(day=1)
        total_disbursed_this_month = (
            models.Disbursement.objects.filter(disbursement_date__date__gte=month_start)
            .aggregate(total=Sum("amount_released"))
            .get("total")
            or 0
        )

        active_loans_count = models.LoanApplication.objects.filter(
            status=models.LoanApplication.Status.ACTIVE
        ).count()
        delinquent_loans_count = (
            models.DelinquencyRecord.objects.filter(resolved=False)
            .values("application")
            .distinct()
            .count()
        )
        delinquency_rate = (
            round((delinquent_loans_count / active_loans_count) * 100, 1)
            if active_loans_count
            else 0
        )

        context.update(
            {
                "funnel_labels": funnel_labels,
                "funnel_values": funnel_values,
                "total_disbursed_this_month": total_disbursed_this_month,
                "active_loans_count": active_loans_count,
                "delinquent_loans_count": delinquent_loans_count,
                "delinquency_rate": delinquency_rate,
                "total_applications": models.LoanApplication.objects.count(),
            }
        )
        return context
