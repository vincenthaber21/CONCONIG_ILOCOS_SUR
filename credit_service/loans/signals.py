"""FSM transition signal handlers for LoanApplication.

Connected from LoansConfig.ready().
"""

from django_fsm.signals import post_transition


def handle_loan_application_post_transition(sender, instance, name, source, target, **kwargs):
    from .models import LoanApplication, LoanSettlement, NotificationLog

    if not isinstance(instance, LoanApplication):
        return

    if target == LoanApplication.Status.CLOSED:
        LoanSettlement.objects.get_or_create(application=instance)

    if target == LoanApplication.Status.REJECTED:
        if not instance.notification_logs.exists():
            NotificationLog.objects.create(
                application=instance,
                channel="EMAIL",
                message=(
                    f"Loan application #{instance.id} was rejected by the credit committee."
                ),
            )


post_transition.connect(handle_loan_application_post_transition)
