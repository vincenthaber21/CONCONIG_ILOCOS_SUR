"""FSM transition signal handlers for LoanApplication.

Connected from LoansConfig.ready().
"""

from django_fsm.signals import post_transition


def handle_loan_application_post_transition(sender, instance, name, source, target, **kwargs):
    from .audit import record_loan_audit
    from .models import LoanApplication, LoanApplicationAuditLog, LoanSettlement
    from .notifications import notify_loan_status_change

    if not isinstance(instance, LoanApplication):
        return

    source_label = dict(LoanApplication.Status.choices).get(source, source)
    target_label = dict(LoanApplication.Status.choices).get(target, target)
    record_loan_audit(
        instance,
        LoanApplicationAuditLog.Action.STATUS_CHANGED,
        description=(
            f"Application status changed from {source_label} to {target_label} "
            f"(transition: {name})."
        ),
        metadata={
            "transition": name,
            "source_status": source,
            "target_status": target,
            "source_label": source_label,
            "target_label": target_label,
        },
    )

    if target == LoanApplication.Status.CLOSED:
        LoanSettlement.objects.get_or_create(application=instance)

    extra = {}
    if target == LoanApplication.Status.VERIFICATION_FAILED:
        verification = getattr(instance, "eligibility_verification", None)
        if verification and verification.remarks:
            extra["remarks"] = verification.remarks
    elif target == LoanApplication.Status.REJECTED:
        review = getattr(instance, "committee_review", None)
        if review and review.remarks:
            extra["remarks"] = review.remarks

    notify_loan_status_change(instance, target, extra=extra)


post_transition.connect(handle_loan_application_post_transition)
