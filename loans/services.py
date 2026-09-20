"""Business logic that doesn't belong on the models themselves.

Kept deliberately framework-light (plain functions) so it's easy to call
from views, management commands, Celery tasks and tests alike.
"""

import base64
import uuid
from calendar import monthrange
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.utils import timezone
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

TWO_PLACES = Decimal("0.01")
ONE_PLACE = Decimal("0.1")
BASE_REPAYMENT_SCORE = Decimal("100.0")
NONCOMPLIANCE_PENALTY = Decimal("0.1")  # -0.1 percentage points per late unpaid installment


def _add_calendar_months(dt, months):
    """Return *dt* advanced by *months* calendar months, clamping the day if needed."""
    month_index = dt.month - 1 + int(months)
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = min(dt.day, monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def member_loan_waiting_period(member, user=None):
    """Whether a member has been registered long enough to request a loan.

    Admin sets ``LoanSettings.min_membership_months`` (default 3). A member
    who joined only a week ago cannot apply until that waiting period passes.
    Set the value to 0 to allow loan requests immediately.
    """
    from .models import LoanSettings

    required_months = int(getattr(LoanSettings.get(), "min_membership_months", 0) or 0)
    empty = {
        "allowed": True,
        "required_months": required_months,
        "eligible_on": None,
        "joined_on": None,
        "message": "",
    }
    if required_months <= 0:
        return empty

    joined = None
    if member is not None:
        joined = getattr(member, "date_joined", None) or getattr(member, "created_at", None)
    if joined is None and user is not None:
        joined = getattr(user, "date_joined", None)

    month_word = "month" if required_months == 1 else "months"
    if joined is None:
        return {
            "allowed": False,
            "required_months": required_months,
            "eligible_on": None,
            "joined_on": None,
            "message": (
                f"You must be a member for at least {required_months} {month_word} "
                "before you can request a loan."
            ),
        }

    eligible_on = _add_calendar_months(joined, required_months)
    now = timezone.now()
    if timezone.is_naive(eligible_on) and timezone.is_aware(now):
        eligible_on = timezone.make_aware(eligible_on, timezone.get_current_timezone())
    elif timezone.is_aware(eligible_on) and timezone.is_naive(now):
        now = timezone.make_aware(now, timezone.get_current_timezone())

    if now >= eligible_on:
        empty["eligible_on"] = eligible_on
        empty["joined_on"] = joined
        return empty

    eligible_local = timezone.localtime(eligible_on) if timezone.is_aware(eligible_on) else eligible_on
    return {
        "allowed": False,
        "required_months": required_months,
        "eligible_on": eligible_on,
        "joined_on": joined,
        "message": (
            f"New members cannot request a loan until they have been a member "
            f"for {required_months} {month_word}. You can apply starting "
            f"{eligible_local.strftime('%B %d, %Y')}."
        ),
    }


def application_membership_maturity(application):
    """Check whether the applicant has met the minimum membership waiting period."""
    from helper.login_helper import get_linked_member

    member = get_linked_member(getattr(application, "member", None))
    return member_loan_waiting_period(member, user=getattr(application, "member", None))


COMMITTEE_VOTER_ROLES = frozenset({"admin", "loan_officer", "staff", "committee"})
COMMITTEE_VOTER_ROLE_LABELS = {
    "admin": "Admin",
    "loan_officer": "Loan Officer",
    "staff": "Staff",
    "committee": "Credit Committee",
}
COMMITTEE_VOTER_ROLE_ORDER = ("admin", "loan_officer", "staff", "committee")


def _committee_votes_needed(total_voters, single_approver=False):
    """Minimum approve (or reject) votes needed for a committee decision."""
    if total_voters <= 0:
        return 0
    if single_approver:
        return 1
    return (total_voters // 2) + 1


def committee_single_approver_enabled():
    """True when one authorized vote is enough to finalize committee review."""
    from .models import LoanSettings

    return bool(getattr(LoanSettings.get(), "committee_single_approver", True))


def eligible_committee_voters():
    """Active admins, loan officers, staff, and committee members who may vote."""
    from members.models import Member

    return list(
        Member.objects.filter(
            is_active=True,
            user__isnull=False,
            user__is_active=True,
            member_role__slug__in=COMMITTEE_VOTER_ROLES,
        )
        .select_related("user", "member_role")
        .order_by("member_role__sort_order", "first_name", "last_name")
    )


def user_can_committee_vote(user):
    """True when this login may cast an admin / loan-officer committee vote."""
    if not user or not getattr(user, "is_active", False):
        return False
    if getattr(user, "is_superuser", False):
        return True
    from helper.login_helper import get_linked_member

    member = get_linked_member(user)
    return bool(
        member
        and member.is_active
        and member.role in COMMITTEE_VOTER_ROLES
    )


def _voter_display(member):
    return member.full_name if member else ""


def committee_approval_status(application, current_user=None):
    """Track committee votes; threshold approval (with maturity) finalizes the loan."""
    from .models import LoanCommitteeVote

    single_approver = committee_single_approver_enabled()
    voters = eligible_committee_voters()
    voter_user_ids = {m.user_id for m in voters}
    votes = {
        v.user_id: v
        for v in application.committee_votes.filter(user_id__in=voter_user_ids)
    }

    def _group_status(group):
        if not group:
            return {"items": [], "required": 0, "approved": 0, "complete": True}
        items = []
        for member in group:
            vote = votes.get(member.user_id)
            is_approve = bool(vote and vote.vote == LoanCommitteeVote.Vote.APPROVE)
            is_reject = bool(vote and vote.vote == LoanCommitteeVote.Vote.REJECT)
            items.append(
                {
                    "member": member,
                    "user_id": member.user_id,
                    "username": getattr(member.user, "username", "") or "",
                    "name": _voter_display(member),
                    "role": member.get_role_display(),
                    "role_slug": member.role,
                    "vote": vote.vote if vote else "",
                    "voted": vote is not None,
                    "approved": is_approve,
                    "rejected": is_reject,
                    "pending": vote is None,
                    "is_current_user": bool(
                        current_user
                        and getattr(current_user, "pk", None) == member.user_id
                    ),
                }
            )
        approved = sum(1 for item in items if item["approved"])
        return {
            "items": items,
            "required": len(items),
            "approved": approved,
            "complete": approved == len(items),
        }

    role_groups = {}
    all_items = []
    for role_slug in COMMITTEE_VOTER_ROLE_ORDER:
        group_members = [m for m in voters if m.role == role_slug]
        group_status = _group_status(group_members)
        role_groups[role_slug] = group_status
        for item in group_status["items"]:
            all_items.append(
                {
                    **item,
                    "group_label": COMMITTEE_VOTER_ROLE_LABELS.get(role_slug, role_slug),
                }
            )

    maturity = application_membership_maturity(application)
    total_required = len(all_items)
    total_approved = sum(1 for item in all_items if item["approved"])
    total_rejected = sum(1 for item in all_items if item["rejected"])
    votes_needed = _committee_votes_needed(total_required, single_approver=single_approver)
    majority_reached = total_required == 0 or total_approved >= votes_needed
    reject_majority_reached = total_required > 0 and total_rejected >= votes_needed
    maturity_met = bool(maturity.get("allowed", False))
    current_user_id = getattr(current_user, "pk", None)
    user_vote = votes.get(current_user_id) if current_user_id else None
    user_can_vote = user_can_committee_vote(current_user) if current_user else False
    user_can_approve_now = bool(
        user_can_vote
        and maturity_met
        and not (user_vote and user_vote.vote == LoanCommitteeVote.Vote.APPROVE)
    )
    pending_approvers = [item for item in all_items if item["pending"]]
    can_finalize_approve = bool(
        maturity_met and majority_reached and not reject_majority_reached
    )
    can_finalize_reject = reject_majority_reached
    can_proceed = can_finalize_approve
    threshold_label = "one approval" if single_approver else "majority"

    return {
        "voters": voters,
        "role_groups": role_groups,
        "admin": role_groups.get("admin", {"items": [], "required": 0, "approved": 0, "complete": True}),
        "loan_officers": role_groups.get(
            "loan_officer",
            {"items": [], "required": 0, "approved": 0, "complete": True},
        ),
        "staff": role_groups.get("staff", {"items": [], "required": 0, "approved": 0, "complete": True}),
        "committee": role_groups.get(
            "committee",
            {"items": [], "required": 0, "approved": 0, "complete": True},
        ),
        "all_approvers": all_items,
        "pending_approvers": pending_approvers,
        "total_required": total_required,
        "total_approved": total_approved,
        "total_rejected": total_rejected,
        "single_approver": single_approver,
        "votes_needed": votes_needed,
        "majority_needed": votes_needed,  # template/compat alias
        "majority_reached": majority_reached,
        "reject_majority_reached": reject_majority_reached,
        "threshold_label": threshold_label,
        "any_reject": total_rejected > 0,
        "unanimous_approved": total_required > 0 and total_approved == total_required,
        "maturity": maturity,
        "maturity_met": maturity_met,
        "can_finalize_approve": can_finalize_approve,
        "can_finalize_reject": can_finalize_reject,
        "can_proceed": can_proceed,
        "user_vote": user_vote,
        "user_can_vote": user_can_vote,
        "user_can_approve_now": user_can_approve_now,
    }


def try_finalize_committee_approval(application, remarks="", actor=None, request=None):
    """Apply committee decision when vote thresholds are met."""
    from django_fsm import TransitionNotAllowed

    from .audit import record_loan_audit
    from .models import CommitteeReview, LoanApplication, LoanApplicationAuditLog, LoanCommitteeVote

    if application.status != LoanApplication.Status.PENDING_COMMITTEE_APPROVAL:
        return None

    status = committee_approval_status(application)
    single = status["single_approver"]
    approve_desc = (
        "Committee approved this loan application (single approver)."
        if single
        else "Committee majority approved this loan application."
    )
    reject_desc = (
        "Committee rejected this loan application (single approver)."
        if single
        else "Committee majority rejected this loan application."
    )

    if status["can_finalize_reject"]:
        review, _ = CommitteeReview.objects.update_or_create(
            application=application,
            defaults={
                "decision": CommitteeReview.Decision.REJECTED,
                "decision_date": timezone.now(),
                "remarks": remarks,
            },
        )
        for reject_vote in application.committee_votes.filter(
            vote=LoanCommitteeVote.Vote.REJECT
        ):
            review.reviewed_by.add(reject_vote.user)
        application.reject()
        application.save(update_fields=["status"])
        record_loan_audit(
            application,
            LoanApplicationAuditLog.Action.COMMITTEE_FINALIZED,
            actor=actor,
            description=reject_desc,
            metadata={
                "decision": CommitteeReview.Decision.REJECTED,
                "remarks": remarks,
                "approve_votes": status["total_approved"],
                "reject_votes": status["total_rejected"],
                "single_approver": single,
                "votes_needed": status["votes_needed"],
            },
            request=request,
        )
        return "rejected"

    if status["can_finalize_approve"]:
        review, _ = CommitteeReview.objects.update_or_create(
            application=application,
            defaults={
                "decision": CommitteeReview.Decision.APPROVED,
                "decision_date": timezone.now(),
                "remarks": remarks,
            },
        )
        for approve_vote in application.committee_votes.filter(
            vote=LoanCommitteeVote.Vote.APPROVE
        ):
            review.reviewed_by.add(approve_vote.user)
        try:
            application.approve()
        except TransitionNotAllowed:
            return None
        application.save(update_fields=["status"])
        record_loan_audit(
            application,
            LoanApplicationAuditLog.Action.COMMITTEE_FINALIZED,
            actor=actor,
            description=approve_desc,
            metadata={
                "decision": CommitteeReview.Decision.APPROVED,
                "remarks": remarks,
                "approve_votes": status["total_approved"],
                "reject_votes": status["total_rejected"],
                "single_approver": single,
                "votes_needed": status["votes_needed"],
            },
            request=request,
        )
        return "approved"

    return None


def record_committee_vote(application, user, vote, remarks="", request=None):
    """Save one approver vote and finalize the application when rules are met."""
    from django_fsm import TransitionNotAllowed

    from .audit import record_loan_audit
    from .models import LoanApplication, LoanApplicationAuditLog, LoanCommitteeVote

    if not user_can_committee_vote(user):
        raise PermissionDenied(
            "Only admins, loan officers, staff, and credit committee members may vote."
        )

    if application.status != LoanApplication.Status.PENDING_COMMITTEE_APPROVAL:
        raise TransitionNotAllowed(
            f"Cannot vote while application status is {application.status}."
        )

    LoanCommitteeVote.objects.update_or_create(
        application=application,
        user=user,
        defaults={"vote": vote, "remarks": remarks},
    )
    vote_label = dict(LoanCommitteeVote.Vote.choices).get(vote, vote)
    record_loan_audit(
        application,
        LoanApplicationAuditLog.Action.COMMITTEE_VOTE,
        actor=user,
        description=f"Committee vote recorded: {vote_label}.",
        metadata={"vote": vote, "remarks": remarks},
        request=request,
    )

    outcome = try_finalize_committee_approval(
        application, remarks=remarks, actor=user, request=request
    )
    if outcome == "rejected":
        return "rejected"
    if outcome == "approved":
        return "approved"
    return "pending"


def get_grace_period_days():
    """Days after due date before late-payment interest applies (Loan Settings)."""
    from .models import LoanSettings

    return int(getattr(LoanSettings.get(), "grace_period_days", 0) or 0)


def overdue_cutoff_date(as_of_date=None):
    """Installments with ``due_date`` before this date are past the grace period.

    Grace of 0 keeps the previous rule: unpaid the day after the due date is late.
    Grace of 5 means an Aug 1 due date is still on-time through Aug 6.
    """
    as_of_date = as_of_date or timezone.localdate()
    return as_of_date - timedelta(days=get_grace_period_days())


def is_installment_past_grace(due_date, as_of_date=None):
    """True when unpaid past due date *and* the configured grace period."""
    if due_date is None:
        return False
    return due_date < overdue_cutoff_date(as_of_date)


def compute_repayment_capacity_score(member, exclude_application=None):
    """Auto repayment score for credit investigation.

    Starts at 100. If the member has prior loan application records and any
    unpaid installments past their due date (payment non-compliance), each
    such installment reduces the score by 0.1. Floor is 0.0.
    """
    from .models import AmortizationSchedule, LoanApplication

    today = timezone.localdate()
    prior_apps = LoanApplication.objects.filter(member=member)
    if exclude_application is not None:
        prior_apps = prior_apps.exclude(pk=exclude_application.pk)

    prior_count = prior_apps.count()
    if prior_count == 0:
        return {
            "score": BASE_REPAYMENT_SCORE,
            "prior_loan_count": 0,
            "noncompliant_count": 0,
            "penalty": Decimal("0.0"),
            "explanation": "No prior loan applications on record. Score starts at 100.",
        }

    prior_ids = list(prior_apps.values_list("pk", flat=True))
    noncompliant_count = AmortizationSchedule.objects.filter(
        application_id__in=prior_ids,
        is_paid=False,
        due_date__lt=overdue_cutoff_date(today),
    ).count()

    penalty = (NONCOMPLIANCE_PENALTY * noncompliant_count).quantize(ONE_PLACE)
    score = max(Decimal("0.0"), BASE_REPAYMENT_SCORE - penalty).quantize(ONE_PLACE)

    if noncompliant_count:
        explanation = (
            f"Prior loan applications: {prior_count}. "
            f"Unpaid past-due installments: {noncompliant_count}. "
            f"Score = 100 − ({noncompliant_count} × 0.1) = {score}."
        )
    else:
        explanation = (
            f"Prior loan applications: {prior_count}. "
            "All recorded installments are paid on time (or not yet due). Score stays at 100."
        )

    return {
        "score": score,
        "prior_loan_count": prior_count,
        "noncompliant_count": noncompliant_count,
        "penalty": penalty,
        "explanation": explanation,
    }


def member_loan_history(member, exclude_application=None):
    """Prior loans for a member so staff can judge repayment standing.

    Used on eligibility verification (and similar review screens) to see
    whether the member has been a good client: paid in full, on time, or
    carrying unpaid overdue installments.
    """
    from .models import LoanApplication

    Status = LoanApplication.Status
    funded_statuses = {
        Status.DISBURSED,
        Status.ACTIVE,
        Status.FULLY_PAID,
        Status.CLOSED,
    }
    settled_statuses = {Status.FULLY_PAID, Status.CLOSED}
    denied_statuses = {Status.REJECTED, Status.VERIFICATION_FAILED}

    prior_apps = (
        LoanApplication.objects.filter(member=member)
        .select_related("loan_product", "disbursement")
        .prefetch_related(
            "amortization_schedules",
            "payments",
            "delinquency_records",
        )
        .order_by("-created_at")
    )
    if exclude_application is not None:
        prior_apps = prior_apps.exclude(pk=exclude_application.pk)

    cutoff = overdue_cutoff_date()
    rows = []
    fully_paid_count = 0
    funded_count = 0
    denied_count = 0
    overdue_installments = 0
    outstanding_total = Decimal("0.00")
    paid_total = Decimal("0.00")

    for app in prior_apps:
        schedules = list(app.amortization_schedules.all())
        payments = list(app.payments.all())
        paid_amount = sum((p.amount_paid for p in payments), Decimal("0.00"))
        schedule_due = sum((s.total_due for s in schedules), Decimal("0.00"))
        obligation = schedule_due if schedules else Decimal(app.amount_requested or 0)
        # Only released loans can carry a collectible balance.
        outstanding = Decimal("0.00")
        if app.status in {Status.DISBURSED, Status.ACTIVE}:
            remaining = obligation - paid_amount
            outstanding = remaining if remaining > 0 else Decimal("0.00")

        overdue_count = sum(
            1
            for s in schedules
            if (not s.is_paid) and s.due_date is not None and s.due_date < cutoff
        )
        paid_installments = sum(1 for s in schedules if s.is_paid)
        last_payment = payments[0] if payments else None
        disbursement = getattr(app, "disbursement", None)
        unresolved_delinquency = any(
            not record.resolved for record in app.delinquency_records.all()
        )

        if app.status in settled_statuses:
            record_label = "Paid in full"
            record_tone = "good"
        elif overdue_count or unresolved_delinquency:
            record_label = "Has overdue"
            record_tone = "poor"
        elif app.status == Status.ACTIVE:
            record_label = "On time"
            record_tone = "good"
        elif app.status in denied_statuses:
            record_label = "Not approved"
            record_tone = "watch"
        elif app.status in funded_statuses:
            record_label = "Released"
            record_tone = "watch"
        else:
            record_label = "Not released"
            record_tone = "neutral"

        rows.append(
            {
                "application": app,
                "product_name": app.loan_product.name if app.loan_product_id else "—",
                "amount_requested": app.amount_requested,
                "amount_released": (
                    disbursement.amount_released if disbursement is not None else None
                ),
                "applied_on": app.submitted_at or app.created_at,
                "disbursed_on": (
                    disbursement.disbursement_date if disbursement is not None else None
                ),
                "paid_amount": paid_amount,
                "outstanding": outstanding,
                "installment_count": len(schedules),
                "paid_installments": paid_installments,
                "overdue_count": overdue_count,
                "last_payment_on": last_payment.payment_date if last_payment else None,
                "record_label": record_label,
                "record_tone": record_tone,
            }
        )

        if app.status in settled_statuses:
            fully_paid_count += 1
        if app.status in funded_statuses:
            funded_count += 1
        if app.status in denied_statuses:
            denied_count += 1
        overdue_installments += overdue_count
        outstanding_total += outstanding
        paid_total += paid_amount

    prior_count = len(rows)
    if prior_count == 0:
        standing = "new"
        standing_label = "First-time borrower"
        standing_detail = (
            "No prior loan applications on record. Review membership and documents "
            "as usual; there is no repayment history to judge."
        )
    elif overdue_installments > 0:
        standing = "poor"
        standing_label = "Poor repayment record"
        standing_detail = (
            f"{overdue_installments} unpaid overdue installment"
            f"{'s' if overdue_installments != 1 else ''} on prior loans. "
            "Review carefully before passing verification."
        )
    elif fully_paid_count > 0 and overdue_installments == 0:
        standing = "good"
        standing_label = "Good client"
        standing_detail = (
            f"{fully_paid_count} prior loan"
            f"{'s' if fully_paid_count != 1 else ''} paid in full, with no unpaid "
            "overdue installments. Repayment history supports this application."
        )
    elif funded_count > 0 and overdue_installments == 0:
        standing = "good"
        standing_label = "In good standing"
        standing_detail = (
            "Prior released loans have no unpaid overdue installments. "
            "Payments appear to be on time."
        )
    elif denied_count > 0:
        standing = "watch"
        standing_label = "Review prior applications"
        standing_detail = (
            "Previous applications were not approved. Check the table below "
            "before deciding."
        )
    else:
        standing = "watch"
        standing_label = "Limited repayment history"
        standing_detail = (
            "Prior applications exist but none were fully repaid. "
            "Use the table below when judging this member."
        )

    score_info = compute_repayment_capacity_score(
        member, exclude_application=exclude_application
    )

    return {
        "rows": rows,
        "prior_count": prior_count,
        "fully_paid_count": fully_paid_count,
        "funded_count": funded_count,
        "denied_count": denied_count,
        "overdue_installments": overdue_installments,
        "outstanding_total": outstanding_total,
        "paid_total": paid_total,
        "standing": standing,
        "standing_label": standing_label,
        "standing_detail": standing_detail,
        "score_info": score_info,
    }


def generate_amortization_schedule(application, principal=None):
    """(Re)generate a principal-only equal-monthly payment schedule.

    Interest is **not** baked into the schedule. Members who pay on or before
    each installment's due date owe principal only. Late (past-due) interest is
    applied later via :func:`apply_late_interest` using the product's
    ``interest_rate``.

    Any existing schedule rows are replaced.
    """
    from .models import AmortizationSchedule

    principal = Decimal(principal if principal is not None else application.amount_requested)
    n = application.term_months

    application.amortization_schedules.all().delete()

    if n <= 0 or principal <= 0:
        return []

    level_payment = (principal / n).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    schedules = []
    balance = principal
    today = timezone.localdate()

    for i in range(1, n + 1):
        if i == n:
            principal_due = balance
        else:
            principal_due = min(level_payment, balance)
        balance -= principal_due

        due_date = _add_months(today, i)
        schedule = AmortizationSchedule.objects.create(
            application=application,
            installment_number=i,
            due_date=due_date,
            principal_due=principal_due,
            interest_due=Decimal("0.00"),
            fees_due=Decimal("0"),
            total_due=principal_due,
        )
        schedules.append(schedule)

    return schedules


def apply_payment_option(application, option_value, actor=None, request=None, notify=True):
    """Save the repayment mode and build the matching schedule / lump-sum record.

    Monthly amortization and lump-sum payoff are mutually exclusive: choosing one
    clears the other so outstanding balance and payment collection stay consistent.
    """
    from datetime import timedelta

    from .audit import record_loan_audit
    from .models import LoanApplicationAuditLog, LumpSumPayoff, PaymentOption

    option, _created = PaymentOption.objects.update_or_create(
        application=application,
        defaults={
            "option": option_value,
            "selected_at": timezone.now(),
        },
    )

    if option_value == PaymentOption.Option.MONTHLY_AMORTIZATION:
        remaining = None
        try:
            lump = application.lump_sum_payoff
        except LumpSumPayoff.DoesNotExist:
            lump = None
        if lump is not None and not lump.is_paid:
            remaining = Decimal(lump.total_amount_due)
        LumpSumPayoff.objects.filter(application=application).delete()
        # Keep existing schedule if any installment was already paid.
        if application.amortization_schedules.filter(is_paid=True).exists():
            record_loan_audit(
                application,
                LoanApplicationAuditLog.Action.PAYMENT_OPTION,
                actor=actor,
                description=(
                    f"Payment option set to {option.get_option_display()} "
                    "(existing paid installments preserved)."
                ),
                metadata={"option": option_value},
                request=request,
            )
            if notify:
                from .notifications import notify_loan_member

                notify_loan_member(
                    application,
                    "payment_option",
                    extra={"option_label": option.get_option_display()},
                )
            return option
        generate_amortization_schedule(
            application,
            principal=remaining if remaining is not None else application.amount_requested,
        )
        record_loan_audit(
            application,
            LoanApplicationAuditLog.Action.PAYMENT_OPTION,
            actor=actor,
            description=f"Payment option set to {option.get_option_display()}.",
            metadata={"option": option_value},
            request=request,
        )
        if notify:
            from .notifications import notify_loan_member

            notify_loan_member(
                application,
                "payment_option",
                extra={"option_label": option.get_option_display()},
            )
        return option

    # Lump sum: capture remaining balance first, then drop installment rows.
    remaining = application.total_outstanding_balance()
    if remaining <= 0:
        remaining = Decimal(application.amount_requested or 0)
    application.amortization_schedules.all().delete()
    term_months = int(application.term_months or 1)
    LumpSumPayoff.objects.update_or_create(
        application=application,
        defaults={
            "maturity_date": timezone.localdate() + timedelta(days=30 * term_months),
            "total_amount_due": remaining,
            "is_paid": False,
        },
    )
    record_loan_audit(
        application,
        LoanApplicationAuditLog.Action.PAYMENT_OPTION,
        actor=actor,
        description=f"Payment option set to {option.get_option_display()}.",
        metadata={"option": option_value, "lump_sum_amount": str(remaining)},
        request=request,
    )
    if notify:
        from .notifications import notify_loan_member

        notify_loan_member(
            application,
            "payment_option",
            extra={"option_label": option.get_option_display()},
        )
    return option


def ensure_monthly_repayment_schedule(application, actor=None, request=None):
    """Create monthly amortization from the loan term when no repayment is set.

    Replaces the old Payment Option pipeline step. Existing schedules or
    lump-sum records are left unchanged.
    """
    from .models import LumpSumPayoff, PaymentOption

    if application.amortization_schedules.exists():
        return None
    try:
        application.lump_sum_payoff
        return None
    except LumpSumPayoff.DoesNotExist:
        pass
    return apply_payment_option(
        application,
        PaymentOption.Option.MONTHLY_AMORTIZATION,
        actor=actor,
        request=request,
        notify=False,
    )


def estimate_payment_schedule(principal, annual_rate_percent, term_months, interest_start_month=1):
    """Compute a monthly payment preview (principal only) without saving.

    Interest is not included in the on-time plan. ``annual_rate_percent`` and
    ``interest_start_month`` are kept for API compatibility and shown as the
    late-payment rate in the UI; they do not increase the scheduled amount.
    """
    principal = Decimal(principal or 0)
    n = int(term_months or 0)
    result = {
        "rows": [],
        "total_principal": Decimal("0.00"),
        "total_interest": Decimal("0.00"),
        "total_payment": Decimal("0.00"),
        "monthly_payment": Decimal("0.00"),
        "term_months": n,
        "late_interest_rate": Decimal(annual_rate_percent or 0),
        "late_interest_from_month": max(1, int(interest_start_month or 1)),
    }
    if principal <= 0 or n <= 0:
        return result

    level_payment = (principal / n).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    rows = []
    balance = principal
    today = timezone.localdate()

    for i in range(1, n + 1):
        if i == n:
            principal_due = balance
        else:
            principal_due = min(level_payment, balance)
        balance -= principal_due
        rows.append(
            {
                "month": i,
                "due_date": _add_months(today, i),
                "principal_due": principal_due,
                "interest_due": Decimal("0.00"),
                "total_due": principal_due,
                "has_interest": False,
            }
        )

    total_principal = sum((r["principal_due"] for r in rows), Decimal("0.00"))
    result.update(
        {
            "rows": rows,
            "total_principal": total_principal,
            "total_interest": Decimal("0.00"),
            "total_payment": total_principal,
            "monthly_payment": level_payment,
        }
    )
    return result


DAYS_PER_MONTH = Decimal("30")
ONE = Decimal("1")


def interest_per_day(principal, monthly_rate):
    """Daily interest from a monthly decimal rate over a fixed 30-day month.

    ``monthly_rate`` is a decimal fraction (e.g. ``0.015`` = 1.5%).
    Returns ₱0 when principal is fully paid (``principal <= 0``).

    Formula::
        interest_per_day = (input_interest / 30) * loan
    """
    principal = Decimal(principal or 0)
    rate = Decimal(monthly_rate or 0)
    if principal <= 0 or rate <= 0:
        return Decimal("0")
    return (rate / DAYS_PER_MONTH) * principal


def compute_interest_balance(principal, monthly_rate, usable_days):
    """Principal + accrued interest for ``usable_days``.

    Interest applies only while unpaid principal remains. When
    ``principal <= 0`` (fully paid principal), interest is ₱0.

    Formula::
        interest_per_day = (input_interest / 30) * loan
        current_balance = round((interest_per_day * usable_days) + loan)

    ``current_balance`` is rounded to the nearest peso (whole number).
    Interest is ``current_balance − principal`` so the two stay consistent.
    """
    principal = Decimal(principal or 0)
    days = max(0, int(usable_days or 0))
    if principal <= 0:
        return {
            "interest_per_day": Decimal("0"),
            "interest": Decimal("0.00"),
            "usable_days": days,
            "current_balance": Decimal("0.00"),
        }
    daily = interest_per_day(principal, monthly_rate)
    raw_interest = daily * Decimal(days)
    balance = (principal + raw_interest).quantize(ONE, rounding=ROUND_HALF_UP)
    interest = (balance - principal).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    return {
        "interest_per_day": daily,
        "interest": interest,
        "usable_days": days,
        "current_balance": balance.quantize(TWO_PLACES, rounding=ROUND_HALF_UP),
    }


def period_interest_on_remaining_principal(application, usable_days):
    """Interest for a payment usable-days period on balance left to pay.

    Each payment uses the current outstanding balance (not the original loan
    amount). Example: after a first payment leaves ₱31,400, the next period's
    interest is ``(rate ÷ 30) × 31400 × days``, not based on ₱50,000.
    """
    balance_left = Decimal(application.total_outstanding_balance() or 0)
    if balance_left <= 0:
        return Decimal("0.00")
    return compute_interest_balance(
        balance_left,
        application.effective_interest_rate(),
        usable_days,
    )["interest"]


def estimate_late_interest_amount(principal_due, monthly_rate, usable_days=30):
    """Late interest for an unpaid installment over ``usable_days``.

    Uses ``(monthly_rate / 30) × principal × days``, with balance rounded to
    the nearest peso.
    """
    return compute_interest_balance(
        principal_due, monthly_rate, usable_days
    )["interest"]


def attach_missed_payment_costs(payment_plan):
    """Enrich schedule rows with on-time vs missed-due-date amounts.

    Honours loan-product admin settings:
    - ``late_interest_rate`` (Interest rate)
    - ``late_interest_from_month`` (Interest start month)

    Months before the start month stay interest-free even if unpaid.
    From the start month onward, failing to pay adds late interest.
    """
    rate = Decimal(payment_plan.get("late_interest_rate") or 0)
    from_month = max(1, int(payment_plan.get("late_interest_from_month") or 1))
    rows = payment_plan.get("rows") or []

    total_if_on_time = Decimal("0.00")
    total_if_all_missed = Decimal("0.00")
    total_late_penalty = Decimal("0.00")

    for row in rows:
        principal = Decimal(row.get("principal_due") or 0)
        month_no = int(row.get("month") or 0)
        on_time_pay = principal
        before_start = month_no < from_month
        can_get_late = (not before_start) and (not row.get("is_paid")) and rate > 0

        if can_get_late:
            if row.get("is_overdue") and Decimal(row.get("interest_due") or 0) > 0:
                late_interest = Decimal(row["interest_due"])
            else:
                # Preview one 30-day month of late interest if the due date is missed.
                late_interest = estimate_late_interest_amount(
                    principal, rate, usable_days=30
                )
        else:
            late_interest = Decimal("0.00")

        if_missed = (principal + late_interest).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        row["on_time_pay"] = on_time_pay
        row["late_interest_if_missed"] = late_interest
        row["total_if_missed"] = if_missed
        row["before_interest_start"] = before_start
        row["can_get_late_interest"] = can_get_late
        row["interest_start_month"] = from_month
        row["interest_rate"] = rate

        total_if_on_time += on_time_pay
        total_if_all_missed += if_missed
        total_late_penalty += late_interest

    payment_plan["total_if_on_time"] = total_if_on_time.quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )
    payment_plan["total_if_all_missed"] = total_if_all_missed.quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )
    payment_plan["total_late_penalty_if_missed"] = total_late_penalty.quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )
    return payment_plan


