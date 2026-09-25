"""Sample time-deposit accounts for the amount and term conditions."""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand
from django.db import transaction

from members.models import Member, MemberType, Role
from savings import models, services
from savings.policy import time_deposit_interest_amount

CASES = (
    {
        "username": "td-dummy-50000",
        "first_name": "Low",
        "last_name": "TimeDeposit",
        "amount": Decimal("50000.00"),
        "opened": date(2025, 9, 1),
        "term": None,
        "note": "₱5,000–₱100,000. Expected yearly interest 50,000 × 0.02 = ₱1,000.00.",
    },
    {
        "username": "td-dummy-100000",
        "first_name": "Cap",
        "last_name": "TimeDeposit",
        "amount": Decimal("100000.00"),
        "opened": date(2025, 8, 1),
        "term": None,
        "note": "Exactly ₱100,000 stays on the yearly rate. 100,000 × 0.02 = ₱2,000.00.",
    },
    {
        "username": "td-dummy-3m",
        "first_name": "Three",
        "last_name": "TimeDeposit",
        "amount": Decimal("120000.00"),
        "opened": date(2026, 5, 1),
        "term": 3,
        "note": "₱100,001 and above, 3 months. 120,000 × 0.01 × (3/12) = ₱300.00.",
    },
    {
        "username": "td-dummy-6m",
        "first_name": "Six",
        "last_name": "TimeDeposit",
        "amount": Decimal("200000.00"),
        "opened": date(2026, 2, 1),
        "term": 6,
        "note": "₱100,001 and above, 6 months. 200,000 × 0.01 × (6/12) = ₱1,000.00.",
    },
    {
        "username": "td-dummy-1y",
        "first_name": "OneYear",
        "last_name": "TimeDeposit",
        "amount": Decimal("150000.00"),
        "opened": date(2025, 9, 1),
        "term": 12,
        "note": "₱100,001 and above, 1 year. 150,000 × 0.03 = ₱4,500.00.",
    },
)


class Command(BaseCommand):
    help = "Create time-deposit dummy members and accounts for the interest conditions."

    @transaction.atomic
    def handle(self, *args, **options):
        role, _ = Role.objects.get_or_create(
            slug="member",
            defaults={"name": "Member", "sort_order": 100, "is_active": True},
        )
        member_type, _ = MemberType.objects.get_or_create(
            name="Regular Member",
            defaults={"description": "Auto-generated test member type"},
        )
        product, created = models.SavingsProduct.objects.get_or_create(
            code="td-demo",
            defaults={
                "name": "Time Deposit Demo",
                "product_type": models.SavingsProduct.ProductType.TIME_DEPOSIT,
                "description": "Dummy time deposit for ₱5,000–₱100,000 and ₱100,001 term tests.",
                "interest_rate": Decimal("0.020"),
                "interest_apply_months": 12,
                "min_opening_deposit": Decimal("5000.00"),
                "max_balance": Decimal("10000000.00"),
                "rate_3_months": Decimal("0.010"),
                "rate_6_months": Decimal("0.010"),
                "rate_1_year": Decimal("0.030"),
                "term_months": 0,
                "allows_withdrawal": True,
                "is_active": True,
            },
        )
        if not created:
            product.product_type = models.SavingsProduct.ProductType.TIME_DEPOSIT
            product.interest_rate = Decimal("0.020")
            product.min_opening_deposit = Decimal("5000.00")
            product.max_balance = Decimal("10000000.00")
            product.rate_3_months = Decimal("0.010")
            product.rate_6_months = Decimal("0.010")
            product.rate_1_year = Decimal("0.030")
            product.is_active = True
            product.save()

        self.stdout.write(f"Product: {product.name} ({product.code})")
        for case in CASES:
            member, _ = Member.objects.get_or_create(
                username=case["username"],
                defaults={
                    "first_name": case["first_name"],
                    "last_name": case["last_name"],
                    "email": f"{case['username']}@example.com",
                    "rfid_card_number": case["username"],
                    "member_type": member_type,
                    "member_role": role,
                    "is_active": True,
                },
            )
            existing = models.MemberSavingsAccount.objects.filter(
                member=member,
                product=product,
            ).exclude(status=models.MemberSavingsAccount.Status.CLOSED).first()
            if existing:
                self.stdout.write(f"Already open: {member.full_name} {existing.account_number}")
                continue
            account = services.open_account(
                member=member,
                product=product,
                opening_amount=case["amount"],
                notes=case["note"],
                opening_date=case["opened"],
                deposit_term_months=case["term"],
            )
            expected = time_deposit_interest_amount(
                case["amount"],
                product.interest_rate,
                term_months=case["term"],
                product=product,
            )
            try:
                posted = services.credit_due_interest(account=account)
            except ValidationError as exc:
                posted = []
                self.stdout.write(
                    "  interest not due yet: "
                    + (" ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
                )
            credited = sum((txn.amount for txn in posted), Decimal("0.00"))
            self.stdout.write(
                f"{member.full_name} {account.account_number} "
                f"opened {case['opened']} start PHP {case['amount']:,.2f} "
                f"term {case['term'] or 'yearly'} "
                f"expected PHP {expected:,.2f} credited PHP {credited:,.2f}"
            )
            self.stdout.write(f"  http://127.0.0.1:8000/dashboard/savings/accounts/{account.pk}/")
