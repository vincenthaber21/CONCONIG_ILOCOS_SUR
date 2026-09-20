"""Member palay credit balances, validation, and settlement."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import DecimalField, F, Sum, Value, Count
from django.db.models.functions import Coalesce, Greatest
from django.utils import timezone

from . import models

ZERO = Decimal("0.00")


def _money(value):
    return Decimal(value or 0).quantize(Decimal("0.01"))


def _credit_outstanding_expression():
    return Greatest(
        F("net_amount") - Coalesce(F("credit_amount_paid"), Value(ZERO)),
        Value(ZERO),
        output_field=DecimalField(max_digits=14, decimal_places=2),
    )


def open_palay_credit_trades(*, member=None):
    qs = models.PalayTrade.objects.filter(
        payment_method=models.PalayTrade.PaymentMethod.CREDIT,
        status=models.PalayTrade.Status.POSTED,
        credit_settled_at__isnull=True,
    )
    if member is not None:
        qs = qs.filter(member=member)
    return qs.annotate(outstanding=_credit_outstanding_expression()).filter(outstanding__gt=ZERO)


def settled_palay_credit_trades(*, limit=50, search_query=""):
    qs = (
        models.PalayTrade.objects.filter(
            payment_method=models.PalayTrade.PaymentMethod.CREDIT,
            status=models.PalayTrade.Status.POSTED,
            credit_settled_at__isnull=False,
        )
        .select_related("member", "product", "performed_by")
        .order_by("-credit_settled_at")
    )
    if search_query:
        from django.db.models import Q

        qs = qs.filter(
            Q(party_name__icontains=search_query)
            | Q(reference__icontains=search_query)
            | Q(member__first_name__icontains=search_query)
            | Q(member__last_name__icontains=search_query)
        )
    return qs[:limit]


def members_with_open_palay_credit():
    """Aggregate open palay credit by member (or party when no member link)."""
    rows = {}
    trades = list(
        open_palay_credit_trades()
        .select_related("member")
        .order_by("member__last_name", "member__first_name", "party_name", "-traded_at")
    )
    for trade in trades:
        if trade.member_id:
            key = ("member", trade.member_id)
            label = trade.member.full_name
            member = trade.member
        else:
            key = ("party", (trade.party_name or "").strip().lower())
            label = trade.party_name
            member = None
        if key not in rows:
            rows[key] = {
                "member": member,
                "member_id": trade.member_id,
                "party_name": label,
                "ticket_count": 0,
                "total_kg": ZERO,
                "total_paid": ZERO,
                "total_outstanding": ZERO,
            }
        row = rows[key]
        row["ticket_count"] += 1
        row["total_kg"] += _money(trade.net_kg)
        row["total_paid"] += _money(trade.credit_amount_paid)
        row["total_outstanding"] += _money(trade.outstanding)
    return sorted(rows.values(), key=lambda r: (-r["total_outstanding"], r["party_name"] or ""))


def palay_credit_overview_stats():
    open_qs = open_palay_credit_trades()
    totals = open_qs.aggregate(
        ticket_count=Count("id"),
        total_kg=Sum("net_kg"),
        total_outstanding=Sum("outstanding"),
    )
    member_rows = members_with_open_palay_credit()
    return {
        "member_count": len(member_rows),
        "ticket_count": totals.get("ticket_count") or 0,
        "total_kg": _money(totals.get("total_kg")),
        "total_outstanding": _money(totals.get("total_outstanding")),
    }


def settle_member_palay_credit(member, *, amount=None, performed_by=None):
    """Apply a payment to a member's open palay credit tickets (FIFO). Omit amount for full settlement."""
    trades = list(
        open_palay_credit_trades(member=member).order_by("traded_at", "id")
    )
    if not trades:
        raise ValidationError("This member has no open palay credit to settle.")

    if amount is None:
        settled = []
        for trade in trades:
            settled.append(settle_palay_credit(trade, performed_by=performed_by))
        return settled

    pay = _money(amount)
    if pay <= ZERO:
        raise ValidationError("Payment amount must be greater than zero.")

    total_outstanding = sum(_money(getattr(t, "outstanding", t.credit_outstanding)) for t in trades)
    if pay > total_outstanding:
        raise ValidationError(
            f"Payment exceeds total outstanding balance (₱{total_outstanding:,.2f})."
        )

    settled = []
    remaining = pay
    for trade in trades:
        if remaining <= ZERO:
            break
        ticket_outstanding = _money(getattr(trade, "outstanding", trade.credit_outstanding))
        apply = min(remaining, ticket_outstanding)
        settled.append(settle_palay_credit(trade, amount=apply, performed_by=performed_by))
        remaining -= apply
    return settled


