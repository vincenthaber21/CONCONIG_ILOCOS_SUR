"""Staff views for savings products and member savings accounts."""

from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction as db_transaction
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, DetailView, ListView, UpdateView, View

from helper.login_helper import is_admin_user, is_cashier_or_admin

from helper.receipt_helper import get_receipt_store_context

from . import exports, forms, models, services
from .policy import regular_savings_policy


def _is_savings_staff(user):
    return bool(user and user.is_authenticated and (user.is_superuser or is_cashier_or_admin(user)))


def _store_profile():
    try:
        from admin_panel.models import StoreProfile

        return StoreProfile.get()
    except Exception:
        return None


def _receipt_context(request, account, transactions, *, single=False, txn=None, back_url=None):
    member = account.member
    ctx = {
        "account": account,
        "transactions": transactions,
        "txn": txn,
        "single": single,
        "member_name": member.full_name,
        "back_url": back_url or reverse("savings:account-detail", kwargs={"pk": account.pk}),
    }
    ctx.update(get_receipt_store_context(request))
    return ctx


class SavingsStaffMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not _is_savings_staff(request.user):
            raise PermissionDenied("Staff access is required for savings management.")
        return super().dispatch(request, *args, **kwargs)


class SavingsOverviewView(SavingsStaffMixin, View):
    template_name = "savings/overview.html"

    def get(self, request):
        search_query = (request.GET.get("search") or "").strip()
        status_filter = (request.GET.get("status") or "active").strip().lower()
        valid_status = {s.value for s in models.MemberSavingsAccount.Status} | {"all"}
        if status_filter not in valid_status:
            status_filter = "active"

        accounts_qs = (
            models.MemberSavingsAccount.objects.select_related("member", "product")
            .order_by("-opened_at")
        )
        if status_filter != "all":
            accounts_qs = accounts_qs.filter(status=status_filter)
        if search_query:
            accounts_qs = accounts_qs.filter(
                Q(member__first_name__icontains=search_query)
                | Q(member__last_name__icontains=search_query)
                | Q(member__username__icontains=search_query)
                | Q(account_number__icontains=search_query)
                | Q(product__name__icontains=search_query)
            )

        page = Paginator(accounts_qs, 25).get_page(request.GET.get("page") or 1)
        active_status = models.MemberSavingsAccount.Status.ACTIVE
        stats = models.MemberSavingsAccount.objects.aggregate(
            account_count=Count("id"),
            active_count=Count("id", filter=Q(status=active_status)),
            total_balance=Sum("balance", filter=Q(status=active_status)),
        )
        product_count = models.SavingsProduct.objects.filter(is_active=True).count()

        status_choices = [("all", "All statuses"), ("active", "Active")] + [
            (s.value, s.label)
            for s in models.MemberSavingsAccount.Status
            if s.value != "active"
        ]

        today = timezone.localdate()
        export_date_from = date(today.year, today.month, 1)
        export_date_to = today
        raw_from = (request.GET.get("date_from") or "").strip()
        raw_to = (request.GET.get("date_to") or "").strip()
        try:
            export_date_from = date.fromisoformat(raw_from)
        except ValueError:
            pass
        try:
            export_date_to = date.fromisoformat(raw_to)
        except ValueError:
            pass

        return render(
            request,
            self.template_name,
            {
                "page_obj": page,
                "accounts": page.object_list,
                "search_query": search_query,
                "status_filter": status_filter,
                "status_choices": status_choices,
                "active_count": stats.get("active_count") or 0,
                "total_balance": stats.get("total_balance") or Decimal("0.00"),
                "account_count": stats.get("account_count") or 0,
                "product_count": product_count,
                "savings_policy": regular_savings_policy(),
                "export_date_from": export_date_from.isoformat(),
                "export_date_to": export_date_to.isoformat(),
                "is_admin_user": is_admin_user(request.user),
            },
        )


class SavingsProductListView(SavingsStaffMixin, ListView):
    model = models.SavingsProduct
    template_name = "savings/savingsproduct_list.html"
    context_object_name = "products"
    paginate_by = 25

    def get_queryset(self):
        return models.SavingsProduct.objects.annotate(account_count=Count("accounts")).order_by("name")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["savings_policy"] = regular_savings_policy()
        return ctx


class SavingsProductCreateView(SavingsStaffMixin, CreateView):
    model = models.SavingsProduct
    form_class = forms.SavingsProductForm
    template_name = "savings/savingsproduct_form.html"
    success_url = reverse_lazy("savings:product-list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["savings_policy"] = regular_savings_policy()
        return ctx

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, f'Regular Savings "{self.object.name}" created.')
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        messages.error(
            self.request,
            "Could not save. Check the highlighted fields and try again.",
        )
        return super().form_invalid(form)


class SavingsProductUpdateView(SavingsStaffMixin, UpdateView):
    model = models.SavingsProduct
    form_class = forms.SavingsProductForm
    template_name = "savings/savingsproduct_form.html"
    success_url = reverse_lazy("savings:product-list")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["savings_policy"] = regular_savings_policy()
        return ctx

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, f'Regular Savings "{self.object.name}" updated.')
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        messages.error(
            self.request,
            "Could not save. Check the highlighted fields and try again.",
        )
        return super().form_invalid(form)


