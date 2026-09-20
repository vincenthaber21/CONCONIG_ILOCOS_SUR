"""Staff views for share capital products and member paid-up capital."""

from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, UpdateView, View

from helper.login_helper import is_cashier_or_admin
from members.models import Member, ShareCapitalTransaction

from . import forms, models, services


def _is_share_capital_staff(user):
    return bool(user and user.is_authenticated and (user.is_superuser or is_cashier_or_admin(user)))


class ShareCapitalStaffMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not _is_share_capital_staff(request.user):
            raise PermissionDenied("Staff access is required for share capital management.")
        return super().dispatch(request, *args, **kwargs)


class ShareCapitalOverviewView(ShareCapitalStaffMixin, View):
    template_name = "share_capital/overview.html"

    def get(self, request):
        search_query = (request.GET.get("search") or "").strip()
        balance_filter = (request.GET.get("balance") or "all").strip().lower()
        if balance_filter not in {"all", "with_balance", "zero"}:
            balance_filter = "all"

        members_qs = (
            Member.objects.filter(is_active=True, member_role__slug="member")
            .select_related("member_status")
            .order_by("last_name", "first_name")
        )
        if balance_filter == "with_balance":
            members_qs = members_qs.filter(share_capital__gt=0)
        elif balance_filter == "zero":
            members_qs = members_qs.filter(share_capital__lte=0)
        if search_query:
            members_qs = members_qs.filter(
                Q(first_name__icontains=search_query)
                | Q(last_name__icontains=search_query)
                | Q(username__icontains=search_query)
                | Q(email__icontains=search_query)
                | Q(rfid_card_number__icontains=search_query)
            )

        page = Paginator(members_qs, 25).get_page(request.GET.get("page") or 1)
        stats = Member.objects.filter(
            is_active=True,
            member_role__slug="member",
        ).aggregate(
            member_count=Count("id"),
            holders=Count("id", filter=Q(share_capital__gt=0)),
            total_capital=Sum("share_capital"),
        )
        product = models.active_share_capital_product()
        product_count = models.ShareCapitalProduct.objects.filter(is_active=True).count()
        members = list(page.object_list)
        if product:
            for member in members:
                member.share_count = product.shares_for(member.share_capital)

        return render(
            request,
            self.template_name,
            {
                "page_obj": page,
                "members": members,
                "search_query": search_query,
                "balance_filter": balance_filter,
                "holder_count": stats.get("holders") or 0,
                "member_count": stats.get("member_count") or 0,
                "total_capital": stats.get("total_capital") or Decimal("0.00"),
                "product": product,
                "product_count": product_count,
            },
        )


class ShareCapitalProductListView(ShareCapitalStaffMixin, ListView):
    model = models.ShareCapitalProduct
    template_name = "share_capital/product_list.html"
    context_object_name = "products"
    paginate_by = 25

    def get_queryset(self):
        return models.ShareCapitalProduct.objects.order_by("name")


class ShareCapitalProductCreateView(ShareCapitalStaffMixin, CreateView):
    model = models.ShareCapitalProduct
    form_class = forms.ShareCapitalProductForm
    template_name = "share_capital/product_form.html"
    success_url = reverse_lazy("share_capital:product-list")

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, f'Share capital product "{self.object.name}" created.')
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        messages.error(
            self.request,
            "Could not save. Check the highlighted fields and try again.",
        )
        return super().form_invalid(form)


class ShareCapitalProductUpdateView(ShareCapitalStaffMixin, UpdateView):
    model = models.ShareCapitalProduct
    form_class = forms.ShareCapitalProductForm
    template_name = "share_capital/product_form.html"
    success_url = reverse_lazy("share_capital:product-list")

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, f'Share capital product "{self.object.name}" updated.')
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        messages.error(
            self.request,
            "Could not save. Check the highlighted fields and try again.",
        )
        return super().form_invalid(form)


