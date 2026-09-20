import pytest
from django_fsm import TransitionNotAllowed

from loans.models import LoanApplication


def _advance_to_committee(application):
    application.submit()
    application.save()
    application.verify(True)
    application.save()
    application.submit_for_committee()
    application.save()
    return application


@pytest.mark.django_db
def test_full_happy_path_fsm_chain(application):
    assert application.status == LoanApplication.Status.DRAFT

    application.submit()
    application.save()
    assert application.status == LoanApplication.Status.SUBMITTED
    assert application.submitted_at is not None

    application.verify(True)
    application.save()
    assert application.status == LoanApplication.Status.UNDER_INVESTIGATION

    application.submit_for_committee()
    application.save()
    assert application.status == LoanApplication.Status.PENDING_COMMITTEE_APPROVAL

    application.approve()
    application.save()
    assert application.status == LoanApplication.Status.APPROVED

    # loan_product fixture has requires_insurance=False, so we skip
    # insurance enrollment and go straight to documentation.
    application.sign_documents()
    application.save()
    assert application.status == LoanApplication.Status.DOCUMENTATION_SIGNED

    application.disburse()
    application.save()
    assert application.status == LoanApplication.Status.ACTIVE

    application.mark_fully_paid()
    application.save()
    assert application.status == LoanApplication.Status.FULLY_PAID

    application.close_account()
    application.save()
    assert application.status == LoanApplication.Status.CLOSED
    assert hasattr(application, "settlement")


@pytest.mark.django_db
def test_happy_path_with_insurance(application):
    application.loan_product.requires_insurance = True
    application.loan_product.save()

    application.submit()
    application.save()
    application.verify(True)
    application.save()
    application.submit_for_committee()
    application.save()
    application.approve()
    application.save()

    application.enroll_insurance()
    application.save()
    assert application.status == LoanApplication.Status.INSURANCE_ENROLLED

    application.prepare_documentation()
    application.save()
    assert application.status == LoanApplication.Status.DOCUMENTATION_SIGNED


@pytest.mark.django_db
def test_verification_failure_branch(application):
    application.submit()
    application.save()

    application.verify(False)
    application.save()
    assert application.status == LoanApplication.Status.VERIFICATION_FAILED


@pytest.mark.django_db
def test_rejection_branch_and_transition_not_allowed_on_disburse(application):
    _advance_to_committee(application)

    application.reject()
    application.save()

    assert application.status == LoanApplication.Status.REJECTED
    assert application.notification_logs.exists()

    with pytest.raises(TransitionNotAllowed):
        application.disburse()


@pytest.mark.django_db
def test_signal_creates_settlement_on_close(application):
    from loans.models import LoanSettlement

    _advance_to_committee(application)
    application.approve()
    application.save()
    application.sign_documents()
    application.save()
    application.disburse()
    application.save()
    application.mark_fully_paid()
    application.save()

    assert not LoanSettlement.objects.filter(application=application).exists()

    application.close_account()
    application.save()

    assert LoanSettlement.objects.filter(application=application).exists()