def member_palay_credit_outstanding(member) -> Decimal:
    if not member:
        return ZERO
    total = open_palay_credit_trades(member=member).aggregate(t=Sum("outstanding"))["t"]
    return _money(total)


def member_meets_palay_credit_eligibility(member) -> bool:
    settings = models.PalayCreditSettings.get()
    required = int(settings.min_membership_months or 0)
    if required <= 0:
        return True
    joined = getattr(member, "date_joined", None)
    if not joined:
        return False
    months = (timezone.now().year - joined.year) * 12 + (timezone.now().month - joined.month)
    if timezone.now().day < joined.day:
        months -= 1
    return months >= required


def validate_palay_credit_trade(
    *,
    product,
    trade_type,
    member,
    amount,
    enforce_membership_eligibility=True,
):
    settings = models.PalayCreditSettings.get()
    if not settings.is_enabled:
        raise ValidationError("Palay credit is not enabled. Enable it under Palay credit settings.")
    if member is None:
        raise ValidationError("Palay credit requires a cooperative member.")
    if not product.credit_enabled:
        raise ValidationError(f'Palay credit is not enabled for "{product.name}".')
    if enforce_membership_eligibility and not member_meets_palay_credit_eligibility(member):
        raise ValidationError(
            f"Member must be registered at least {settings.min_membership_months} month(s) "
            "before using palay credit."
        )
    if trade_type == models.PalayTrade.TradeType.SELL:
        if not settings.allow_credit_on_sell:
            raise ValidationError("Palay credit is not allowed on sell (buy) tickets.")
    elif trade_type == models.PalayTrade.TradeType.BUY:
        if not settings.allow_credit_on_buy:
            raise ValidationError("Palay credit is not allowed on buy (from farmer) tickets.")
    else:
        raise ValidationError("Invalid trade type for palay credit.")

    amount = _money(amount)
    cap = _money(settings.member_max_outstanding)
    if cap > ZERO:
        current = member_palay_credit_outstanding(member)
        if current + amount > cap:
            raise ValidationError(
                f"Palay credit limit exceeded. Outstanding ₱{current:,.2f}; "
                f"this ticket ₱{amount:,.2f}; limit ₱{cap:,.2f}."
            )


def post_member_utang(
    *,
    product,
    member,
    gross_kg,
    performed_by=None,
    notes="",
):
    """Sell rice from stock to a member on palay credit (utang)."""
    from . import services

    settings = models.PalayCreditSettings.get()
    if not settings.is_enabled:
        raise ValidationError(
            "Palay credit (utang) is turned off. Turn it on under Configure limits."
        )
    if not settings.allow_credit_on_sell:
        raise ValidationError("Utang from stock is not allowed in palay credit settings.")

    return services.post_trade(
        product=product,
        trade_type=models.PalayTrade.TradeType.SELL,
        party_name=member.full_name,
        gross_kg=gross_kg,
        unit_price=product.sell_price_per_kg,
        member=member,
        performed_by=performed_by,
        notes=notes,
        payment_method=models.PalayTrade.PaymentMethod.CREDIT,
        enforce_membership_eligibility=False,
    )


def settle_palay_credit(trade, *, amount=None, performed_by=None):
    with transaction.atomic():
        trade = models.PalayTrade.objects.select_for_update().get(pk=trade.pk)
        if trade.payment_method != models.PalayTrade.PaymentMethod.CREDIT:
            raise ValidationError("This ticket was not posted on palay credit.")
        if trade.credit_settled_at:
            raise ValidationError("This palay credit ticket is already settled.")

        outstanding = trade.credit_outstanding
        if outstanding <= ZERO:
            trade.credit_settled_at = timezone.now()
            trade.save(update_fields=["credit_settled_at", "updated_at"])
            return trade

        pay = _money(amount if amount is not None else outstanding)
        if pay <= ZERO:
            raise ValidationError("Payment amount must be greater than zero.")
        if pay > outstanding:
            raise ValidationError(f"Payment exceeds outstanding balance (₱{outstanding:,.2f}).")

        trade.credit_amount_paid = _money(trade.credit_amount_paid) + pay
        if trade.credit_outstanding <= ZERO:
            trade.credit_settled_at = timezone.now()
        trade.save(update_fields=["credit_amount_paid", "credit_settled_at", "updated_at"])
        return trade