class ShareCapitalContributeView(ShareCapitalStaffMixin, View):
    template_name = "share_capital/contribute_form.html"

    def _form_context(self, form, product):
        members = form.fields["member"].queryset.only(
            "pk",
            "first_name",
            "last_name",
            "middle_name",
            "share_capital",
        )
        member_meta = {
            str(m.pk): {
                "share_capital": str(m.share_capital or Decimal("0.00")),
                "name": m.full_name,
            }
            for m in members
        }
        min_contribution = Decimal("0.00")
        max_paid_up = None
        par_value = None
        if product:
            min_contribution = product.min_contribution or product.min_paid_up or Decimal("0.00")
            max_paid_up = product.max_paid_up
            par_value = product.par_value
        return {
            "form": form,
            "product": product,
            "member_meta": member_meta,
            "min_contribution": min_contribution,
            "max_paid_up": max_paid_up,
            "par_value": par_value,
        }

    def get(self, request):
        product = models.active_share_capital_product()
        form = forms.ShareCapitalContributeForm(product=product)
        return render(request, self.template_name, self._form_context(form, product))

    def post(self, request):
        product = models.active_share_capital_product()
        form = forms.ShareCapitalContributeForm(request.POST, product=product)
        if form.is_valid():
            try:
                txn = services.post_deposit(
                    member=form.cleaned_data["member"],
                    amount=form.cleaned_data["amount"],
                    performed_by=request.user,
                    notes=form.cleaned_data.get("notes") or "",
                    product=product,
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(
                    request,
                    f"Posted ₱{txn.amount:,.2f} share capital for {txn.member.full_name}.",
                )
                return redirect("share_capital:member-detail", pk=txn.member.pk)
        return render(
            request,
            self.template_name,
            self._form_context(form, product),
        )


class ShareCapitalMemberDetailView(ShareCapitalStaffMixin, View):
    template_name = "share_capital/member_detail.html"

    def get(self, request, pk):
        member = get_object_or_404(
            Member.objects.select_related("member_status"),
            pk=pk,
        )
        product = models.active_share_capital_product()
        ledger = ShareCapitalTransaction.objects.filter(member=member).select_related(
            "performed_by"
        )[:50]
        shares = product.shares_for(member.share_capital) if product else None
        min_contribution = Decimal("0.00")
        max_paid_up = None
        par_value = None
        if product:
            min_contribution = product.min_contribution or product.min_paid_up or Decimal("0.00")
            max_paid_up = product.max_paid_up
            par_value = product.par_value
        return render(
            request,
            self.template_name,
            {
                "member": member,
                "product": product,
                "movement_form": forms.ShareCapitalMovementForm(),
                "ledger": ledger,
                "shares": shares,
                "can_withdraw": product is None or product.allows_withdrawal,
                "min_contribution": min_contribution,
                "max_paid_up": max_paid_up,
                "par_value": par_value,
            },
        )


@method_decorator(require_POST, name="dispatch")
class ShareCapitalMemberMoveView(ShareCapitalStaffMixin, View):
    def post(self, request, pk):
        member = get_object_or_404(Member, pk=pk)
        form = forms.ShareCapitalMovementForm(request.POST)
        action = (request.POST.get("action") or "deposit").strip().lower()
        product = models.active_share_capital_product()
        if not form.is_valid():
            messages.error(request, "Enter a valid amount.")
            return redirect("share_capital:member-detail", pk=member.pk)
        try:
            if action == "withdraw":
                txn = services.post_withdrawal(
                    member=member,
                    amount=form.cleaned_data["amount"],
                    performed_by=request.user,
                    notes=form.cleaned_data.get("notes") or "",
                    product=product,
                )
                messages.success(
                    request,
                    f"Withdrew ₱{txn.amount:,.2f} from {member.full_name}'s share capital.",
                )
            else:
                txn = services.post_deposit(
                    member=member,
                    amount=form.cleaned_data["amount"],
                    performed_by=request.user,
                    notes=form.cleaned_data.get("notes") or "",
                    product=product,
                )
                messages.success(
                    request,
                    f"Posted ₱{txn.amount:,.2f} share capital for {member.full_name}.",
                )
        except ValidationError as exc:
            messages.error(
                request,
                " ".join(exc.messages) if hasattr(exc, "messages") else str(exc),
            )
        return redirect("share_capital:member-detail", pk=member.pk)