def allocate_payments_to_schedule(payment_plan, total_paid):
    """Mark schedule months Paid / Partial / Unpaid from recorded payment totals.

    Payments are applied earliest-month-first against each row's on-time amount
    (principal). This lets the member UI reflect coverage even when installment
    ``is_paid`` flags were not updated (partial pays, lump-sum mode, estimates).
    """
    remaining = Decimal(total_paid or 0)
    if remaining < 0:
        remaining = Decimal("0.00")

    paid_months = 0
    partial_months = 0
    rows = payment_plan.get("rows") or []

    for row in rows:
        due = Decimal(row.get("on_time_pay") or row.get("principal_due") or row.get("total_due") or 0)
        if due < 0:
            due = Decimal("0.00")

        applied = min(remaining, due)
        remaining -= applied
        left_on_row = due - applied

        if due <= 0 or left_on_row <= 0:
            row["is_paid"] = True
            row["payment_status"] = "paid"
            row["amount_applied"] = due
            row["amount_remaining"] = Decimal("0.00")
            paid_months += 1
        elif applied > 0:
            row["is_paid"] = False
            row["payment_status"] = "partial"
            row["amount_applied"] = applied
            row["amount_remaining"] = left_on_row
            partial_months += 1
        else:
            row["is_paid"] = False
            row["payment_status"] = "unpaid"
            row["amount_applied"] = Decimal("0.00")
            row["amount_remaining"] = due

        # Recompute late-interest eligibility now that payment coverage is known.
        if row["is_paid"]:
            row["can_get_late_interest"] = False

    payment_plan["paid_months"] = paid_months
    payment_plan["partial_months"] = partial_months
    payment_plan["unpaid_months"] = max(0, len(rows) - paid_months - partial_months)
    payment_plan["payment_credit_remaining"] = remaining.quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )
    return payment_plan


