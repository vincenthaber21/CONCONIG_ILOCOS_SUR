"""Post palay buy/sell tickets and update product rice stock."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from . import models

ZERO = Decimal("0.00")


def _money(value):
    return Decimal(value).quantize(Decimal("0.01"))


@transaction.atomic
def post_trade(
    *,
    product,
    trade_type,
    party_name,
    gross_kg,
    unit_price=None,
    member=None,
    performed_by=None,
    notes="",
    traded_at=None,
    payment_method=None,
    enforce_membership_eligibility=True,
):
    product = models.PalayTradeProduct.objects.select_for_update().get(pk=product.pk)

    if not product.is_active:
        raise ValidationError("This palay trade product is not active.")
    if product.members_only and member is None:
        raise ValidationError("This product requires a cooperative member.")

    gross = _money(gross_kg)
    if gross <= ZERO:
        raise ValidationError("Weight must be greater than zero.")

    min_qty = _money(product.min_quantity_kg)
    max_qty = _money(product.max_quantity_kg)
    if min_qty > ZERO and gross < min_qty:
        raise ValidationError(f"Weight must be at least {min_qty} kg.")
    if max_qty > ZERO and gross > max_qty:
        raise ValidationError(f"Weight cannot exceed {max_qty} kg.")

    if trade_type not in models.PalayTrade.TradeType.values:
        raise ValidationError("Invalid trade type.")

    if trade_type == models.PalayTrade.TradeType.SELL:
        available = _money(product.stock_kg)
        if gross > available:
            raise ValidationError(
                f"Not enough rice stock for {product.name}. "
                f"Available {available} kg; requested {gross} kg."
            )

    if unit_price is None:
        unit_price = (
            product.buy_price_per_kg
            if trade_type == models.PalayTrade.TradeType.BUY
            else product.sell_price_per_kg
        )
    price = _money(unit_price)
    if price <= ZERO:
        raise ValidationError("Unit price must be greater than zero.")

    amount = _money(gross * price)

    pay_method = payment_method or models.PalayTrade.PaymentMethod.CASH
    if pay_method not in models.PalayTrade.PaymentMethod.values:
        raise ValidationError("Invalid payment method.")
    if pay_method == models.PalayTrade.PaymentMethod.CREDIT:
        from . import credit_services

        credit_services.validate_palay_credit_trade(
            product=product,
            trade_type=trade_type,
            member=member,
            amount=amount,
            enforce_membership_eligibility=enforce_membership_eligibility,
        )

    trade = models.PalayTrade(
        product=product,
        trade_type=trade_type,
        member=member,
        party_name=(party_name or "").strip() or (member.full_name if member else ""),
        traded_at=traded_at or timezone.now(),
        gross_kg=gross,
        net_kg=gross,
        unit_price=price,
        gross_amount=amount,
        net_amount=amount,
        payment_method=pay_method,
        status=models.PalayTrade.Status.POSTED,
        notes=notes or "",
        performed_by=performed_by,
    )
    if not trade.party_name:
        raise ValidationError("Farmer or buyer name is required.")
    trade.save()

    if trade_type == models.PalayTrade.TradeType.BUY:
        product.stock_kg = _money(product.stock_kg) + gross
    else:
        product.stock_kg = _money(product.stock_kg) - gross
    product.save(update_fields=["stock_kg", "updated_at"])

    return trade


@transaction.atomic
def delete_trade(trade, *, performed_by=None):
    """Remove a posted trade ticket and reverse its effect on product stock."""
    trade = (
        models.PalayTrade.objects.select_related("product")
        .select_for_update()
        .get(pk=trade.pk)
    )
    product = models.PalayTradeProduct.objects.select_for_update().get(pk=trade.product_id)
    kg = _money(trade.gross_kg or trade.net_kg or ZERO)

    if trade.trade_type == models.PalayTrade.TradeType.BUY:
        available = _money(product.stock_kg)
        if kg > available:
            raise ValidationError(
                f"Cannot delete {trade.reference}: reversing this buy would make "
                f"{product.name} stock negative (available {available} kg; trade {kg} kg)."
            )
        product.stock_kg = available - kg
    elif trade.trade_type == models.PalayTrade.TradeType.SELL:
        product.stock_kg = _money(product.stock_kg) + kg
    else:
        raise ValidationError("Unknown trade type.")

    product.save(update_fields=["stock_kg", "updated_at"])
    reference = trade.reference
    trade.delete()
    return reference, product
