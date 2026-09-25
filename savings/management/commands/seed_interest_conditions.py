"""Create one savings account per interest rule so each condition can be checked.

Uses the live Regular Savings product (rate and apply-every-months).
Re-running replaces the previous intcond_ members.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from members.models import Member, Role
from savings import models, services
from savings.services import _post


def _when(year, month, day):
    return timezone.make_aware(datetime(year, month, day, 9, 0, 0))


class Command(BaseCommand):
    help = "Seed dummy savings accounts that demonstrate each interest condition."

    def handle(self, *args, **options):
        product = (
            models.SavingsProduct.objects.filter(
                is_active=True,
                product_type=models.SavingsProduct.ProductType.REGULAR,
            )
            .order_by("created_at")
            .first()
        )
        if product is None:
            self.stderr.write("No active Regular Savings product.")
            return

        role, _ = Role.objects.get_or_create(
            slug="member",
            defaults={"name": "Member", "sort_order": 100, "is_active": True},
        )

        with transaction.atomic():
            old = Member.objects.filter(username__startswith="intcond_")
            models.MemberSavingsAccount.objects.filter(member__in=old).delete()
            old.delete()

            cases = [
                self._basic,
                self._deposit_in_period,
                self._succeeded_next_balance,
                self._withdrawal_reset,
                self._minimum_balance,
            ]
            created = []
            for index, builder in enumerate(cases, start=1):
                created.append(builder(product, role, index))

        self.stdout.write("")
        self.stdout.write(
            f"Product: {product.name}  rate {product.interest_rate}  "
            f"every {product.interest_apply_months} months"
        )
        for account, label in created:
            account.refresh_from_db()
            snap = services.interest_snapshot(account)
            self.stdout.write("")
            self.stdout.write(label)
            self.stdout.write(
                f"  {account.account_number}  {account.member.full_name}  "
                f"balance {account.balance}"
            )
            self.stdout.write(
                f"  base {snap['interest_base']}  deposits {snap['period_deposits']}  "
                f"interest {snap['estimated_interest']}  "
                f"next {snap['next_credit_on']}"
            )
            self.stdout.write(
                f"  reset={snap['period_reset']}  "
                f"no_withdrawal={snap['no_withdrawal']}  "
                f"below_1000={snap['below_minimum']}"
            )
            for txn in account.transactions.order_by("created_at", "id"):
                self.stdout.write(
                    f"  ledger {txn.created_at:%Y-%m-%d}  {txn.transaction_type:12}  "
                    f"{txn.amount}  bal {txn.balance_after}"
                )
            self.stdout.write(
                f"  http://127.0.0.1:8000/dashboard/savings/accounts/{account.pk}/"
            )

    def _member(self, role, index, first_name):
        tag = f"{index:02d}"
        return Member.objects.create(
            username=f"intcond_{tag}",
            email=f"intcond_{tag}@example.com",
            rfid_card_number=f"INTCOND{tag}",
            first_name=first_name,
            last_name="Interest",
            phone=f"090000000{tag}",
            member_role=role,
            is_active=True,
        )

    def _open(self, member, product, amount, opened, notes):
        return services.open_account(
            member=member,
            product=product,
            opening_amount=Decimal(amount),
            notes=notes,
            opening_date=opened,
        )

    def _credit_next(self, account):
        """Post the next interest date into the ledger so the rule is visible."""
        account.refresh_from_db()
        nxt = services.next_unpaid_interest_on(account)
        if nxt is None:
            return account
        services.credit_due_interest(account=account, as_of=nxt + timedelta(days=1))
        account.refresh_from_db()
        return account

    def _move(self, account, txn_type, amount, when, notes, *, credit):
        return _post(
            account,
            txn_type,
            Decimal(amount),
            notes=notes,
            credit=credit,
            posted_at=when,
        )

    def _basic(self, product, role, index):
        member = self._member(role, index, "Basic")
        account = self._open(
            member,
            product,
            "5000.00",
            _when(2026, 8, 25),
            "Condition: opening only. Interest uses 5000 until the period ends.",
        )
        return self._credit_next(account), "1. Basic — formula on the opening savings, no deposit or withdrawal"

    def _deposit_in_period(self, product, role, index):
        member = self._member(role, index, "Deposit")
        account = self._open(
            member,
            product,
            "2000.00",
            _when(2026, 8, 1),
            "Condition: deposit inside the interest period stays out of this interest.",
        )
        self._move(
            account,
            models.SavingsTransaction.TxnType.DEPOSIT,
            "1000.00",
            _when(2026, 9, 1),
            "February-style deposit inside the interest period.",
            credit=True,
        )
        return self._credit_next(account), "2. Deposit in period — balance includes 1000, interest still uses 2000"

    def _succeeded_next_balance(self, product, role, index):
        member = self._member(role, index, "Succeed")
        account = self._open(
            member,
            product,
            "2000.00",
            _when(2026, 1, 15),
            "Condition: after a successful period the next interest uses the new balance.",
        )
        self._move(
            account,
            models.SavingsTransaction.TxnType.DEPOSIT,
            "1000.00",
            _when(2026, 2, 15),
            "Deposit inside the first period.",
            credit=True,
        )
        services.credit_due_interest(account=account)
        return self._credit_next(account), "3. Succeeded period — next period applies the formula to the new balance"

    def _withdrawal_reset(self, product, role, index):
        member = self._member(role, index, "Withdraw")
        account = self._open(
            member,
            product,
            "5000.00",
            _when(2026, 6, 15),
            "Condition: withdrawal inside the period resets the month count.",
        )
        self._move(
            account,
            models.SavingsTransaction.TxnType.WITHDRAWAL,
            "1000.00",
            _when(2026, 8, 15),
            "Withdrawal inside the 3-month period. Count restarts here.",
            credit=False,
        )
        return self._credit_next(account), "4. Withdrawal reset — next interest is 3 months after the withdrawal"

    def _minimum_balance(self, product, role, index):
        member = self._member(role, index, "Minimum")
        account = self._open(
            member,
            product,
            "1000.00",
            _when(2026, 8, 1),
            "Condition: remaining balance of 1000 does not earn interest.",
        )
        return self._credit_next(account), "5. Minimum balance — 1000 remaining, no interest"