def apply_late_interest(installment, as_of_date=None):
    """Apply (or clear) late interest on a single installment.

    - Paid on/before due date, or still within the grace period → ₱0 interest.
    - Principal of the loan already fully covered by payments → ₱0 interest
      (member benefit: no further interest after principal is paid).
    - Unpaid and past due date *plus* Loan Settings grace days → interest on
      principal using the monthly decimal rate prorated by day::
        interest_per_day = (rate / 30) * principal
        interest = interest_per_day * usable_days
        current_balance = round(principal + interest)  # nearest peso
    - Installments before ``interest_start_month`` never receive late interest.
    """
    as_of_date = as_of_date or timezone.localdate()
    application = installment.application
    product = application.loan_product
    interest_start = max(1, int(product.interest_start_month or 1))

    # On-time, still in grace, principal fully paid, or still in the
    # interest-free months window.
    if (
        installment.is_paid
        or application.is_principal_fully_paid()
        or not is_installment_past_grace(installment.due_date, as_of_date)
        or installment.installment_number < interest_start
    ):
        if installment.interest_due and not installment.is_paid:
            installment.interest_due = Decimal("0.00")
            installment.total_due = (
                installment.principal_due + installment.fees_due
            ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            installment.save(update_fields=["interest_due", "total_due", "updated_at"])
        return installment

    usable_days = (as_of_date - installment.due_date).days
    if usable_days <= 0:
        return installment

    late_interest = estimate_late_interest_amount(
        installment.principal_due,
        application.effective_interest_rate(),
        usable_days=usable_days,
    )

    new_total = (
        installment.principal_due + late_interest + installment.fees_due
    ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    if installment.interest_due != late_interest or installment.total_due != new_total:
        installment.interest_due = late_interest
        installment.total_due = new_total
        installment.save(update_fields=["interest_due", "total_due", "updated_at"])

    return installment


def refresh_schedule_interest(application, as_of_date=None):
    """Sync interest on all unpaid installments for late-vs-on-time rules."""
    as_of_date = as_of_date or timezone.localdate()
    updated = []
    for installment in application.amortization_schedules.filter(is_paid=False).order_by(
        "installment_number"
    ):
        updated.append(apply_late_interest(installment, as_of_date=as_of_date))
    return updated


def _add_months(source_date, months):
    month_index = source_date.month - 1 + months
    year = source_date.year + month_index // 12
    month = month_index % 12 + 1
    day = min(source_date.day, _days_in_month(year, month))
    return source_date.replace(year=year, month=month, day=day)


def _days_in_month(year, month):
    if month == 12:
        next_month_first = timezone.datetime(year + 1, 1, 1)
    else:
        next_month_first = timezone.datetime(year, month + 1, 1)
    first_of_month = timezone.datetime(year, month, 1)
    return (next_month_first - first_of_month).days


def allocate_or_number(payment):
    """Assign a unique official receipt number if the payment has none.

    Format: LOR-YYYYMMDD-###### (loan official receipt + date + payment id).
    Existing manual OR numbers are left unchanged for audit integrity.
    """
    if (payment.or_number or "").strip():
        return payment.or_number
    payment_day = timezone.localdate(payment.payment_date)
    payment.or_number = f"LOR-{payment_day:%Y%m%d}-{payment.pk:06d}"
    payment.save(update_fields=["or_number", "updated_at"])
    return payment.or_number


def ensure_payment_or_numbers(payments):
    """Backfill missing OR numbers on a payment queryset/list for audit trail."""
    updated = []
    for payment in payments:
        if not (payment.or_number or "").strip():
            allocate_or_number(payment)
            updated.append(payment)
    return updated


def build_payment_receipt_context(application, payment):
    """Transparency breakdown for a printable loan payment official receipt."""
    from django.db.models import Q, Sum

    from .models import LoanSettings

    principal = Decimal(application.amount_requested or 0)
    rate = Decimal(application.effective_interest_rate() or 0)
    amount_paid = Decimal(payment.amount_paid or 0)
    period_interest = Decimal(payment.period_interest or 0)

    prior_qs = application.payments.filter(
        Q(payment_date__lt=payment.payment_date)
        | Q(payment_date=payment.payment_date, pk__lt=payment.pk)
    )
    prior_paid = Decimal(
        prior_qs.aggregate(total=Sum("amount_paid")).get("total") or 0
    )
    prior_interest = Decimal(
        prior_qs.aggregate(total=Sum("period_interest")).get("total") or 0
    )

    paid_through = prior_paid + amount_paid
    interest_through = prior_interest + period_interest

    outstanding_before = (principal + prior_interest - prior_paid).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )
    if outstanding_before < 0:
        outstanding_before = Decimal("0.00")

    outstanding_after = (principal + interest_through - paid_through).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )
    if outstanding_after < 0:
        outstanding_after = Decimal("0.00")

    remaining_principal_before = (principal - prior_paid).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )
    if remaining_principal_before < 0:
        remaining_principal_before = Decimal("0.00")

    remaining_principal_after = (principal - paid_through).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )
    if remaining_principal_after < 0:
        remaining_principal_after = Decimal("0.00")

    usable_days = int(payment.usable_days or 0)
    if payment.usable_from and payment.usable_to and usable_days <= 0:
        usable_days = (payment.usable_to - payment.usable_from).days

    daily = interest_per_day(outstanding_before, rate)
    interest_breakdown = compute_interest_balance(
        outstanding_before, rate, usable_days
    )

    grace_days = int(LoanSettings.get().grace_period_days or 0)
    disbursement = getattr(application, "disbursement", None)

    rate_percent = (rate * Decimal("100")).quantize(
        Decimal("0.001"), rounding=ROUND_HALF_UP
    )

    return {
        "loan_principal": principal,
        "monthly_interest_rate": rate,
        "monthly_interest_rate_percent": rate_percent,
        "loan_term_months": application.term_months,
        "grace_period_days": grace_days,
        "usable_from": payment.usable_from,
        "usable_to": payment.usable_to,
        "usable_days": usable_days,
        "has_interest_period": bool(
            payment.usable_from and payment.usable_to and usable_days > 0
        ),
        "outstanding_before": outstanding_before,
        "outstanding_after": outstanding_after,
        "remaining_principal_before": remaining_principal_before,
        "remaining_principal_after": remaining_principal_after,
        "interest_per_day": daily.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
        "period_interest": period_interest,
        "computed_period_interest": interest_breakdown["interest"],
        "amount_paid": amount_paid,
        "cumulative_paid": paid_through,
        "cumulative_interest": interest_through,
        "disbursement": disbursement,
        "interest_formula": (
            f"(monthly rate ÷ 30) × balance × days = "
            f"({rate} ÷ 30) × ₱{outstanding_before:,.2f} × {usable_days} day"
            f"{'s' if usable_days != 1 else ''}"
        ),
    }


