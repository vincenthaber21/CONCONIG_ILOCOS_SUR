from decimal import Decimal

import pytest

from accounts.models import User
from loans.models import LoanApplication, LoanProduct


@pytest.fixture
def member(db):
    return User.objects.create_user(
        username="member1", password="pass12345", role=User.Role.MEMBER
    )


@pytest.fixture
def credit_officer(db):
    return User.objects.create_user(
        username="officer1", password="pass12345", role=User.Role.CREDIT_OFFICER
    )


@pytest.fixture
def committee_member(db):
    return User.objects.create_user(
        username="committee1", password="pass12345", role=User.Role.COMMITTEE
    )


@pytest.fixture
def cashier(db):
    return User.objects.create_user(
        username="cashier1", password="pass12345", role=User.Role.CASHIER
    )


@pytest.fixture
def loan_product(db):
    return LoanProduct.objects.create(
        name="Regular Salary Loan",
        description="Short term salary loan",
        interest_rate=Decimal("12.0"),
        min_amount=Decimal("1000.00"),
        max_amount=Decimal("100000.00"),
        requires_collateral=False,
        requires_insurance=False,
    )


@pytest.fixture
def application(db, member, loan_product):
    return LoanApplication.objects.create(
        member=member,
        loan_product=loan_product,
        amount_requested=Decimal("12000.00"),
        purpose="Home improvement",
        term_months=12,
    )
