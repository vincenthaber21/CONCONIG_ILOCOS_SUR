"""Staff views for palay trade products (features) and trade tickets."""

from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Case, Count, F, IntegerField, Q, Sum, Value, When
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_http_methods, require_POST
from django.views.generic import DetailView, UpdateView, View

from helper.login_helper import is_admin_user, is_cashier_or_admin

from helper.receipt_helper import get_receipt_store_context
from members.models import Member

from . import credit_services, forms, models, reports, services


def _is_palay_staff(user):
    return bool(user and user.is_authenticated and (user.is_superuser or is_cashier_or_admin(user)))


def _parse_date(value):
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


def _apply_date_range(qs, date_from, date_to):
    if date_from:
        start = datetime.combine(date_from, time.min)
        if timezone.is_naive(start):
            start = timezone.make_aware(start)
        qs = qs.filter(traded_at__gte=start)
    if date_to:
        end = datetime.combine(date_to + timedelta(days=1), time.min)
        if timezone.is_naive(end):
            end = timezone.make_aware(end)
        qs = qs.filter(traded_at__lt=end)
    return qs


def _store_profile():
    try:
        from admin_panel.models import StoreProfile

        return StoreProfile.get()
    except Exception:
        return None


class PalayStaffMixin(LoginRequiredMixin):
    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not _is_palay_staff(request.user):
            raise PermissionDenied("Staff access is required for palay trade management.")
        return super().dispatch(request, *args, **kwargs)


class PalayTradeOverviewView(PalayStaffMixin, View):
    template_name = "palay_trade/overview.html"

    def get(self, request):
        search_query = (request.GET.get("search") or "").strip()
        type_filter = (request.GET.get("trade_type") or "all").strip().lower()
        date_from = _parse_date(request.GET.get("date_from"))
        date_to = _parse_date(request.GET.get("date_to"))
        if date_from and date_to and date_to < date_from:
            date_from, date_to = date_to, date_from

        valid_types = {t.value for t in models.PalayTrade.TradeType} | {"all"}
        if type_filter not in valid_types:
            type_filter = "all"

        trades_qs = (
            models.PalayTrade.objects.select_related(
                "member", "product", "product__variety", "performed_by"
            )
            .filter(status=models.PalayTrade.Status.POSTED)
            .order_by("-traded_at")
        )
        trades_qs = _apply_date_range(trades_qs, date_from, date_to)
        if type_filter != "all":
            trades_qs = trades_qs.filter(trade_type=type_filter)
        if search_query:
            trades_qs = trades_qs.filter(
                Q(party_name__icontains=search_query)
                | Q(reference__icontains=search_query)
                | Q(product__name__icontains=search_query)
                | Q(product__variety__name__icontains=search_query)
                | Q(member__first_name__icontains=search_query)
                | Q(member__last_name__icontains=search_query)
            )

        page = Paginator(trades_qs, 25).get_page(request.GET.get("page") or 1)

        # KPI cards follow the same date (+ optional type) filter as the list.
        posted = _apply_date_range(
            models.PalayTrade.objects.filter(status=models.PalayTrade.Status.POSTED),
            date_from,
            date_to,
        )
        if type_filter != "all":
            posted = posted.filter(trade_type=type_filter)

        buy_totals = posted.filter(trade_type=models.PalayTrade.TradeType.BUY).aggregate(
            kg=Sum("net_kg"),
            amount=Sum("net_amount"),
            count=Count("id"),
        )
        sell_totals = posted.filter(trade_type=models.PalayTrade.TradeType.SELL).aggregate(
            kg=Sum("net_kg"),
            amount=Sum("net_amount"),
            count=Count("id"),
        )
        all_totals = posted.aggregate(
            kg=Sum("net_kg"),
            amount=Sum("net_amount"),
            count=Count("id"),
        )
        product_count = models.PalayTradeProduct.objects.filter(
            is_active=True, code__in=models.DEFAULT_PRODUCT_CODES
        ).count()
        stock_totals = models.PalayTradeProduct.objects.filter(
            is_active=True, code__in=models.DEFAULT_PRODUCT_CODES
        ).aggregate(
            total_stock=Sum("stock_kg"),
            low_count=Count("id", filter=Q(low_stock_kg__gt=0, stock_kg__lte=F("low_stock_kg"))),
        )
        rice_products = (
            models.PalayTradeProduct.active_trade_products()
            .select_related("variety")
            .annotate(trade_count=Count("trades"))
        )

        if date_from and date_to:
            date_label = f"{date_from:%b %d, %Y} — {date_to:%b %d, %Y}"
        elif date_from:
            date_label = f"From {date_from:%b %d, %Y}"
        elif date_to:
            date_label = f"Until {date_to:%b %d, %Y}"
        else:
            date_label = "All dates"

        if type_filter == "buy":
            filter_scope = "Buys"
        elif type_filter == "sell":
            filter_scope = "Sells"
        else:
            filter_scope = "All trades"

        return render(
            request,
            self.template_name,
            {
                "page_obj": page,
                "trades": page.object_list,
                "search_query": search_query,
                "type_filter": type_filter,
                "date_from": date_from.isoformat() if date_from else "",
                "date_to": date_to.isoformat() if date_to else "",
                "date_label": date_label,
                "filter_scope": filter_scope,
                "has_date_filter": bool(date_from or date_to),
                "buy_count": buy_totals.get("count") or 0,
                "buy_kg": buy_totals.get("kg") or Decimal("0.00"),
                "buy_amount": buy_totals.get("amount") or Decimal("0.00"),
                "sell_count": sell_totals.get("count") or 0,
                "sell_kg": sell_totals.get("kg") or Decimal("0.00"),
                "sell_amount": sell_totals.get("amount") or Decimal("0.00"),
                "total_net_amount": all_totals.get("amount") or Decimal("0.00"),
                "total_net_kg": all_totals.get("kg") or Decimal("0.00"),
                "total_trade_count": all_totals.get("count") or 0,
                "product_count": product_count,
                "total_rice_stock": stock_totals.get("total_stock") or Decimal("0.00"),
                "low_stock_count": stock_totals.get("low_count") or 0,
                "rice_products": rice_products,
                "credit_settings": models.PalayCreditSettings.get(),
                "open_credit_count": credit_services.open_palay_credit_trades().count(),
            },
        )


