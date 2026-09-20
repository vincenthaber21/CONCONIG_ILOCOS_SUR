"""Member-facing savings product features, accounts, and receipts."""

from decimal import Decimal

from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from helper.login_helper import member_or_login_required
from members.models import Member

from . import models, services
from .policy import regular_savings_policy
from .views import _receipt_context


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


def _require_member_account(request, pk):
    member = _get_active_member(request)
    if not member:
        raise Http404("Savings account not found.")
    return get_object_or_404(
        models.MemberSavingsAccount.objects.select_related("member", "product"),
        pk=pk,
        member=member,
    )


@member_or_login_required
def member_savings_list(request):
    member = _get_active_member(request)
    products = models.SavingsProduct.objects.filter(is_active=True).order_by("name")
    accounts = []
    total_balance = 0
    display_name = "Member"
    if request.user.is_authenticated:
        display_name = request.user.get_full_name() or request.user.username
    if member:
        display_name = member.full_name
        accounts = list(
            models.MemberSavingsAccount.objects.filter(member=member)
            .select_related("product")
            .order_by("-opened_at")
        )
        for account in accounts:
            services.auto_credit_due_interest(account=account)
            account.refresh_from_db()
            account.interest = services.interest_snapshot(account)
        total_balance = sum((account.balance for account in accounts), Decimal("0.00"))

    return render(
        request,
        "savings/member/savings_list.html",
        {
            "display_name": display_name,
            "products": products,
            "accounts": accounts,
            "total_balance": total_balance,
            "member": member,
            "savings_policy": regular_savings_policy(),
        },
    )


@member_or_login_required
def member_savings_account(request, pk):
    account = _require_member_account(request, pk)
    services.auto_credit_due_interest(account=account)
    account.refresh_from_db()
    ledger = account.transactions.select_related("performed_by")[:50]
    return render(
        request,
        "savings/member/account_detail.html",
        {
            "account": account,
            "ledger": ledger,
            "display_name": account.member.full_name,
            "interest": services.interest_snapshot(account),
            "savings_policy": regular_savings_policy(),
        },
    )


@member_or_login_required
def member_savings_receipt(request, pk, txn_id):
    account = _require_member_account(request, pk)
    txn = get_object_or_404(
        models.SavingsTransaction.objects.select_related("performed_by", "account"),
        pk=txn_id,
        account=account,
    )
    ctx = _receipt_context(
        request,
        account,
        [txn],
        single=True,
        txn=txn,
        back_url=reverse("member_savings_account", kwargs={"pk": account.pk}),
    )
    return render(request, "savings/transaction_receipt.html", ctx)


@member_or_login_required
def member_savings_receipts_all(request, pk):
    account = _require_member_account(request, pk)
    transactions = list(
        account.transactions.select_related("performed_by").order_by("created_at", "id")
    )
    ctx = _receipt_context(
        request,
        account,
        transactions,
        single=False,
        back_url=reverse("member_savings_account", kwargs={"pk": account.pk}),
    )
    return render(request, "savings/transaction_receipt.html", ctx)
