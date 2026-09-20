"""Member-facing palay credit features and balance."""

from decimal import Decimal

from django.http import Http404
from django.shortcuts import render

from helper.login_helper import member_or_login_required
from members.models import Member

from . import credit_services, models


def _get_active_member(request):
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


@member_or_login_required
def member_palay_credit(request):
    member = _get_active_member(request)
    settings = models.PalayCreditSettings.get()
    products = list(
        models.PalayTradeProduct.objects.filter(
            is_active=True,
            code__in=models.DEFAULT_PRODUCT_CODES,
        ).order_by("name")
    )
    display_name = "Member"
    if request.user.is_authenticated:
        display_name = request.user.get_full_name() or request.user.username
    open_trades = []
    total_outstanding = Decimal("0.00")
    eligible = False
    if member:
        display_name = member.full_name
        eligible = credit_services.member_meets_palay_credit_eligibility(member)
        open_trades = list(
            credit_services.open_palay_credit_trades(member=member)
            .select_related("product")
            .order_by("-traded_at")
        )
        total_outstanding = credit_services.member_palay_credit_outstanding(member)

    return render(
        request,
        "palay_trade/member/palay_credit.html",
        {
            "display_name": display_name,
            "member": member,
            "settings": settings,
            "products": products,
            "open_trades": open_trades,
            "total_outstanding": total_outstanding,
            "eligible": eligible,
        },
    )