class PalayTradeProductFeaturesListView(PalayStaffMixin, View):
    """Rice Palay and Bigas product features — rates, stock, and trade limits."""

    template_name = "palay_trade/product_features_list.html"

    def get(self, request):
        models.PalayTradeProduct.ensure_default_products()
        products = list(
            models.PalayTradeProduct.objects.filter(code__in=models.DEFAULT_PRODUCT_CODES)
            .select_related("variety")
            .annotate(trade_count=Count("trades"))
            .order_by(
                Case(
                    When(code="rice-palay", then=Value(0)),
                    When(code="bigas", then=Value(1)),
                    default=Value(99),
                    output_field=IntegerField(),
                ),
                "name",
            )
        )
        stock_totals = models.PalayTradeProduct.objects.filter(
            is_active=True, code__in=models.DEFAULT_PRODUCT_CODES
        ).aggregate(
            total_stock=Sum("stock_kg"),
            low_count=Count("id", filter=Q(low_stock_kg__gt=0, stock_kg__lte=F("low_stock_kg"))),
        )
        return render(
            request,
            self.template_name,
            {
                "products": products,
                "total_rice_stock": stock_totals.get("total_stock") or Decimal("0.00"),
                "low_stock_count": stock_totals.get("low_count") or 0,
                "credit_settings": models.PalayCreditSettings.get(),
            },
        )


class PalayCreditOverviewView(PalayStaffMixin, View):
    """Members with palay utang, open tickets, and recent settlements."""

    template_name = "palay_trade/palay_credit_overview.html"

    def get(self, request):
        search_query = (request.GET.get("search") or "").strip()
        view_tab = (request.GET.get("tab") or "members").strip().lower()
        if view_tab not in {"members", "open", "settled"}:
            view_tab = "members"

        member_rows = credit_services.members_with_open_palay_credit()
        open_qs = (
            credit_services.open_palay_credit_trades()
            .select_related("member", "product")
            .order_by("-traded_at")
        )
        settled_qs = credit_services.settled_palay_credit_trades(
            limit=50, search_query=search_query
        )
        if search_query:
            open_qs = open_qs.filter(
                Q(party_name__icontains=search_query)
                | Q(reference__icontains=search_query)
                | Q(member__first_name__icontains=search_query)
                | Q(member__last_name__icontains=search_query)
            )
            sq = search_query.lower()
            member_rows = [
                r
                for r in member_rows
                if sq in (r["party_name"] or "").lower()
                or (r["member"] and sq in (r["member"].username or "").lower())
            ]

        stats = credit_services.palay_credit_overview_stats()
        if search_query:
            filtered_open = list(open_qs)
            stats = {
                **stats,
                "ticket_count": len(filtered_open),
                "total_kg": sum((t.net_kg for t in filtered_open), Decimal("0.00")),
                "total_outstanding": sum((t.outstanding for t in filtered_open), Decimal("0.00")),
                "member_count": len(member_rows),
            }

        return render(
            request,
            self.template_name,
            {
                "search_query": search_query,
                "view_tab": view_tab,
                "stats": stats,
                "member_rows": member_rows,
                "open_trades": list(open_qs[:100]),
                "settled_trades": list(settled_qs),
                "settings_obj": models.PalayCreditSettings.get(),
                "overview_url": reverse("palay_trade:credit-overview"),
            },
        )