def record_payment(
    application,
    amount,
    collected_by,
    payment_method,
    or_number="",
    remarks="",
    payment_date=None,
    request=None,
    usable_from=None,
    usable_to=None,
    usable_days=None,
    period_interest=None,
):
    """Record a payment against a loan application.

    Optional usable-days period accrues interest on the current **balance left
    to pay** (outstanding after prior payments), not the original loan amount::
        interest_per_day = (rate / 30) * balance_left
        period_interest = round(interest_per_day * usable_days)

    Refreshes late interest first (only overdue unpaid installments get interest),
    then applies the payment to the earliest unpaid installment (or marks the
    lump sum payoff as paid), and transitions the application to FULLY_PAID once
    no balance remains.

    Every payment receives an official receipt (OR) number for security/audit.
    """
    from .audit import record_loan_audit
    from .models import LoanApplicationAuditLog, Payment

    amount = Decimal(amount)
    payment_date = payment_date or timezone.now()
    payment_day = timezone.localdate(payment_date)
    period_interest = Decimal(period_interest or 0).quantize(
        TWO_PLACES, rounding=ROUND_HALF_UP
    )

    if usable_from and usable_to and usable_days is None:
        usable_days = (usable_to - usable_from).days

    # Interest is always derived from balance left to pay at payment time.
    balance_left = Decimal(application.total_outstanding_balance() or 0)
    if balance_left <= 0:
        period_interest = Decimal("0.00")
    elif usable_from and usable_to and usable_days:
        period_interest = period_interest_on_remaining_principal(
            application, usable_days
        )
    else:
        period_interest = Decimal("0.00")

    # Charge interest only on installments unpaid past their due date.
    refresh_schedule_interest(application, as_of_date=payment_day)

    payment = Payment.objects.create(
        application=application,
        amount_paid=amount,
        payment_date=payment_date,
        collected_by=collected_by,
        payment_method=payment_method,
        or_number=(or_number or "").strip(),
        remarks=remarks,
        usable_from=usable_from,
        usable_to=usable_to,
        usable_days=usable_days,
        period_interest=period_interest,
    )
    allocate_or_number(payment)

    # Keep application.usable_* as the original apply-time period.
    # Next payment's From is derived from the latest payment.usable_to.

    lump_sum = getattr(application, "lump_sum_payoff", None)
    if lump_sum is not None:
        remaining_after = application.total_outstanding_balance()
        if remaining_after <= 0:
            lump_sum.is_paid = True
            lump_sum.save(update_fields=["is_paid"])
        else:
            lump_sum.total_amount_due = remaining_after
            lump_sum.save(update_fields=["total_amount_due"])
    else:
        remaining = amount
        installments = application.amortization_schedules.filter(
            is_paid=False
        ).order_by("installment_number")
        for installment in installments:
            if remaining <= 0:
                break
            if remaining >= installment.total_due:
                remaining -= installment.total_due
                installment.is_paid = True
                installment.save(update_fields=["is_paid"])
                if payment.applied_to_installment_id is None:
                    payment.applied_to_installment = installment
                    payment.save(update_fields=["applied_to_installment"])

    interest_note = ""
    if period_interest > 0:
        interest_note = (
            f" Period interest ₱{period_interest:.2f}"
            f" ({usable_days or 0} usable days)."
        )

    record_loan_audit(
        application,
        LoanApplicationAuditLog.Action.PAYMENT_RECORDED,
        actor=collected_by,
        description=(
            f"Payment of ₱{amount:.2f} recorded. Official receipt {payment.or_number}."
            f"{interest_note}"
        ),
        metadata={
            "payment_id": payment.pk,
            "amount": str(amount),
            "or_number": payment.or_number,
            "payment_method": payment_method,
            "remarks": remarks,
            "usable_from": str(usable_from) if usable_from else "",
            "usable_to": str(usable_to) if usable_to else "",
            "usable_days": usable_days,
            "period_interest": str(period_interest),
        },
        request=request,
    )

    from .notifications import notify_loan_member

    notify_loan_member(
        application,
        "payment",
        extra={
            "payment": payment,
            "outstanding": application.total_outstanding_balance(),
        },
    )

    if _is_fully_settled(application):
        if application.status == application.Status.ACTIVE:
            application.mark_fully_paid()
            application.save(update_fields=["status"])

    return payment