class OpenSavingsAccountView(SavingsStaffMixin, View):
    template_name = "savings/account_form.html"

    def get(self, request):
        return render(
            request,
            self.template_name,
            {
                "form": forms.OpenSavingsAccountForm(),
                "savings_policy": regular_savings_policy(),
            },
        )

    def post(self, request):
        form = forms.OpenSavingsAccountForm(request.POST)
        if form.is_valid():
            try:
                account = services.open_account(
                    member=form.cleaned_data["member"],
                    product=form.cleaned_data["product"],
                    opening_amount=form.cleaned_data["opening_amount"],
                    performed_by=request.user,
                    notes=form.cleaned_data.get("notes") or "",
                    opening_date=form.cleaned_data.get("opening_date"),
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(
                    request,
                    f"Opened {account.account_number} for {account.member.full_name}.",
                )
                opening = account.transactions.filter(
                    transaction_type=models.SavingsTransaction.TxnType.OPENING
                ).first()
                if opening:
                    return redirect(
                        "savings:transaction-receipt",
                        pk=account.pk,
                        txn_id=opening.pk,
                    )
                return redirect("savings:account-detail", pk=account.pk)
        return render(
            request,
            self.template_name,
            {"form": form, "savings_policy": regular_savings_policy()},
        )


class SavingsAccountDetailView(SavingsStaffMixin, DetailView):
    model = models.MemberSavingsAccount
    template_name = "savings/account_detail.html"
    context_object_name = "account"

    def get_queryset(self):
        return models.MemberSavingsAccount.objects.select_related(
            "member",
            "member__member_status",
            "product",
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        posted = services.auto_credit_due_interest(
            account=self.object,
            performed_by=self.request.user,
        )
        if posted:
            self.object.refresh_from_db()
            last = posted[-1]
            if len(posted) == 1:
                messages.success(
                    self.request,
                    f"Automatic interest of ₱{last.amount:,.2f} credited.",
                )
            else:
                total = sum((txn.amount for txn in posted), Decimal("0.00"))
                messages.success(
                    self.request,
                    f"Automatic interest: {len(posted)} credits totaling ₱{total:,.2f}.",
                )
        ctx["movement_form"] = forms.SavingsMovementForm()
        ctx["close_form"] = forms.CloseSavingsAccountForm()
        ctx["ledger"] = self.object.transactions.select_related("performed_by")[:50]
        ctx["can_close"] = (
            self.object.status != models.MemberSavingsAccount.Status.CLOSED
        )
        ctx["savings_policy"] = regular_savings_policy()
        ctx["interest"] = services.interest_snapshot(self.object)
        return ctx


class SavingsAccountCloseView(SavingsStaffMixin, View):
    """Close a savings account; optionally set Resign status (member stays active)."""

    def post(self, request, pk):
        account = get_object_or_404(
            models.MemberSavingsAccount.objects.select_related("member", "product"),
            pk=pk,
        )
        form = forms.CloseSavingsAccountForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Could not close this account. Check the form and try again.")
            return redirect("savings:account-detail", pk=account.pk)
        try:
            closed, payout = services.close_account(
                account=account,
                performed_by=request.user,
                notes=form.cleaned_data.get("notes") or "",
                mark_member_resign=bool(form.cleaned_data.get("mark_member_resign")),
            )
        except ValidationError as exc:
            messages.error(
                request,
                " ".join(exc.messages) if hasattr(exc, "messages") else str(exc),
            )
            return redirect("savings:account-detail", pk=account.pk)

        extra = f" Remaining ₱{payout.amount:,.2f} was withdrawn." if payout else ""
        barred = " Member cannot open a savings account again."
        if form.cleaned_data.get("mark_member_resign"):
            messages.success(
                request,
                f"Closed {closed.account_number}.{extra}{barred} "
                "Member status set to Resign (savings only); "
                "other services remain available.",
            )
        else:
            messages.success(request, f"Closed {closed.account_number}.{extra}{barred}")
        if payout:
            return redirect("savings:transaction-receipt", pk=closed.pk, txn_id=payout.pk)
        return redirect("savings:account-detail", pk=closed.pk)


@method_decorator(require_POST, name="dispatch")
class SavingsAccountDeleteView(LoginRequiredMixin, View):
    """Permanently delete a savings account. Admin role only; written to audit trail."""

    def post(self, request, pk):
        if not is_admin_user(request.user):
            return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

        account = get_object_or_404(
            models.MemberSavingsAccount.objects.select_related("member", "product"),
            pk=pk,
        )

        account_id = str(account.pk)
        account_number = account.account_number or account_id
        member_name = account.member.full_name if account.member_id else "Unknown"
        product_name = account.product.name if account.product_id else ""
        balance = f"{account.balance:,.2f}"
        status = account.status
        status_display = account.get_status_display()

        try:
            with db_transaction.atomic():
                from admin_panel.audit import mark_audit_recorded, record_audit

                record_audit(
                    "SAVINGS",
                    actor=request.user,
                    description=(
                        f'Deleted savings account {account_number} '
                        f'({member_name}, {product_name}, ₱{balance}, {status_display})'
                    ),
                    request=request,
                    object_type="MemberSavingsAccount",
                    object_id=account_id,
                    metadata={
                        "account_number": account_number,
                        "member": member_name,
                        "product": product_name,
                        "balance": balance,
                        "status": status,
                    },
                )
                mark_audit_recorded(request)
                account.delete()
        except Exception:
            return JsonResponse(
                {
                    "success": False,
                    "error": (
                        "Could not delete this savings account. "
                        "It may still be linked to other records."
                    ),
                },
                status=400,
            )

        return JsonResponse(
            {
                "success": True,
                "message": f'Savings account {account_number} deleted successfully.',
            }
        )


class SavingsAccountMoveView(SavingsStaffMixin, View):
    def post(self, request, pk):
        account = get_object_or_404(
            models.MemberSavingsAccount.objects.select_related("product", "member"),
            pk=pk,
        )
        form = forms.SavingsMovementForm(request.POST)
        action = (request.POST.get("action") or "deposit").strip().lower()
        if not form.is_valid():
            messages.error(request, "Enter a valid amount.")
            return redirect("savings:account-detail", pk=account.pk)
        try:
            if action == "withdraw":
                txn = services.withdraw(
                    account=account,
                    amount=form.cleaned_data["amount"],
                    performed_by=request.user,
                    notes=form.cleaned_data.get("notes") or "",
                )
                messages.success(request, "Withdrawal posted. Member receipt is ready to print.")
            else:
                txn = services.deposit(
                    account=account,
                    amount=form.cleaned_data["amount"],
                    performed_by=request.user,
                    notes=form.cleaned_data.get("notes") or "",
                )
                messages.success(request, "Deposit posted. Member receipt is ready to print.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
            return redirect("savings:account-detail", pk=account.pk)
        return redirect("savings:transaction-receipt", pk=account.pk, txn_id=txn.pk)


class SavingsAccountCreditInterestView(SavingsStaffMixin, View):
    """Credit annual interest that is already due on this account."""

    def post(self, request, pk):
        account = get_object_or_404(
            models.MemberSavingsAccount.objects.select_related("product", "member"),
            pk=pk,
        )
        try:
            posted = services.credit_due_interest(
                account=account,
                performed_by=request.user,
            )
        except ValidationError as exc:
            messages.error(
                request,
                " ".join(exc.messages) if hasattr(exc, "messages") else str(exc),
            )
            return redirect("savings:account-detail", pk=account.pk)
        last = posted[-1]
        if len(posted) == 1:
            messages.success(
                request,
                f"Interest of ₱{last.amount:,.2f} credited. Member receipt is ready to print.",
            )
        else:
            total = sum((txn.amount for txn in posted), Decimal("0.00"))
            messages.success(
                request,
                f"{len(posted)} interest credits totaling ₱{total:,.2f} posted. Member receipt is ready to print.",
            )
        return redirect("savings:transaction-receipt", pk=account.pk, txn_id=last.pk)


class SavingsTransactionReceiptView(SavingsStaffMixin, View):
    """Printable member receipt for one savings ledger movement."""

    template_name = "savings/transaction_receipt.html"

    def get(self, request, pk, txn_id):
        account = get_object_or_404(
            models.MemberSavingsAccount.objects.select_related("member", "product"),
            pk=pk,
        )
        txn = get_object_or_404(
            models.SavingsTransaction.objects.select_related("performed_by", "account"),
            pk=txn_id,
            account=account,
        )
        return render(
            request,
            self.template_name,
            _receipt_context(request, account, [txn], single=True, txn=txn),
        )


class SavingsReceiptBatchView(SavingsStaffMixin, View):
    """Printable member receipts for every movement on a savings account."""

    template_name = "savings/transaction_receipt.html"

    def get(self, request, pk):
        account = get_object_or_404(
            models.MemberSavingsAccount.objects.select_related("member", "product"),
            pk=pk,
        )
        transactions = list(
            account.transactions.select_related("performed_by").order_by("created_at", "id")
        )
        return render(
            request,
            self.template_name,
            _receipt_context(request, account, transactions, single=False),
        )


class SavingsInterestExportView(SavingsStaffMixin, View):
    """Download all members' savings interest rates / credits as Excel or PDF."""

    def get(self, request):
        date_from, date_to, range_start, range_end = exports.parse_export_dates(request)
        fmt = (request.GET.get("format") or "excel").strip().lower()
        if fmt not in ("excel", "pdf"):
            fmt = "excel"

        rows = exports.build_interest_report_rows(
            date_from=date_from,
            date_to=date_to,
            range_start=range_start,
            range_end=range_end,
        )
        user_label = request.user.get_full_name() or request.user.username
        if fmt == "pdf":
            return exports.render_interest_pdf(
                rows=rows,
                date_from=date_from,
                date_to=date_to,
                user_label=user_label,
            )
        return exports.render_interest_excel(
            rows=rows,
            date_from=date_from,
            date_to=date_to,
            user_label=user_label,
        )