class PalayCreditDeskView(PalayStaffMixin, View):
    """Post member utang — rice taken from stock on palay credit."""

    template_name = "palay_trade/palay_credit_desk.html"

    def _desk_context(self, utang_form, *, search_query=""):
        settings_obj = models.PalayCreditSettings.get()
        products = list(models.PalayTradeProduct.active_trade_products())
        product_rates = {
            str(p.pk): {
                "sell": str(p.sell_price_per_kg),
                "stock": str(p.stock_kg),
                "name": p.name,
                "code": p.code,
                "credit": bool(p.credit_enabled),
            }
            for p in products
        }
        open_qs = (
            credit_services.open_palay_credit_trades()
            .select_related("member", "product")
            .order_by("-traded_at")
        )
        if search_query:
            open_qs = open_qs.filter(
                Q(party_name__icontains=search_query)
                | Q(reference__icontains=search_query)
                | Q(member__first_name__icontains=search_query)
                | Q(member__last_name__icontains=search_query)
            )
        open_trades = list(open_qs[:50])
        return {
            "utang_form": utang_form,
            "settings_obj": settings_obj,
            "products": products,
            "product_rates": product_rates,
            "open_trades": open_trades,
            "search_query": search_query,
            "credit_ready": settings_obj.is_enabled and settings_obj.allow_credit_on_sell,
        }

    def get(self, request):
        search_query = (request.GET.get("search") or "").strip()
        return render(
            request,
            self.template_name,
            self._desk_context(forms.PalayCreditUtangForm(), search_query=search_query),
        )

    def post(self, request):
        form = forms.PalayCreditUtangForm(request.POST)
        if form.is_valid():
            try:
                trade = credit_services.post_member_utang(
                    product=form.cleaned_data["product"],
                    member=form.cleaned_data["member"],
                    gross_kg=form.cleaned_data["gross_kg"],
                    performed_by=request.user,
                    notes=form.cleaned_data.get("notes") or "",
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(
                    request,
                    f"Posted utang {trade.reference} — {trade.net_kg:,.2f} kg "
                    f"({trade.product.name}) for ₱{trade.net_amount:,.2f}.",
                )
                return redirect("palay_trade:credit-desk")
        return render(request, self.template_name, self._desk_context(form))


class PalayCreditConfigureView(PalayStaffMixin, View):
    template_name = "palay_trade/palay_credit_configure.html"

    def get(self, request):
        settings_obj = models.PalayCreditSettings.get()
        products = list(
            models.PalayTradeProduct.objects.filter(code__in=models.DEFAULT_PRODUCT_CODES).order_by(
                "name"
            )
        )
        return render(
            request,
            self.template_name,
            {
                "form": forms.PalayCreditSettingsForm(instance=settings_obj),
                "settings_obj": settings_obj,
                "products": products,
            },
        )

    def post(self, request):
        settings_obj = models.PalayCreditSettings.get()
        form = forms.PalayCreditSettingsForm(request.POST, instance=settings_obj)
        products = list(
            models.PalayTradeProduct.objects.filter(code__in=models.DEFAULT_PRODUCT_CODES).order_by(
                "name"
            )
        )
        if form.is_valid():
            form.save()
            messages.success(request, "Palay credit limits saved.")
            return redirect("palay_trade:credit-settings")
        messages.error(request, "Could not save palay credit limits.")
        return render(
            request,
            self.template_name,
            {"form": form, "settings_obj": settings_obj, "products": products},
        )


class PalayCreditSettingsView(PalayCreditDeskView):
    """Backward-compatible alias for the utang desk."""

    pass


@login_required
@require_http_methods(["GET"])
def api_palay_search_members(request):
    """Typeahead search for palay credit member picker (max 10 results)."""
    if not _is_palay_staff(request.user):
        return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

    query = (request.GET.get("q") or "").strip()
    qs = forms.PalayCreditUtangForm.member_queryset()
    if query:
        if len(query) < 2:
            return JsonResponse({"success": True, "members": []})
        qs = qs.filter(
            Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(username__icontains=query)
            | Q(rfid_card_number__icontains=query)
        )

    members = qs[: forms.PalayCreditUtangForm.MEMBER_PREVIEW_LIMIT]
    return JsonResponse(
        {
            "success": True,
            "members": [
                {
                    "id": member.pk,
                    "label": forms.PalayCreditUtangForm.member_label(member),
                }
                for member in members
            ],
        }
    )


class PalayTradeProductUpdateView(PalayStaffMixin, UpdateView):
    """Edit features for the fixed Rice Palay / Bigas products."""

    model = models.PalayTradeProduct
    form_class = forms.PalayTradeProductFeaturesForm
    template_name = "palay_trade/product_features_form.html"
    success_url = reverse_lazy("palay_trade:product-list")
    context_object_name = "product"

    def get_queryset(self):
        models.PalayTradeProduct.ensure_default_products()
        return models.PalayTradeProduct.objects.filter(code__in=models.DEFAULT_PRODUCT_CODES)

    def form_valid(self, form):
        self.object = form.save()
        messages.success(
            self.request,
            f'Updated features for "{self.object.name}".',
        )
        return redirect("palay_trade:product-list")

    def form_invalid(self, form):
        messages.error(
            self.request,
            "Could not save product features. Check the highlighted fields and try again.",
        )
        return super().form_invalid(form)


class PalayTradeCreateView(PalayStaffMixin, View):
    template_name = "palay_trade/trade_form.html"

    def _context(self, form):
        products = list(models.PalayTradeProduct.active_trade_products())
        credit_settings = models.PalayCreditSettings.get()
        product_rates = {
            str(p.pk): {
                "buy": str(p.buy_price_per_kg),
                "sell": str(p.sell_price_per_kg),
                "stock": str(p.stock_kg),
                "name": p.name,
                "code": p.code,
                "low": bool(p.is_low_stock),
                "credit": bool(p.credit_enabled),
            }
            for p in products
        }
        return {
            "form": form,
            "products": products,
            "product_rates": product_rates,
            "credit_settings": credit_settings,
        }

    def get(self, request):
        credit_settings = models.PalayCreditSettings.get()
        return render(
            request,
            self.template_name,
            self._context(forms.PalayTradeForm(credit_settings=credit_settings)),
        )

    def post(self, request):
        credit_settings = models.PalayCreditSettings.get()
        form = forms.PalayTradeForm(request.POST, credit_settings=credit_settings)
        if form.is_valid():
            try:
                trade = services.post_trade(
                    product=form.cleaned_data["product"],
                    trade_type=form.cleaned_data["trade_type"],
                    party_name=form.cleaned_data["party_name"],
                    gross_kg=form.cleaned_data["gross_kg"],
                    unit_price=form.cleaned_data.get("unit_price"),
                    member=form.cleaned_data.get("member"),
                    performed_by=request.user,
                    notes=form.cleaned_data.get("notes") or "",
                    payment_method=form.cleaned_data.get("payment_method"),
                    enforce_membership_eligibility=False,
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(
                    request,
                    f"Posted {trade.reference} — {trade.get_trade_type_display()} "
                    f"{trade.net_kg:,.2f} kg for ₱{trade.net_amount:,.2f}. Receipt is ready to print.",
                )
                return redirect("palay_trade:trade-receipt", pk=trade.pk)
        return render(request, self.template_name, self._context(form))


class PalayTradeDetailView(PalayStaffMixin, DetailView):
    model = models.PalayTrade
    template_name = "palay_trade/trade_detail.html"
    context_object_name = "trade"

    def get_queryset(self):
        return models.PalayTrade.objects.select_related(
            "member", "product", "product__variety", "performed_by"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["store_profile"] = _store_profile()
        ctx["back_url"] = reverse("palay_trade:overview")
        ctx["receipt_url"] = reverse("palay_trade:trade-receipt", kwargs={"pk": self.object.pk})
        ctx["credit_outstanding"] = self.object.credit_outstanding
        return ctx


@method_decorator(require_POST, name="dispatch")
class PalayTradeDeleteView(LoginRequiredMixin, View):
    """Permanently delete a posted palay trade. Admin role only; written to audit trail."""

    def post(self, request, pk):
        if not is_admin_user(request.user):
            return JsonResponse({"success": False, "error": "Permission denied"}, status=403)

        trade = get_object_or_404(
            models.PalayTrade.objects.select_related("product", "member"),
            pk=pk,
        )

        trade_id = str(trade.pk)
        reference = trade.reference or trade_id
        party_name = trade.party_name or ""
        product_name = trade.product.name if trade.product_id else ""
        trade_type = trade.trade_type
        trade_type_display = trade.get_trade_type_display()
        net_kg = f"{trade.net_kg:,.2f}"
        net_amount = f"{trade.net_amount:,.2f}"

        try:
            from django.db import transaction as db_transaction
            from admin_panel.audit import mark_audit_recorded, record_audit

            with db_transaction.atomic():
                record_audit(
                    "PALAY",
                    actor=request.user,
                    description=(
                        f'Deleted palay trade {reference} '
                        f'({trade_type_display}, {party_name}, {product_name}, '
                        f'{net_kg} kg, ₱{net_amount})'
                    ),
                    request=request,
                    object_type="PalayTrade",
                    object_id=trade_id,
                    metadata={
                        "reference": reference,
                        "trade_type": trade_type,
                        "party": party_name,
                        "product": product_name,
                        "net_kg": net_kg,
                        "net_amount": net_amount,
                    },
                )
                mark_audit_recorded(request)
                services.delete_trade(trade, performed_by=request.user)
        except ValidationError as exc:
            message = " ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            return JsonResponse({"success": False, "error": message}, status=400)
        except Exception:
            return JsonResponse(
                {
                    "success": False,
                    "error": (
                        "Could not delete this palay trade. "
                        "It may still be linked to other records."
                    ),
                },
                status=400,
            )

        return JsonResponse(
            {
                "success": True,
                "message": f"Palay trade {reference} deleted successfully.",
            }
        )


def _parse_palay_credit_payment_amount(request):
    """Return Decimal amount from POST, or None for full settlement."""
    raw = (request.POST.get("amount") or "").strip()
    if not raw:
        return None
    try:
        amount = Decimal(raw)
    except Exception:
        raise ValidationError("Enter a valid payment amount.")
    return amount.quantize(Decimal("0.01"))


@method_decorator(require_POST, name="dispatch")
class PalayCreditSettleView(PalayStaffMixin, View):
    """Record full or partial payment for an open palay credit ticket."""

    def post(self, request, pk):
        trade = get_object_or_404(models.PalayTrade, pk=pk)
        next_url = (request.POST.get("next") or request.GET.get("next") or "").strip()
        try:
            amount = _parse_palay_credit_payment_amount(request)
            trade.refresh_from_db()
            outstanding_before = trade.credit_outstanding
            credit_services.settle_palay_credit(
                trade, amount=amount, performed_by=request.user
            )
        except ValidationError as exc:
            message = " ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            messages.error(request, message)
        else:
            trade.refresh_from_db()
            paid_now = (
                outstanding_before
                if amount is None
                else min(amount, outstanding_before)
            )
            if trade.credit_settled_at:
                messages.success(
                    request,
                    f"Palay credit for {trade.reference} fully paid (₱{paid_now:,.2f} recorded).",
                )
            else:
                messages.success(
                    request,
                    f"Partial payment of ₱{paid_now:,.2f} recorded for {trade.reference}. "
                    f"Remaining balance: ₱{trade.credit_outstanding:,.2f}.",
                )
        if next_url:
            return redirect(next_url)
        return redirect("palay_trade:trade-detail", pk=trade.pk)


@method_decorator(require_POST, name="dispatch")
class PalayCreditMemberSettleView(PalayStaffMixin, View):
    """Settle open palay credit tickets for one member (full or partial, FIFO)."""

    def post(self, request, member_id):
        member = get_object_or_404(Member, pk=member_id, is_active=True)
        next_url = (request.POST.get("next") or request.GET.get("next") or "").strip()
        try:
            amount = _parse_palay_credit_payment_amount(request)
            settled = credit_services.settle_member_palay_credit(
                member, amount=amount, performed_by=request.user
            )
        except ValidationError as exc:
            message = " ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
            messages.error(request, message)
        else:
            if amount is None:
                total = sum((t.net_amount for t in settled), Decimal("0.00"))
                messages.success(
                    request,
                    f"Settled {len(settled)} palay credit ticket(s) for {member.full_name} "
                    f"(₱{total:,.2f} total).",
                )
            else:
                fully_paid = sum(1 for t in settled if t.credit_settled_at)
                remaining = credit_services.member_palay_credit_outstanding(member)
                messages.success(
                    request,
                    f"Recorded ₱{amount:,.2f} payment for {member.full_name} "
                    f"across {len(settled)} ticket(s)"
                    f"{f' ({fully_paid} fully paid)' if fully_paid else ''}. "
                    f"Remaining balance: ₱{remaining:,.2f}.",
                )
        if next_url:
            return redirect(next_url)
        return redirect("palay_trade:credit-overview")


class PalayTradeReceiptView(PalayStaffMixin, DetailView):
    """Printable party + office copies for transparency."""

    model = models.PalayTrade
    template_name = "palay_trade/trade_receipt.html"
    context_object_name = "trade"

    def get_queryset(self):
        return models.PalayTrade.objects.select_related(
            "member", "product", "product__variety", "performed_by"
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        trade = self.object
        party_label = "Farmer / seller copy" if trade.trade_type == models.PalayTrade.TradeType.BUY else "Buyer copy"
        ctx.update(get_receipt_store_context(self.request))
        ctx["back_url"] = reverse("palay_trade:trade-detail", kwargs={"pk": trade.pk})
        ctx["copy_labels"] = [party_label, "Office / coop copy"]
        return ctx


def _filtered_trades_from_request(request):
    search_query = (request.GET.get("search") or "").strip()
    type_filter = (request.GET.get("trade_type") or "all").strip().lower()
    date_from = _parse_date(request.GET.get("date_from"))
    date_to = _parse_date(request.GET.get("date_to"))
    if date_from and date_to and date_to < date_from:
        date_from, date_to = date_to, date_from

    valid_types = {t.value for t in models.PalayTrade.TradeType} | {"all"}
    if type_filter not in valid_types:
        type_filter = "all"

    trades_qs = (
        models.PalayTrade.objects.select_related(
            "member", "product", "product__variety", "performed_by"
        )
        .filter(status=models.PalayTrade.Status.POSTED)
        .order_by("-traded_at")
    )
    trades_qs = _apply_date_range(trades_qs, date_from, date_to)
    if type_filter != "all":
        trades_qs = trades_qs.filter(trade_type=type_filter)
    if search_query:
        trades_qs = trades_qs.filter(
            Q(party_name__icontains=search_query)
            | Q(reference__icontains=search_query)
            | Q(product__name__icontains=search_query)
            | Q(product__variety__name__icontains=search_query)
            | Q(member__first_name__icontains=search_query)
            | Q(member__last_name__icontains=search_query)
        )
    return trades_qs, date_from, date_to, type_filter, search_query


@login_required
@require_http_methods(["GET"])
def export_palay_inout_report(request):
    """Download palay trade IN/OUT import details as Excel or PDF."""
    if not _is_palay_staff(request.user):
        messages.warning(request, "You do not have permission to export this report.")
        return redirect("palay_trade:overview")

    requested_format = (request.GET.get("format") or "excel").strip().lower()
    if requested_format not in ("pdf", "excel"):
        requested_format = "excel"

    trades_qs, date_from, date_to, type_filter, search_query = _filtered_trades_from_request(request)
    trades = list(trades_qs)
    products = list(models.PalayTradeProduct.objects.order_by("name"))
    user_label = request.user.get_full_name() or request.user.username

    if requested_format == "pdf":
        return reports.build_pdf_response(
            trades=trades,
            date_from=date_from,
            date_to=date_to,
            type_filter=type_filter,
            search_query=search_query,
            user_label=user_label,
        )
    return reports.build_excel_response(
        trades=trades,
        products=products,
        date_from=date_from,
        date_to=date_to,
        type_filter=type_filter,
        search_query=search_query,
        user_label=user_label,
    )
