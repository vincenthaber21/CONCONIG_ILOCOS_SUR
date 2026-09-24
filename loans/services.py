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
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.units import mm
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

    Admin can enable/disable the waiting-period rule via
    ``LoanSettings.min_membership_enabled``. When enabled, members must wait
    ``LoanSettings.min_membership_months`` (default 3) before applying.
    Disable the rule (or set months to 0) to allow loan requests immediately.
    """
    from .models import LoanSettings

    settings_obj = LoanSettings.get()
    rule_enabled = bool(getattr(settings_obj, "min_membership_enabled", True))
    required_months = int(getattr(settings_obj, "min_membership_months", 0) or 0)
    if not rule_enabled:
        required_months = 0
    empty = {
        "allowed": True,
        "required_months": required_months,
        "rule_enabled": rule_enabled,
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
            "rule_enabled": rule_enabled,
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
        "rule_enabled": rule_enabled,
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

    # Superusers (and any other authorized voter not on the member roster) may
    # cast votes; those must count toward the threshold — especially when only
    # one approval is required.
    orphan_votes = (
        application.committee_votes.exclude(user_id__in=voter_user_ids)
        .select_related("user")
        if voter_user_ids is not None
        else application.committee_votes.none()
    )
    for vote in orphan_votes:
        voter = vote.user
        if not user_can_committee_vote(voter):
            continue
        is_approve = vote.vote == LoanCommitteeVote.Vote.APPROVE
        is_reject = vote.vote == LoanCommitteeVote.Vote.REJECT
        display_name = (
            (getattr(voter, "get_full_name", lambda: "")() or "").strip()
            or getattr(voter, "username", "")
            or "Authorized approver"
        )
        all_items.append(
            {
                "member": None,
                "user_id": voter.pk,
                "username": getattr(voter, "username", "") or "",
                "name": display_name,
                "role": "Administrator" if getattr(voter, "is_superuser", False) else "Authorized",
                "role_slug": "admin" if getattr(voter, "is_superuser", False) else "authorized",
                "vote": vote.vote,
                "voted": True,
                "approved": is_approve,
                "rejected": is_reject,
                "pending": False,
                "is_current_user": bool(
                    current_user and getattr(current_user, "pk", None) == voter.pk
                ),
                "group_label": (
                    "Administrator"
                    if getattr(voter, "is_superuser", False)
                    else "Authorized approver"
                ),
            }
        )
        votes[voter.pk] = vote

    maturity = application_membership_maturity(application)
    # Denominator is the member roster; orphan (e.g. superuser) votes still count
    # in the numerator so a single authorized approval can proceed.
    total_required = len(voters)
    total_approved = sum(1 for item in all_items if item["approved"])
    total_rejected = sum(1 for item in all_items if item["rejected"])
    if single_approver:
        votes_needed = 1
        majority_reached = total_approved >= 1
        reject_majority_reached = total_rejected >= 1
    else:
        votes_needed = _committee_votes_needed(total_required, single_approver=False)
        majority_reached = total_required == 0 or total_approved >= votes_needed
        reject_majority_reached = total_required > 0 and total_rejected >= votes_needed
    maturity_met = bool(maturity.get("allowed", False))
    current_user_id = getattr(current_user, "pk", None)
    user_vote = votes.get(current_user_id) if current_user_id else None
    if user_vote is None and current_user_id:
        user_vote = application.committee_votes.filter(user_id=current_user_id).first()
    user_can_vote = user_can_committee_vote(current_user) if current_user else False
    user_can_approve_now = bool(
        user_can_vote
        and maturity_met
        and not (user_vote and user_vote.vote == LoanCommitteeVote.Vote.APPROVE)
    )
    pending_approvers = [item for item in all_items if item["pending"]]
    if single_approver and majority_reached:
        # One yes is enough — do not keep listing remaining roster names as blockers.
        pending_approvers = []
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


COOP_FORM_NAME = "CONCONIG EAST FARMERS MULTI-PURPOSE COOPERATIVE"
COOP_FORM_ADDRESS = "Conconig East, Sta. Lucia, Ilocos Sur"
COOP_FORM_REG = "CDA Registration No. 9520-01004557 / TIN 004-964-838-000"


def _resolve_coop_logo():
    """Return ``(url, filesystem_path)`` for the Store Profile logo.

    Prefers the logo uploaded under Admin → Store Profile. Falls back to the
    static coop seal when no store logo is configured.
    """
    static_logo = Path(settings.BASE_DIR) / "static" / "images" / "coop_logo.png"
    url = ""
    path = ""
    try:
        from admin_panel.models import StoreProfile

        profile = StoreProfile.get()
    except Exception:
        profile = None
    if profile and profile.logo:
        try:
            url = profile.logo.url
        except Exception:
            url = ""
        try:
            file_path = Path(profile.logo.path)
            if file_path.exists():
                path = str(file_path)
        except Exception:
            path = ""
    if not path and static_logo.exists():
        path = str(static_logo)
    if not url and static_logo.exists():
        url = settings.STATIC_URL.rstrip("/") + "/images/coop_logo.png"
    return url, path


def _member_display_name(member):
    """Best-effort display name for a Django user / applicant."""
    getter = getattr(member, "get_full_name", None)
    if callable(getter):
        full = (getter() or "").strip()
        if full:
            return full
    return str(member)


def _resolve_member_profile(user):
    """Return the linked ``members.Member`` row for a loan applicant user, if any."""
    if user is None:
        return None
    try:
        from members.models import Member
    except Exception:
        return None
    try:
        profile = getattr(user, "member", None)
        if profile is not None and getattr(profile, "pk", None):
            return profile
    except Exception:
        pass
    qs = Member.objects.all()
    profile = qs.filter(user=user).first()
    if profile:
        return profile
    username = (getattr(user, "username", None) or "").strip()
    if username:
        return qs.filter(username=username).first()
    return None


def _format_php(amount):
    value = Decimal(amount or 0).quantize(TWO_PLACES)
    return f"{value:,.2f}"


def _amount_in_words(amount):
    """Spell out a peso amount in English for disclosure / promissory blanks."""
    ones = [
        "", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
        "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
        "Seventeen", "Eighteen", "Nineteen",
    ]
    tens = [
        "", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety",
    ]

    def under_thousand(n):
        n = int(n)
        if n == 0:
            return ""
        if n < 20:
            return ones[n]
        if n < 100:
            return f"{tens[n // 10]}{(' ' + ones[n % 10]) if n % 10 else ''}".strip()
        return f"{ones[n // 100]} Hundred{(' ' + under_thousand(n % 100)) if n % 100 else ''}"

    value = Decimal(amount or 0).quantize(TWO_PLACES)
    pesos = int(value)
    centavos = int((value - pesos) * 100)
    if pesos == 0:
        words = "Zero"
    else:
        parts = []
        billions, pesos = divmod(pesos, 1_000_000_000)
        millions, pesos = divmod(pesos, 1_000_000)
        thousands, pesos = divmod(pesos, 1_000)
        if billions:
            parts.append(f"{under_thousand(billions)} Billion")
        if millions:
            parts.append(f"{under_thousand(millions)} Million")
        if thousands:
            parts.append(f"{under_thousand(thousands)} Thousand")
        if pesos:
            parts.append(under_thousand(pesos))
        words = " ".join(parts)
    result = f"{words} Pesos"
    if centavos:
        result += f" and {under_thousand(centavos)} Centavos"
    return f"{result} Only"


def build_loan_agreement_context(application):
    """Collect loan details used by the Complete Loan Form (HTML + PDF)."""
    product = application.loan_product
    late_rate = Decimal(application.effective_interest_rate() or 0)
    plan = estimate_payment_schedule(
        application.amount_requested,
        late_rate,
        application.term_months,
        product.interest_start_month,
    )
    attach_missed_payment_costs(plan)
    today = timezone.localdate()
    interest_breakdown = application.interest_balance_breakdown()
    total_on_time = (
        plan.get("total_if_on_time")
        or plan.get("total_payment")
        or Decimal(application.amount_requested or 0)
    )

    profile = _resolve_member_profile(application.member)
    if profile:
        member_name = profile.full_name or _member_display_name(application.member)
        first_name = profile.first_name or ""
        middle_name = profile.middle_name or ""
        last_name = profile.last_name or ""
        barangay = (profile.barangay or "").strip()
        municipality = (profile.municipality or "").strip() or "Sta. Lucia"
        province = (profile.province or "").strip() or "Ilocos Sur"
        address_parts = [
            (profile.home_address or "").strip(),
            barangay,
            municipality,
            province,
        ]
        address = ", ".join(p for p in address_parts if p) or "—"
        place_taga = barangay or (profile.home_address or "").strip() or municipality
        birth_date = profile.date_of_birth
        spouse_name = (profile.spouse_full_name or "").strip()
        area = (getattr(profile, "area", None) or "").strip()
    else:
        member_name = _member_display_name(application.member)
        first_name = getattr(application.member, "first_name", "") or ""
        middle_name = ""
        last_name = getattr(application.member, "last_name", "") or ""
        barangay = ""
        municipality = "Sta. Lucia"
        province = "Ilocos Sur"
        address = "—"
        place_taga = municipality
        birth_date = None
        spouse_name = ""
        area = ""

    disbursement = getattr(application, "disbursement", None)
    if disbursement and disbursement.disbursement_date:
        date_granted = timezone.localdate(disbursement.disbursement_date)
        service_fee = Decimal(disbursement.transaction_fee or 0)
        other_charges = Decimal(disbursement.other_deduction_amount or 0)
        other_charges_label = (disbursement.other_deduction_label or "").strip() or "Others"
        net_proceeds = Decimal(disbursement.amount_released or 0)
    else:
        date_granted = today
        service_fee = Decimal("0.00")
        other_charges = Decimal("0.00")
        other_charges_label = "Others"
        net_proceeds = Decimal(application.amount_requested or 0)

    date_due = _add_calendar_months(date_granted, int(application.term_months or 0))
    amount = Decimal(application.amount_requested or 0).quantize(TWO_PLACES)
    late_rate_pct = (late_rate * Decimal("100")).quantize(Decimal("0.001"))
    finance_charges = (service_fee + other_charges).quantize(TWO_PLACES)
    # On-time loans in this system charge principal only; show zero finance interest.
    interest_on_loan = Decimal("0.00")

    payment_option = getattr(application, "payment_option", None)
    if payment_option and payment_option.option == "LUMP_SUM":
        payment_mode = "Gulpi / Lump sum"
        payment_mode_short = "gulpi"
    else:
        payment_mode = "Hulugan kada bulan / Monthly"
        payment_mode_short = "hulugan kada bulan"

    collaterals = list(application.collaterals.all())
    schedule_rows = plan.get("rows") or []
    first_due = schedule_rows[0].get("due_date") if schedule_rows else date_due

    return {
        "application": application,
        "member_name": member_name,
        "first_name": first_name,
        "middle_name": middle_name,
        "last_name": last_name,
        "barangay": barangay or place_taga,
        "place_taga": place_taga,
        "municipality": municipality,
        "province": province,
        "address": address,
        "birth_date": birth_date,
        "spouse_name": spouse_name or "—",
        "area": area or "—",
        "product": product,
        "plan": plan,
        "issued_on": today,
        "date_granted": date_granted,
        "date_due": date_due,
        "first_due": first_due,
        "application_ref": str(application.id)[:8].upper(),
        "pn_number": f"PN-{str(application.id)[:8].upper()}",
        "monthly_payment": plan.get("monthly_payment") or Decimal("0.00"),
        "total_on_time": total_on_time,
        "interest_breakdown": interest_breakdown,
        "late_rate": late_rate,
        "late_rate_pct": late_rate_pct,
        "interest_start_month": product.interest_start_month,
        "purpose": (application.purpose or "").strip() or "—",
        "amount": amount,
        "amount_php": _format_php(amount),
        "amount_words": _amount_in_words(amount),
        "term_months": int(application.term_months or 0),
        "payment_mode": payment_mode,
        "payment_mode_short": payment_mode_short,
        "is_lump_sum": payment_mode_short.startswith("gulpi"),
        "collaterals": collaterals,
        "service_fee": service_fee,
        "other_charges": other_charges,
        "other_charges_label": other_charges_label,
        "interest_on_loan": interest_on_loan,
        "finance_charges": finance_charges,
        "net_proceeds": net_proceeds,
        "coop_name": COOP_FORM_NAME,
        "coop_address": COOP_FORM_ADDRESS,
        "coop_reg": COOP_FORM_REG,
        "coop_logo_url": _resolve_coop_logo()[0],
        "authorized_personnel_name": "",
    }


def generate_loan_agreement(
    application, documentation=None, authorized_personnel_name=""
):
    """Generate the Complete Loan Form PDF (A4) and attach it to documentation.

    Creates/updates ``LoanDocumentation.agreement_file``. Returns the documentation.
    Layout follows Conconig's Complete-Loan-Form (agreement, application,
    promissory note, disclosure statement) on professional A4 pages.

    ``authorized_personnel_name`` is the logged-in staff/officer printed under
    authorized-representative signature slots.
    """
    from .models import LoanDocumentation

    if documentation is None:
        documentation, _ = LoanDocumentation.objects.get_or_create(application=application)

    ctx = build_loan_agreement_context(application)
    if authorized_personnel_name:
        ctx["authorized_personnel_name"] = authorized_personnel_name
    else:
        ctx.setdefault("authorized_personnel_name", "")
    logo_url, logo_path = _resolve_coop_logo()
    ctx["coop_logo_url"] = logo_url
    ctx["coop_logo_path"] = logo_path
    buffer_path = (
        Path(settings.MEDIA_ROOT) / "loan_agreements" / f"{application.id}_contract.pdf"
    )
    buffer_path.parent.mkdir(parents=True, exist_ok=True)

    # ISO A4 — 210mm × 297mm
    pdf = canvas.Canvas(str(buffer_path), pagesize=A4)
    width, height = A4
    margin = 18 * mm
    left = margin
    right = width - margin
    content_width = right - left
    top_y = height - margin
    bottom_y = margin + 12 * mm
    y = top_y
    page_no = 1
    total_pages = 4
    body = "Times-Roman"
    body_bold = "Times-Bold"
    ink = (0.08, 0.12, 0.18)
    muted = (0.35, 0.40, 0.48)
    rule = (0.15, 0.22, 0.28)
    fill_soft = (0.96, 0.97, 0.98)

    def set_ink(rgb=ink):
        pdf.setFillColorRGB(*rgb)
        pdf.setStrokeColorRGB(*rgb)

    def draw_page_chrome():
        """Outer frame + footer for a formal A4 document look."""
        set_ink(rule)
        pdf.setLineWidth(1.15)
        pdf.rect(10 * mm, 10 * mm, width - 20 * mm, height - 20 * mm, stroke=1, fill=0)
        pdf.setLineWidth(0.35)
        pdf.rect(11.5 * mm, 11.5 * mm, width - 23 * mm, height - 23 * mm, stroke=1, fill=0)
        pdf.setLineWidth(1)
        set_ink(muted)
        pdf.setFont(body, 7.5)
        pdf.drawString(left, 12.5 * mm, f"Ref. {ctx['application_ref']}")
        pdf.drawCentredString(
            width / 2,
            12.5 * mm,
            "Complete Loan Form — Conconig East Farmers Multi-Purpose Cooperative",
        )
        pdf.drawRightString(right, 12.5 * mm, f"Page {page_no} of {total_pages}")
        set_ink()

    def new_page():
        nonlocal y, page_no
        pdf.showPage()
        page_no += 1
        draw_page_chrome()
        y = top_y

    def ensure_space(needed=48):
        nonlocal y
        if y < bottom_y + needed:
            new_page()

    def draw_header(section_title=""):
        nonlocal y
        set_ink()
        logo_path = Path(ctx.get("coop_logo_path") or "")
        if not logo_path.exists():
            _, resolved = _resolve_coop_logo()
            logo_path = Path(resolved) if resolved else Path()
        logo_size = 22 * mm
        brand_gap = 4 * mm
        name_size = 11
        pdf.setFont(body_bold, name_size)
        name_w = pdf.stringWidth(ctx["coop_name"], body_bold, name_size)
        pdf.setFont(body, 9)
        addr_w = pdf.stringWidth(ctx["coop_address"], body, 9)
        reg_w = pdf.stringWidth(ctx["coop_reg"], body, 9)
        text_w = max(name_w, addr_w, reg_w)
        has_logo = logo_path.exists()
        block_w = (logo_size + brand_gap + text_w) if has_logo else text_w
        # Keep letterhead flush to the left content margin (professional form layout).
        block_x = left
        header_top = y
        text_x = block_x
        if has_logo:
            try:
                pdf.drawImage(
                    str(logo_path),
                    block_x,
                    header_top - logo_size,
                    width=logo_size,
                    height=logo_size,
                    preserveAspectRatio=True,
                    mask="auto",
                    anchor="sw",
                )
            except Exception:
                has_logo = False
        if has_logo:
            text_x = block_x + logo_size + brand_gap
            mid = header_top - (logo_size / 2)
            name_y = mid + 10
            addr_y = mid - 2
            reg_y = mid - 14
        else:
            # Centered text-only header when no logo is available.
            block_x = (width - block_w) / 2
            text_x = block_x
            name_y = header_top - 2
            addr_y = header_top - 15
            reg_y = header_top - 26
        pdf.setFont(body_bold, name_size)
        set_ink()
        pdf.drawString(text_x, name_y, ctx["coop_name"])
        pdf.setFont(body, 9)
        set_ink(muted)
        pdf.drawString(text_x, addr_y, ctx["coop_address"])
        pdf.drawString(text_x, reg_y, ctx["coop_reg"])
        y = (header_top - logo_size if has_logo else reg_y) - 8
        set_ink(rule)
        pdf.setLineWidth(1.4)
        pdf.line(left, y, right, y)
        y -= 2.5
        pdf.setLineWidth(0.4)
        pdf.line(left, y, right, y)
        pdf.setLineWidth(1)
        y -= 14
        set_ink()
        if section_title:
            pdf.setFont(body_bold, 12)
            pdf.drawCentredString(width / 2, y, section_title)
            y -= 16

    def draw_wrapped(
        text,
        font=body,
        size=10,
        leading=13.5,
        max_width=None,
        indent=0,
        justify=True,
        first_indent=0,
    ):
        nonlocal y
        max_width = max_width or (content_width - indent)
        pdf.setFont(font, size)
        set_ink()
        words = str(text).split()
        if not words:
            y -= leading
            return
        lines = []
        line = words[0]
        for word in words[1:]:
            trial = f"{line} {word}"
            width_limit = max_width - (first_indent if not lines else 0)
            if pdf.stringWidth(trial, font, size) <= width_limit:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
        for idx, line_text in enumerate(lines):
            ensure_space(leading + 16)
            x0 = left + indent + (first_indent if idx == 0 else 0)
            avail = max_width - (first_indent if idx == 0 else 0)
            parts = line_text.split()
            if justify and idx < len(lines) - 1 and len(parts) > 1:
                text_w = sum(pdf.stringWidth(p, font, size) for p in parts)
                gap = (avail - text_w) / (len(parts) - 1)
                cursor = x0
                for part in parts:
                    pdf.drawString(cursor, y, part)
                    cursor += pdf.stringWidth(part, font, size) + gap
            else:
                pdf.drawString(x0, y, line_text)
            y -= leading

    def draw_kv_box(rows):
        """Professional key/value panel instead of fill-in underlines."""
        nonlocal y
        row_h = 16
        box_h = row_h * len(rows) + 8
        ensure_space(box_h + 12)
        label_w = content_width * 0.34
        set_ink(fill_soft)
        pdf.rect(left, y - box_h + 4, content_width, box_h, stroke=0, fill=1)
        set_ink(rule)
        pdf.setLineWidth(0.7)
        pdf.rect(left, y - box_h + 4, content_width, box_h, stroke=1, fill=0)
        pdf.line(left + label_w, y + 4, left + label_w, y - box_h + 4)
        for i, (label, value) in enumerate(rows):
            row_top = y - i * row_h
            if i:
                pdf.line(left, row_top + 4, right, row_top + 4)
            set_ink(muted)
            pdf.setFont(body, 8.5)
            pdf.drawString(left + 6, row_top - 7, str(label).upper())
            set_ink()
            pdf.setFont(body_bold, 10)
            pdf.drawString(left + label_w + 8, row_top - 7, str(value))
        y -= box_h + 10
        pdf.setLineWidth(1)

    def draw_table(headers, rows, col_weights=None):
        nonlocal y
        col_weights = col_weights or [1] * len(headers)
        total_w = sum(col_weights)
        cols = [content_width * (w / total_w) for w in col_weights]
        row_h = 15
        header_h = 16
        ensure_space(header_h + row_h * max(len(rows), 1) + 20)
        set_ink(rule)
        pdf.setFillColorRGB(0.18, 0.25, 0.32)
        pdf.rect(left, y - header_h + 3, content_width, header_h, stroke=0, fill=1)
        pdf.setFillColorRGB(1, 1, 1)
        pdf.setFont(body_bold, 8)
        x = left
        for header, col_w in zip(headers, cols):
            pdf.drawString(x + 5, y - 8, str(header).upper())
            x += col_w
        y -= header_h
        set_ink()
        for ri, row in enumerate(rows):
            ensure_space(row_h + 12)
            if ri % 2 == 1:
                set_ink(fill_soft)
                pdf.rect(left, y - row_h + 3, content_width, row_h, stroke=0, fill=1)
            set_ink(rule)
            pdf.setLineWidth(0.4)
            pdf.rect(left, y - row_h + 3, content_width, row_h, stroke=1, fill=0)
            x = left
            set_ink()
            pdf.setFont(body, 9)
            for cell, col_w in zip(row, cols):
                pdf.drawString(x + 5, y - 8, str(cell)[:48])
                x += col_w
            y -= row_h
        pdf.setLineWidth(1)
        y -= 8

    def _draw_signature_image(image_field, x, bottom_y, sig_width=170, sig_height=48):
        """Draw signature ink bottom-aligned just above the signature line."""
        if not image_field:
            return False
        try:
            image_path = image_field.path
        except (ValueError, NotImplementedError):
            return False
        if not Path(image_path).exists():
            return False
        try:
            from io import BytesIO

            from PIL import Image as PILImage
            from reportlab.lib.utils import ImageReader

            with PILImage.open(image_path) as src:
                im = src.convert("RGBA")
            # Trim empty/transparent padding so ink sits on the rule.
            bbox = im.getbbox()
            if bbox:
                im = im.crop(bbox)
            iw, ih = im.size
            if iw <= 0 or ih <= 0:
                return False
            scale = min(sig_width / float(iw), sig_height / float(ih))
            draw_w = max(1.0, iw * scale)
            draw_h = max(1.0, ih * scale)
            # Center horizontally; keep bottom flush to the signature line.
            draw_x = x + (sig_width - draw_w) / 2.0
            buf = BytesIO()
            im.save(buf, format="PNG")
            buf.seek(0)
            pdf.drawImage(
                ImageReader(buf),
                draw_x,
                bottom_y,
                width=draw_w,
                height=draw_h,
                mask="auto",
                anchor="sw",
            )
            return True
        except Exception:
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

    borrower_sig = getattr(documentation, "borrower_signature", None)
    personnel_sig = getattr(documentation, "personnel_signature", None)
    spouse_sig = getattr(documentation, "spouse_signature", None)
    prepared_sig = getattr(documentation, "prepared_by_signature", None)
    comaker1_sig = getattr(documentation, "comaker1_signature", None)
    comaker2_sig = getattr(documentation, "comaker2_signature", None)
    borrower_at = getattr(documentation, "signed_by_borrower_at", None)
    personnel_at = getattr(documentation, "signed_by_authorized_personnel_at", None)
    spouse_at = getattr(documentation, "signed_by_spouse_at", None)
    prepared_at = getattr(documentation, "prepared_by_signed_at", None)
    comaker1_at = getattr(documentation, "signed_by_comaker1_at", None)
    comaker2_at = getattr(documentation, "signed_by_comaker2_at", None)

    spouse_display = (getattr(documentation, "spouse_signer_name", None) or "").strip()
    if not spouse_display:
        spouse_display = ctx["spouse_name"] if ctx.get("spouse_name") != "—" else ""
    prepared_display = (getattr(documentation, "prepared_by_name", None) or "").strip()
    if not prepared_display:
        prepared_display = ctx.get("authorized_personnel_name") or ""
    comaker1_display = (getattr(documentation, "comaker1_name", None) or "").strip()
    comaker2_display = (getattr(documentation, "comaker2_name", None) or "").strip()
    ctx["spouse_signer_display"] = spouse_display
    ctx["prepared_by_display"] = prepared_display
    ctx["comaker1_display"] = comaker1_display
    ctx["comaker2_display"] = comaker2_display

    def draw_dual_signatures(
        left_label,
        right_label,
        left_name="",
        right_name="",
        left_image=None,
        right_image=None,
        left_stamp=None,
        right_stamp=None,
        compact=False,
        pin_to_bottom=False,
    ):
        nonlocal y
        gap = 12 if compact else 14
        box_w = (content_width - gap) / 2
        box_h = 58 if compact else 78
        needed = (box_h + 14) if compact else (box_h + 32)
        if pin_to_bottom:
            # Keep signatures on the current page, flush above the footer.
            target_top = bottom_y + needed
            if y > target_top:
                y = target_top
        else:
            ensure_space(needed)
        boxes = (
            (left, left_label, left_name, left_image, left_stamp),
            (left + box_w + gap, right_label, right_name, right_image, right_stamp),
        )
        for x0, label, name, image, stamp in boxes:
            set_ink(fill_soft)
            pdf.roundRect(x0, y - box_h, box_w, box_h, 3, stroke=0, fill=1)
            set_ink(rule)
            pdf.setLineWidth(0.7)
            pdf.roundRect(x0, y - box_h, box_w, box_h, 3, stroke=1, fill=0)
            # Leave room under the rule for label / name / signed stamp.
            has_stamp = bool(stamp)
            line_y = y - box_h + (32 if has_stamp else (24 if compact else 28))
            sig_h = 20 if compact else 26
            if image:
                _draw_signature_image(
                    image,
                    x0 + 10,
                    line_y + 1,
                    sig_width=box_w - 20,
                    sig_height=sig_h,
                )
            set_ink(rule)
            pdf.setLineWidth(0.9)
            pdf.line(x0 + 10, line_y, x0 + box_w - 10, line_y)
            set_ink(muted)
            pdf.setFont(body, 7 if compact else 7.5)
            label_y = y - box_h + (18 if has_stamp else (12 if compact else 16))
            pdf.drawCentredString(x0 + box_w / 2, label_y, label)
            set_ink()
            pdf.setFont(body_bold, 8.5 if compact else 9)
            name_y = y - box_h + (10 if has_stamp else (4 if compact else 6))
            if name:
                pdf.drawCentredString(x0 + box_w / 2, name_y, name)
            if stamp:
                local_at = timezone.localtime(stamp)
                set_ink(muted)
                pdf.setFont(body, 6.5)
                pdf.drawCentredString(
                    x0 + box_w / 2,
                    y - box_h + 2,
                    f"Signed {local_at:%b %d, %Y %I:%M %p}",
                )
        y -= box_h + (10 if compact else 14)
        pdf.setLineWidth(1)
        set_ink()

    # ------------------------------------------------------------------ page 1: Loan Agreement
    draw_page_chrome()
    draw_header("LOAN AGREEMENT")
    draw_kv_box(
        [
            ("Date Granted", ctx["date_granted"].strftime("%B %d, %Y")),
            ("Date Due", ctx["date_due"].strftime("%B %d, %Y")),
            ("Amount of Loan", f"Php {ctx['amount_php']}"),
            ("Reference", ctx["application_ref"]),
        ]
    )

    agreement_text = (
        f"Siak ni {ctx['member_name']} a taga {ctx['place_taga']}, {ctx['municipality']}, "
        f"{ctx['province']} ket immutang ti gatad nga {ctx['amount_words']} "
        f"(Php {ctx['amount_php']}) ti {ctx['coop_name']}. Ti collateral ti nasao nga "
        f"utang ko ket ti produkto nga apet ko. Daytoy nga utang ko ket bayadak sakbay "
        f"wenno ti aldaw nga panagpaso ti nasao nga utang ko. No diak makabayad ti dayta "
        f"nga tiempo, siaannugutaak nga umay da alaen ti produkto nga adda ti uneg ti "
        f"balay ko nga awan nga pulos ti panagkedked ko. Ket no awan ti produkto nga "
        f"adda iti uneg ti balay ko kayat na sawen nga naelako kon. No diak pay la apan "
        f"bayadan, siaannugutak nga inda alaen iti aniaman nga adda iti uneg ti balayko "
        f"ket ti presio ti coop masurot. Ket no awan latta ti natibker nga rason no apay "
        f"nga saan nak nga nakabayad, siannugutak nga agfile ti {ctx['coop_name']} ti "
        f"kaso maikontra kaniak ket amin nga gastos ti abogado ket siak ti mangbayad."
    )
    draw_wrapped(agreement_text, size=10.5, leading=14.5, first_indent=18, justify=False)
    y -= 8
    draw_wrapped(
        "Kas pammatalged, agpermaak ditoy baba kasta met ti asawak, anak wenno kabsat.",
        size=10.5,
        leading=14.5,
        first_indent=18,
        justify=False,
    )
    # Pin borrower/spouse signature boxes to the bottom of page 1 only.
    draw_dual_signatures(
        "Nagan ken Pirma ti Immutang",
        "Nagan ken pirma ti asawa (anak wenno kabsat)",
        left_name=ctx["member_name"],
        right_name=spouse_display,
        left_image=borrower_sig,
        right_image=spouse_sig,
        left_stamp=borrower_at,
        right_stamp=spouse_at,
        pin_to_bottom=True,
    )

    # ------------------------------------------------------------------ page 2: Application
    new_page()
    draw_header("LOAN APPLICATION")
    app_text = (
        f"Siak ni {ctx['member_name']} agaplikar ti kantidad {ctx['amount_words']} "
        f"pesos (php {ctx['amount_php']}) nga utangen iti las-ud ti {ctx['term_months']} "
        f"a bayadak nga {ctx['payment_mode_short']}. Ti panagtinnag ko ket "
        f"Php {_format_php(ctx['monthly_payment'])} agraman ti interes."
    )
    draw_wrapped(app_text, size=10.5, leading=14.5, first_indent=18)
    y -= 4
    draw_kv_box(
        [
            ("Pagusaran / Proyekto", ctx["purpose"]),
            ("Kalawa ti taltalonen", ctx["area"]),
            ("Petsa ti panagkasapulan", ctx["date_granted"].strftime("%B %d, %Y")),
            ("Termino", f"{ctx['term_months']} bulan — {ctx['payment_mode']}"),
        ]
    )
    pdf.setFont(body_bold, 10)
    set_ink()
    pdf.drawString(left, y, "Ikarik nga usaren toy utangek kadagiti sumaganad:")
    y -= 12
    draw_table(
        ["Kaadu", "Klase / nagan ti kasapulan", "Kantidad"],
        [
            ["1", str(ctx["purpose"])[:50], f"Php {ctx['amount_php']}"],
            ["", "", ""],
            ["", "", ""],
        ],
        col_weights=[1, 4.5, 2],
    )

    pdf.setFont(body_bold, 10)
    pdf.drawString(left, y, "Dagitoy dagiti intedmi a talged wenno seguridad (collateral):")
    y -= 12
    collateral_rows = []
    if ctx["collaterals"]:
        for item in ctx["collaterals"]:
            collateral_rows.append(
                [
                    str(item.description)[:36],
                    "—",
                    f"Php {_format_php(item.estimated_value)}",
                    f"Php {ctx['amount_php']}",
                ]
            )
    else:
        collateral_rows.append(
            [
                "Produkto nga apet / as per agreement",
                str(ctx["address"])[:28],
                "—",
                f"Php {ctx['amount_php']}",
            ]
        )
    draw_table(
        ["Sanikua / talged", "Lokasyon", "Balor", "Gatad ti mautang"],
        collateral_rows,
        col_weights=[3, 2.2, 1.6, 1.8],
    )

    draw_wrapped(
        "Sertipikarik/paneknekak nga amin nga indatag ken inpalawag ko agraman dagiti "
        "dokumento ket agpaypayso ken kompleto. Ket sitataalogudak nga mangted kadagitoy "
        "nga agbalin nga seguridad/collateral para iti utangek a kantidad.",
        size=10,
        leading=13.5,
        first_indent=14,
    )
    y -= 8
    draw_dual_signatures(
        "Nagan ken Pirma iti Immutang",
        "Nagan ken Pirma ti Asawa (anak/kabsat)",
        left_name=ctx["member_name"],
        right_name=spouse_display,
        left_image=borrower_sig,
        right_image=spouse_sig,
        left_stamp=borrower_at,
        right_stamp=spouse_at,
    )
    pdf.setFont(body_bold, 10)
    pdf.drawString(left, y, "Pammaneknek ti panagutang")
    y -= 12
    draw_kv_box(
        [
            ("Umutang", ctx["member_name"]),
            ("Co-Maker 1", comaker1_display or "_______________________________"),
            ("Co-Maker 2", comaker2_display or "_______________________________"),
        ]
    )
    draw_dual_signatures(
        "Prepared By",
        "Recommending Approval / Manager",
        left_image=prepared_sig,
        left_stamp=prepared_at,
        left_name=prepared_display,
        right_image=personnel_sig,
        right_stamp=personnel_at,
        right_name=ctx.get("authorized_personnel_name") or "",
    )
    set_ink(muted)
    pdf.setFont(body, 8.5)
    pdf.drawString(
        left,
        y,
        "Action taken by:  Credit Committee (  )    Board of Directors (  )    Manager (  )",
    )
    y -= 14
    pdf.drawString(left, y, "Credit Committee: ______________   ______________   ______________")
    y -= 11
    pdf.drawString(left, y, "                Chairman                    Member                      Member")
    y -= 14
    pdf.drawString(left, y, "Board of Directors: ______________   ______________   ______________")
    y -= 11
    pdf.drawString(left, y, "                   Chairman               Vice Chairman                Member")

    # ------------------------------------------------------------------ page 3: Promissory Note
    new_page()
    draw_header("PROMISSORY NOTE")
    draw_kv_box(
        [
            ("Numero ti P.N.", ctx["pn_number"]),
            ("Petsa ti pannakaawat ti utang", ctx["date_granted"].strftime("%B %d, %Y")),
            ("Gatad", f"Php {ctx['amount_php']}"),
            ("Petsa ti Panagpaso ti utang", ctx["date_due"].strftime("%B %d, %Y")),
        ]
    )
    pn_text = (
        f"Gapu ta inawat ko/mi nga gatad I kwarta, siak/sikami {ctx['member_name']} "
        f"nga nakapirma ditoy baba ket immutang ti gatad nga {ctx['amount_words']} "
        f"ket isapatak/isapatami nga bayadan ti {ctx['coop_name']} ti "
        f"{ctx['amount_words']} (Php {ctx['amount_php']}) ken interes nga "
        f"{ctx['late_rate_pct']}% per month ({ctx['late_rate']}) babaen ti sumaganad:"
    )
    draw_wrapped(pn_text, size=10.5, leading=14.5, first_indent=18)
    y -= 4
    draw_kv_box(
        [
            ("Gatad", f"Php {ctx['amount_php']}"),
            ("Termino", f"{ctx['term_months']} bulan"),
            ("Wagas ti panagbayad", ctx["payment_mode"]),
            (
                "Petsa ti panagbayad",
                ctx["first_due"].strftime("%B %d, %Y") if ctx["first_due"] else "—",
            ),
            ("Tipu (Type of Loan)", ctx["product"].name),
        ]
    )

    draw_wrapped(
        f"No kas pangarigan saan ko nga mabayadan daytoy nga utang ko inton madanon ti "
        f"termino na, siak nga makautang ket umannugot nga agbayad ti multa (penalty) "
        f"nga {ctx['late_rate_pct']}% base suma total ko kada bulan. Kasta met nga ti "
        f"kooperatiba ket maddaan karbengan nga mangremata ti/dagiti inted me nga byenes.",
        size=10,
        leading=13.5,
    )
    y -= 4
    draw_wrapped(
        "Ket daytoy nga beyenes nga nasao ket mailako kalpasan ti _____________ "
        "aldaw/bulan manipud pannakaremata na iti kangatuan nga bidder wenno gumatang. "
        "No adda masobra ket matratar nga maisubli idiay akinkukua, ngem no agkurang, "
        "sidadaan ken mayatak nga mangbayad iti aniaman nga pagkurangan na.",
        size=10,
        leading=13.5,
        first_indent=14,
    )
    y -= 4
    draw_wrapped(
        "No daytoy ket maiyamang ti husgado, ti mangmanmaneho ket addaan karbengan "
        "nga mangsingir iti 25% nga kas Attorney's Fee ken dadduma pay nga gastos "
        "maipanggep daytoy nga kaso.",
        size=10,
        leading=13.5,
        first_indent=14,
    )
    y -= 10
    draw_dual_signatures(
        "Nagan ken Pirma ti Immutang",
        "Nagan ken Pirma ti Asawa (Anak wenno Kabsat)",
        left_name=ctx["member_name"],
        right_name=spouse_display,
        left_image=borrower_sig,
        right_image=spouse_sig,
        left_stamp=borrower_at,
        right_stamp=spouse_at,
    )
    draw_dual_signatures(
        "Nagan ken Pirma ti Co-Maker",
        "Nagan ken Pirma ti Co-Maker",
        left_name=comaker1_display,
        right_name=comaker2_display,
        left_image=comaker1_sig,
        right_image=comaker2_sig,
        left_stamp=comaker1_at,
        right_stamp=comaker2_at,
    )
    set_ink()
    pdf.setFont(body_bold, 10)
    pdf.drawString(left, y, "Dagiti Nakaimatang / Witness:")
    y -= 16
    pdf.setFont(body, 9)
    set_ink(muted)
    pdf.drawString(left, y, "______________     ______________     ______________")

    # ------------------------------------------------------------------ page 4: Disclosure Statement
    new_page()
    draw_header("DISCLOSURE STATEMENT")
    draw_kv_box(
        [
            ("Borrower", f"{ctx['last_name'] or '—'}, {ctx['first_name'] or '—'} {ctx['middle_name'] or ''}".strip()),
            (
                "Birth Date / PN#",
                f"{ctx['birth_date'].strftime('%B %d, %Y') if ctx['birth_date'] else '—'}  |  {ctx['pn_number']}",
            ),
            ("Address", ctx["address"]),
            ("Loan Type / Purpose", f"{ctx['product'].name} (X Loan) — {ctx['purpose']}"),
            (
                "Date Granted / Due",
                f"{ctx['date_granted'].strftime('%b %d, %Y')}  →  {ctx['date_due'].strftime('%b %d, %Y')}",
            ),
        ]
    )
    draw_wrapped(
        f'Pursuant to RA No. 3765 or otherwise known as the "Truth in Lending Act," '
        f"the {ctx['coop_name']} hereby discloses fully the following terms and "
        f"conditions of Credit to the Debtor, to wit:",
        size=10,
        leading=13.5,
    )
    y -= 4
    draw_table(
        ["Particulars", "Amount"],
        [
            ["LOAN GRANTED (A)", f"Php {ctx['amount_php']}"],
            ["Interest on loan", f"Php {_format_php(ctx['interest_on_loan'])}"],
            ["Service Fee", f"Php {_format_php(ctx['service_fee'])}"],
            ["TOTAL FINANCE CHARGES (B)", f"Php {_format_php(ctx['finance_charges'])}"],
            [ctx["other_charges_label"], f"Php {_format_php(ctx['other_charges'])}"],
            ["TOTAL NON-FINANCE CHARGES (C)", f"Php {_format_php(ctx['other_charges'])}"],
            ["NET LOAN PROCEEDS A-B-C (D)", f"Php {_format_php(ctx['net_proceeds'])}"],
        ],
        col_weights=[3.4, 1.6],
    )
    set_ink()
    pdf.setFont(body, 9.5)
    pdf.drawString(
        left,
        y,
        f"Interest Rate: {ctx['late_rate_pct']}% per month (late / unpaid balance)",
    )
    y -= 14
    pdf.setFont(body_bold, 10)
    pdf.drawString(left, y, "Schedule of Payment")
    y -= 12
    pdf.setFont(body, 9.5)
    if ctx["is_lump_sum"]:
        pdf.drawString(
            left + 8,
            y,
            f"a) Single Payment due on {ctx['date_due'].strftime('%b %d, %Y')} — "
            f"Php {ctx['amount_php']}",
        )
        y -= 12
        pdf.drawString(left + 8, y, "b.) Total Installment Payable —")
    else:
        pdf.drawString(left + 8, y, "a) Single Payment due on —")
        y -= 12
        pdf.drawString(
            left + 8,
            y,
            f"b.) Total Installment Payable Php {_format_php(ctx['total_on_time'])}",
        )
        y -= 12
        pdf.drawString(
            left + 18,
            y,
            f"b.1) No. of Payments {ctx['term_months']} in monthly installments — "
            f"Php {_format_php(ctx['monthly_payment'])}",
        )
    y -= 12
    # Pin Certified Correct + Co-Maker signature block to bottom of page 4.
    compact_box_h = 58
    disclosure_sig_block_h = (
        16  # "Certified Correct" + gap
        + compact_box_h
        + 10  # first signature row
        + 40  # acknowledgement text
        + 16  # date line
        + 16  # "Signed in the Presence of:"
        + compact_box_h
        + 10  # co-maker signature row
    )
    pinned_disclosure_top = bottom_y + disclosure_sig_block_h
    if y > pinned_disclosure_top:
        y = pinned_disclosure_top
    pdf.setFont(body_bold, 10)
    pdf.drawString(left, y, "Certified Correct")
    y -= 6
    draw_dual_signatures(
        "Signature of Authorized Representative",
        "Name & Signature of Borrower",
        left_image=personnel_sig,
        right_image=borrower_sig,
        left_stamp=personnel_at,
        right_stamp=borrower_at,
        left_name=ctx.get("authorized_personnel_name") or "",
        right_name=ctx["member_name"],
        compact=True,
    )
    draw_wrapped(
        "I/WE ACKNOWLEDGE RECEIPT OF THIS STATEMENT PRIOR TO THE CONSUMMATION OF THE "
        "CREDIT TRANSACTION AND THAT WE UNDERSTAND AND FULLY AGREE TO THE TERMS AND "
        "CONDITIONS THEREOF.",
        size=8.5,
        leading=11,
        justify=False,
    )
    y -= 4
    set_ink(muted)
    pdf.setFont(body, 9)
    pdf.drawString(left, y, f"Date: {ctx['issued_on'].strftime('%B %d, %Y')}")
    y -= 12
    set_ink()
    pdf.setFont(body_bold, 10)
    pdf.drawString(left, y, "Signed in the Presence of:")
    y -= 6
    draw_dual_signatures(
        "Co-Maker",
        "Co-Maker",
        left_name=comaker1_display,
        right_name=comaker2_display,
        left_image=comaker1_sig,
        right_image=comaker2_sig,
        left_stamp=comaker1_at,
        right_stamp=comaker2_at,
        compact=True,
    )

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