def _is_fully_settled(application):
    return application.total_outstanding_balance() <= 0 and (
        application.payments.exists()
        or application.amortization_schedules.exists()
        or getattr(application, "lump_sum_payoff", None) is not None
    )


def _member_display_name(member):
    """Best-effort display name for a Django user / applicant."""
    getter = getattr(member, "get_full_name", None)
    if callable(getter):
        full = (getter() or "").strip()
        if full:
            return full
    return str(member)


def build_loan_agreement_context(application):
    """Collect loan details used by the on-screen and PDF payment contract."""
    product = application.loan_product
    late_rate = application.effective_interest_rate()
    plan = estimate_payment_schedule(
        application.amount_requested,
        late_rate,
        application.term_months,
        product.interest_start_month,
    )
    attach_missed_payment_costs(plan)
    member_name = _member_display_name(application.member)
    today = timezone.localdate()
    # Interest is charged at payment time from usable dates, not at apply time.
    interest_breakdown = application.interest_balance_breakdown()
    total_on_time = (
        plan.get("total_if_on_time")
        or plan.get("total_payment")
        or Decimal(application.amount_requested or 0)
    )
    return {
        "application": application,
        "member_name": member_name,
        "product": product,
        "plan": plan,
        "issued_on": today,
        "application_ref": str(application.id)[:8].upper(),
        "monthly_payment": plan.get("monthly_payment") or Decimal("0.00"),
        "total_on_time": total_on_time,
        "interest_breakdown": interest_breakdown,
        "late_rate": late_rate,
        "interest_start_month": product.interest_start_month,
        "purpose": (application.purpose or "").strip() or "—",
    }


