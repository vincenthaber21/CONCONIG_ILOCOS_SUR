from decimal import Decimal

import pytest

from loans.models import AmortizationSchedule, LoanApplication, LumpSumPayoff
from loans.services import generate_amortization_schedule, record_payment


@pytest.mark.django_db
def test_generate_amortization_schedule_math(application):
    application.term_months = 6
    application.amount_requested = Decimal("6000.00")
    application.save()

    schedules = generate_amortization_schedule(application)

    assert len(schedules) == 6
    assert AmortizationSchedule.objects.filter(application=application).count() == 6

    total_principal = sum((s.principal_due for s in schedules), Decimal("0"))
    assert total_principal == Decimal("6000.00")

    installment_numbers = [s.installment_number for s in schedules]
    assert installment_numbers == list(range(1, 7))

    # Every non-final installment should have the same level total payment.
    level_payments = {s.total_due for s in schedules[:-1]}
    assert len(level_payments) == 1


@pytest.mark.django_db
def test_generate_amortization_schedule_zero_interest(application, credit_officer):
    application.loan_product.interest_rate = Decimal("0")
    application.loan_product.save()
    application.term_months = 4
    application.amount_requested = Decimal("4000.00")
    application.save()

    schedules = generate_amortization_schedule(application)

    assert len(schedules) == 4
    for schedule in schedules:
        assert schedule.interest_due == Decimal("0")
    assert sum((s.principal_due for s in schedules), Decimal("0")) == Decimal("4000.00")


def _advance_application_to_active(application):
    application.submit()
    application.save()
    application.verify(True)
    application.save()
    application.submit_for_committee()
    application.save()
    application.approve()
    application.save()
    application.sign_documents()
    application.save()
    application.disburse()
    application.save()
    return application


@pytest.mark.django_db
def test_record_payment_marks_installments_paid_and_fully_pays_loan(application, cashier):
    application.term_months = 2
    application.amount_requested = Decimal("2000.00")
    application.save()

    _advance_application_to_active(application)
    assert application.status == LoanApplication.Status.ACTIVE

    schedules = generate_amortization_schedule(application)
    assert len(schedules) == 2

    first, second = schedules

    record_payment(
        application=application,
        amount=first.total_due,
        collected_by=cashier,
        payment_method="CASH",
        or_number="OR-0001",
    )
    first.refresh_from_db()
    # FSMField is protected, so reload via a fresh query instead of
    # refresh_from_db() (which would attempt a blocked direct assignment).
    application = LoanApplication.objects.get(pk=application.pk)
    assert first.is_paid is True
    assert application.status == LoanApplication.Status.ACTIVE

    record_payment(
        application=application,
        amount=second.total_due,
        collected_by=cashier,
        payment_method="CASH",
        or_number="OR-0002",
    )
    second.refresh_from_db()
    application = LoanApplication.objects.get(pk=application.pk)
    assert second.is_paid is True
    assert application.status == LoanApplication.Status.FULLY_PAID


@pytest.mark.django_db
def test_record_payment_settles_lump_sum(application, cashier):
    _advance_application_to_active(application)

    LumpSumPayoff.objects.create(
        application=application,
        maturity_date=application.created_at.date(),
        total_amount_due=Decimal("5000.00"),
    )

    record_payment(
        application=application,
        amount=Decimal("5000.00"),
        collected_by=cashier,
        payment_method="CASH",
    )

    application = LoanApplication.objects.get(pk=application.pk)
    assert application.lump_sum_payoff.is_paid is True
    assert application.status == LoanApplication.Status.FULLY_PAID
