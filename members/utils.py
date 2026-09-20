def member_registered_discount_for_kiosk(member):
    """
    When a member has an active Senior or PWD profile, return a small payload for kiosk UI:
    headline plus per–product-group savings (from SegmentProductGroupDiscount for senior_pwd).
    Returns None if no active concession registration.
    """
    if not member:
        return None
    from members.models import (
        PWDProfile,
        SegmentProductGroupDiscount,
        SeniorCitizenProfile,
    )

    try:
        sp = member.senior_profile
    except SeniorCitizenProfile.DoesNotExist:
        sp = None
    try:
        pp = member.pwd_profile
    except PWDProfile.DoesNotExist:
        pp = None

    if sp and sp.is_active:
        kind = "senior"
        headline = "Senior citizen pricing"
    elif pp and pp.is_active:
        kind = "pwd"
        headline = "PWD pricing"
    else:
        return None

    rules = list(
        SegmentProductGroupDiscount.objects.filter(
            segment=SegmentProductGroupDiscount.SEG_SENIOR_PWD,
            is_active=True,
        )
        .select_related("discount_group")
        .order_by("discount_group__sort_order", "discount_group__code")
    )
    details = []
    for r in rules:
        raw = (getattr(r, "label", None) or "").strip()
        if raw:
            details.append(raw)
        else:
            details.append(
                f"₱{r.amount_off} off per unit — {r.get_discount_group_display()}"
            )

    # One admin label is often reused across product groups (e.g. two dairy tiers); show each line once.
    details = list(dict.fromkeys(details))

    return {
        "kind": kind,
        "headline": headline,
        "details": details,
    }


def mask_rfid(rfid_card_number):
    """
    Mask RFID card number for security purposes.
    Shows only the last 4 characters, prefixed with asterisks.

    Args:
        rfid_card_number: The RFID card number string

    Returns:
        Masked RFID string (e.g., '0008265033' -> '******5033')
    """
    if not rfid_card_number:
        return 'N/A'
    value = str(rfid_card_number).strip()
    if not value:
        return 'N/A'
    if len(value) <= 4:
        return value
    return '******' + value[-4:]