def generate_loan_agreement(application, documentation=None):
    """Generate a payment contract PDF from the loan application and attach it.

    Creates/updates ``LoanDocumentation.agreement_file``. Returns the documentation.
    """
    from .models import LoanDocumentation

    if documentation is None:
        documentation, _ = LoanDocumentation.objects.get_or_create(application=application)

    ctx = build_loan_agreement_context(application)
    buffer_path = (
        Path(settings.MEDIA_ROOT) / "loan_agreements" / f"{application.id}_contract.pdf"
    )
    buffer_path.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(buffer_path), pagesize=letter)
    width, height = letter
    left = 54
    right = width - 54
    y = height - 56

    def new_page():
        nonlocal y
        pdf.showPage()
        y = height - 56

    def ensure_space(needed=48):
        nonlocal y
        if y < needed:
            new_page()

    def draw_wrapped(text, font="Helvetica", size=10, leading=14, max_width=None):
        nonlocal y
        max_width = max_width or (right - left)
        pdf.setFont(font, size)
        words = str(text).split()
        if not words:
            y -= leading
            return
        line = words[0]
        for word in words[1:]:
            trial = f"{line} {word}"
            if pdf.stringWidth(trial, font, size) <= max_width:
                line = trial
            else:
                ensure_space(leading + 20)
                pdf.drawString(left, y, line)
                y -= leading
                line = word
        ensure_space(leading + 20)
        pdf.drawString(left, y, line)
        y -= leading

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawCentredString(width / 2, y, "LOAN PAYMENT CONTRACT")
    y -= 18
    pdf.setFont("Helvetica", 10)
    pdf.drawCentredString(
        width / 2,
        y,
        f"Application Ref. LPC-{ctx['application_ref']}  |  Issued {ctx['issued_on']:%B %d, %Y}",
    )
    y -= 28

    paragraphs = [
        (
            f"This Loan Payment Contract is entered into between the Cooperative "
            f"(the Lender) and {ctx['member_name']} (the Borrower) for the loan product "
            f"\"{ctx['product'].name}\"."
        ),
        (
            f"1. LOAN AMOUNT. The Borrower applied for and, upon approval and "
            f"disbursement, agrees to repay a principal amount of "
            f"PHP {application.amount_requested:,.2f}."
        ),
        (
            f"2. TERM. The repayment term is {application.term_months} month(s), "
            f"payable in equal monthly installments of approximately "
            f"PHP {ctx['monthly_payment']:,.2f} when paid on or before each due date."
        ),
        (
            f"3. PURPOSE. {ctx['purpose']}"
        ),
        (
            f"4. INTEREST. No interest is charged when an installment is paid on or "
            f"before its due date. Late-payment interest at a monthly rate of "
            f"{Decimal(ctx['late_rate'])} (daily rate = monthly rate ÷ 30) applies from installment month "
            f"{ctx['interest_start_month']} onward if an installment remains unpaid after its due date."
        ),
        (
            f"5. TOTAL IF PAID ON TIME. If all installments are paid on time, the "
            f"Borrower shall pay a total of PHP {ctx['total_on_time']:,.2f} "
            f"(principal only; PHP 0.00 interest)."
        ),
        (
            "6. PAYMENT SCHEDULE. The Borrower agrees to pay according to the "
            "monthly schedule below (or the official amortization schedule issued "
            "upon disbursement)."
        ),
    ]
    for paragraph in paragraphs:
        draw_wrapped(paragraph, size=10, leading=13)
        y -= 6

    y -= 4
    ensure_space(80)
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(left, y, "Month")
    pdf.drawString(left + 55, y, "Due date")
    pdf.drawString(left + 160, y, "Principal due")
    pdf.drawString(left + 280, y, "Pay on time")
    y -= 4
    pdf.line(left, y, right, y)
    y -= 14

    for row in ctx["plan"].get("rows") or []:
        ensure_space(28)
        pdf.setFont("Helvetica", 9)
        due = row.get("due_date")
        due_txt = due.strftime("%b %d, %Y") if due else "—"
        principal = row.get("principal_due") or Decimal("0.00")
        on_time = row.get("on_time_pay") or row.get("total_due") or principal
        pdf.drawString(left, y, str(row.get("month")))
        pdf.drawString(left + 55, y, due_txt)
        pdf.drawString(left + 160, y, f"PHP {principal:,.2f}")
        pdf.drawString(left + 280, y, f"PHP {on_time:,.2f}")
        y -= 13

    y -= 10
    draw_wrapped(
        "7. BORROWER UNDERTAKING. The Borrower acknowledges the loan details above "
        "and agrees to repay the loan according to this contract and cooperative policy.",
        size=10,
        leading=13,
    )
    y -= 8
    draw_wrapped(
        "8. SIGNATURES. By signing below, the parties confirm they have read and "
        "accepted this Loan Payment Contract.",
        size=10,
        leading=13,
    )

    ensure_space(150)
    y -= 10
    sig_width = 200
    sig_height = 70
    line_y = y - sig_height - 4

    def _draw_signature_image(image_field, x, bottom_y):
        if not image_field:
            return False
        try:
            image_path = image_field.path
        except (ValueError, NotImplementedError):
            return False
        if not Path(image_path).exists():
            return False
        pdf.drawImage(
            image_path,
            x,
            bottom_y,
            width=sig_width,
            height=sig_height,
            preserveAspectRatio=True,
            mask="auto",
            anchor="sw",
        )
        return True

    borrower_drawn = _draw_signature_image(
        getattr(documentation, "borrower_signature", None),
        left,
        line_y + 6,
    )
    personnel_drawn = _draw_signature_image(
        getattr(documentation, "personnel_signature", None),
        left + 280,
        line_y + 6,
    )

    pdf.setStrokeColorRGB(0.58, 0.64, 0.72)
    pdf.line(left, line_y, left + 220, line_y)
    pdf.line(left + 280, line_y, left + 500, line_y)
    pdf.setStrokeColorRGB(0, 0, 0)

    y = line_y - 14
    pdf.setFont("Helvetica", 10)
    pdf.drawString(left, y, "Borrower signature / date")
    pdf.drawString(left + 280, y, "Authorized personnel / date")
    y -= 12
    pdf.setFont("Helvetica-Oblique", 9)
    pdf.drawString(left, y, ctx["member_name"])

    borrower_at = getattr(documentation, "signed_by_borrower_at", None)
    personnel_at = getattr(documentation, "signed_by_authorized_personnel_at", None)
    y -= 12
    pdf.setFont("Helvetica", 8)
    if borrower_drawn and borrower_at:
        local_at = timezone.localtime(borrower_at)
        pdf.drawString(left, y, f"Signed {local_at:%b %d, %Y %I:%M %p}")
    if personnel_drawn and personnel_at:
        local_at = timezone.localtime(personnel_at)
        pdf.drawString(left + 280, y, f"Signed {local_at:%b %d, %Y %I:%M %p}")

    pdf.showPage()
    pdf.save()

    with open(buffer_path, "rb") as fh:
        documentation.agreement_file.save(
            f"{application.id}_contract.pdf",
            ContentFile(fh.read()),
            save=False,
        )
    documentation.save(update_fields=["agreement_file", "updated_at"])
    return documentation


def generate_clearance_certificate(application):
    """Render a simple clearance certificate PDF to MEDIA_ROOT and attach it.

    Returns the relative media path of the generated PDF.
    """
    from .models import LoanSettlement

    buffer_path = (
        Path(settings.MEDIA_ROOT) / "clearance_certificates" / f"{application.id}.pdf"
    )
    buffer_path.parent.mkdir(parents=True, exist_ok=True)

    pdf_canvas = canvas.Canvas(str(buffer_path), pagesize=letter)
    width, height = letter

    pdf_canvas.setFont("Helvetica-Bold", 18)
    pdf_canvas.drawCentredString(width / 2, height - 100, "CERTIFICATE OF LOAN CLEARANCE")

    pdf_canvas.setFont("Helvetica", 12)
    member_name = _member_display_name(application.member)
    lines = [
        f"This certifies that {member_name or application.member} has fully settled",
        f"Loan Application #{application.id} ({application.loan_product.name}) in the",
        f"principal amount of {application.amount_requested}.",
        "",
        f"Date issued: {timezone.localdate().isoformat()}",
    ]
    y = height - 160
    for line in lines:
        pdf_canvas.drawCentredString(width / 2, y, line)
        y -= 24

    pdf_canvas.showPage()
    pdf_canvas.save()

    relative_path = f"clearance_certificates/{application.id}.pdf"

    settlement, _ = LoanSettlement.objects.get_or_create(
        application=application,
        defaults={"closure_date": timezone.now()},
    )
    with open(buffer_path, "rb") as fh:
        settlement.clearance_document.save(
            f"{application.id}.pdf", ContentFile(fh.read()), save=False
        )
    settlement.clearance_issued = True
    settlement.save(update_fields=["clearance_document", "clearance_issued"])

    return relative_path


def notify_applicant_of_disapproval(application):
    """Notify the member of the application's current status (email + log)."""
    from .notifications import notify_loan_status_change

    return notify_loan_status_change(application, application.status)


def _save_review_staff_signature(review, data_url):
    """Persist a canvas data-URL onto CommitteeReview.staff_signature."""
    if not data_url or not data_url.startswith("data:image"):
        return False
    try:
        header, encoded = data_url.split(",", 1)
    except ValueError:
        return False
    ext = "png"
    if "jpeg" in header or "jpg" in header:
        ext = "jpg"
    raw = base64.b64decode(encoded)
    filename = f"staff_decision_{uuid.uuid4().hex[:10]}.{ext}"
    review.staff_signature.save(filename, ContentFile(raw), save=True)
    return True


def advance_application_to_approved(
    application,
    user,
    remarks="Staff approved via loan desk.",
    staff_signature_data="",
):
    """Advance an underwriting-stage application all the way to APPROVED.

    Creates the eligibility / investigation / committee records as needed and
    fires the FSM transitions in order. Safe to call from any of:
    SUBMITTED, UNDER_VERIFICATION, UNDER_INVESTIGATION, PENDING_COMMITTEE_APPROVAL.
    """
    from django_fsm import TransitionNotAllowed

    from .models import (
        CommitteeReview,
        CreditInvestigation,
        EligibilityVerification,
        LoanApplication,
    )

    def _reload():
        # Protected FSMField breaks refresh_from_db(); re-fetch instead.
        return LoanApplication.objects.get(pk=application.pk)

    Status = LoanApplication.Status
    allowed = {
        Status.SUBMITTED,
        Status.UNDER_VERIFICATION,
        Status.UNDER_INVESTIGATION,
        Status.PENDING_COMMITTEE_APPROVAL,
    }
    application = _reload()
    if application.status not in allowed:
        raise TransitionNotAllowed(
            f"Cannot approve from status {application.status}."
        )

    maturity = application_membership_maturity(application)
    if not maturity.get("allowed"):
        raise TransitionNotAllowed(
            maturity.get("message")
            or "This member has not met the minimum membership period required for loan approval."
        )

    now = timezone.now()

    # 1) Eligibility → UNDER_INVESTIGATION
    if application.status == Status.SUBMITTED:
        application.begin_verification()
        application.save(update_fields=["status"])
        application = _reload()

    if application.status == Status.UNDER_VERIFICATION:
        EligibilityVerification.objects.update_or_create(
            application=application,
            defaults={
                "verified_by": user,
                "membership_status_ok": True,
                "documents_complete": True,
                "remarks": remarks,
                "verified_at": now,
            },
        )
        application.complete_verification(True)
        application.save(update_fields=["status"])
        application = _reload()

    # 2) Investigation → PENDING_COMMITTEE_APPROVAL
    if application.status == Status.UNDER_INVESTIGATION:
        score_info = compute_repayment_capacity_score(application.member, exclude_application=application)
        CreditInvestigation.objects.update_or_create(
            application=application,
            defaults={
                "evaluated_by": user,
                "repayment_capacity_score": score_info["score"],
                "loan_purpose_assessment": remarks,
                "recommendation": CreditInvestigation.Recommendation.RECOMMEND_APPROVE,
                "remarks": remarks,
                "evaluated_at": now,
            },
        )
        application.submit_for_committee()
        application.save(update_fields=["status"])
        application = _reload()

    # 3) Committee → APPROVED
    if application.status == Status.PENDING_COMMITTEE_APPROVAL:
        review, _ = CommitteeReview.objects.update_or_create(
            application=application,
            defaults={
                "decision": CommitteeReview.Decision.APPROVED,
                "decision_date": now,
                "remarks": remarks,
            },
        )
        review.reviewed_by.add(user)
        if staff_signature_data:
            _save_review_staff_signature(review, staff_signature_data)
        application.approve()
        application.save(update_fields=["status"])
        application = _reload()

    if application.status != Status.APPROVED:
        raise TransitionNotAllowed(
            f"Approval did not complete; current status is {application.status}."
        )

    return application


def reject_application_at_committee(
    application,
    user,
    remarks="Rejected by credit committee.",
    staff_signature_data="",
):
    """Reject a loan pending committee approval (terminal REJECTED state)."""
    from django_fsm import TransitionNotAllowed

    from .models import CommitteeReview, LoanApplication

    if application.status != LoanApplication.Status.PENDING_COMMITTEE_APPROVAL:
        raise TransitionNotAllowed(
            f"Cannot reject from status {application.status}."
        )

    now = timezone.now()
    review, _ = CommitteeReview.objects.update_or_create(
        application=application,
        defaults={
            "decision": CommitteeReview.Decision.REJECTED,
            "decision_date": now,
            "remarks": remarks,
        },
    )
    review.reviewed_by.add(user)
    if staff_signature_data:
        _save_review_staff_signature(review, staff_signature_data)
    application.reject()
    application.save(update_fields=["status"])
    return application
