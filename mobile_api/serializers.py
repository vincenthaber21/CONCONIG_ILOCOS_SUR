from rest_framework import serializers
from members.models import Member, BalanceTransaction
from transactions.models import Transaction, TransactionItem


class MemberSerializer(serializers.ModelSerializer):
    """Serializer for Member account information"""
    full_name = serializers.ReadOnlyField()
    member_type_name = serializers.SerializerMethodField()
    rfid_card_number = serializers.SerializerMethodField()
    rfid_card_number_full = serializers.CharField(source='rfid_card_number', read_only=True)

    class Meta:
        model = Member
        fields = [
            'id', 'rfid_card_number', 'rfid_card_number_full', 'first_name', 'last_name',
            'full_name', 'email', 'phone', 'member_type_name',
            'balance',
            'is_active', 'date_joined', 'last_transaction'
        ]
        read_only_fields = ['id', 'date_joined', 'last_transaction']

    def get_member_type_name(self, obj):
        return obj.member_type.name if obj.member_type else None

    def get_rfid_card_number(self, obj):
        """Return full RFID card number"""
        return obj.rfid_card_number or 'N/A'


class BalanceTransactionSerializer(serializers.ModelSerializer):
    """Serializer for balance transactions"""
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    
    class Meta:
        model = BalanceTransaction
        fields = [
            'id', 'transaction_type', 'transaction_type_display',
            'amount', 'balance_before', 'balance_after',
            'notes', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class TransactionItemSerializer(serializers.ModelSerializer):
    """Serializer for transaction items"""
    class Meta:
        model = TransactionItem
        fields = [
            'id', 'product_name', 'product_barcode',
            'unit_price', 'quantity', 'manual_discount_php', 'total_price',
            'vat_amount', 'vatable_sale', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class TransactionSerializer(serializers.ModelSerializer):
    """Serializer for transactions"""
    payment_method_display = serializers.CharField(source='get_payment_method_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    items = TransactionItemSerializer(many=True, read_only=True)
    refund_details = serializers.SerializerMethodField()
    return_window_details = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            'id', 'transaction_number', 'subtotal', 'vatable_sale',
            'vat_amount', 'total_amount', 'payment_method', 'payment_method_display',
            'amount_paid', 'amount_from_balance',
            'status', 'status_display',
            'notes', 'created_at', 'items', 'refund_details', 'return_window_details'
        ]
        read_only_fields = ['id', 'transaction_number', 'created_at']

    def get_refund_details(self, obj):
        """Return refund amount, refunded items, and balance before/after for refunded transactions."""
        if obj.status not in ('refunded', 'refund_requested'):
            return None

        # Determine which items were refunded
        all_items = list(obj.items.all())
        refunded_items = all_items  # default: all
        try:
            rr = obj.refund_reason
            selected = list(rr.refund_items.all())
            if selected:
                refunded_items = selected
        except Exception:
            pass

        refund_amount = sum(i.total_price for i in refunded_items)

        # Fetch balance before/after from the linked BalanceTransaction
        balance_before = None
        balance_after = None
        from members.models import BalanceTransaction as BT
        bt = (
            BT.objects
            .filter(notes__icontains=obj.transaction_number, transaction_type='deposit')
            .order_by('-created_at')
            .first()
        )
        if bt:
            balance_before = str(bt.balance_before)
            balance_after = str(bt.balance_after)

        return {
            'refund_amount': str(refund_amount),
            'refunded_items': TransactionItemSerializer(refunded_items, many=True).data,
            'is_partial': len(refunded_items) < len(all_items),
            'balance_before': balance_before,
            'balance_after': balance_after,
        }

    def get_return_window_details(self, obj):
        """Return return-window deadline info for return_window and return_expired statuses."""
        if obj.status not in ('return_window', 'return_expired'):
            return None
        try:
            rw = obj.return_window
        except Exception:
            return None
        from django.utils import timezone
        from datetime import timedelta
        now = timezone.now()
        deadline = rw.return_deadline
        delta = deadline - now
        days_remaining = max(0, delta.days)
        hours_remaining = max(0, int(delta.total_seconds() // 3600))
        is_expired = rw.is_expired()
        from admin_panel.models import ReportScheduleConfig
        return {
            'return_deadline': deadline.isoformat(),
            'days_remaining': days_remaining,
            'hours_remaining': hours_remaining,
            'is_expired': is_expired,
            'is_returned': rw.is_returned,
            'window_days': ReportScheduleConfig.get().return_window_days,
        }


class AccountSummarySerializer(serializers.Serializer):
    """Serializer for account summary"""
    member = MemberSerializer()
    recent_transactions = TransactionSerializer(many=True)
    recent_balance_transactions = BalanceTransactionSerializer(many=True)
    total_spent_this_month = serializers.DecimalField(max_digits=10, decimal_places=2)


class FundTransferSerializer(serializers.Serializer):
    """Serializer for fund transfer requests"""
    from decimal import Decimal
    recipient_rfid = serializers.CharField(required=True, help_text="RFID card number of recipient")
    amount = serializers.DecimalField(max_digits=10, decimal_places=2, required=True, min_value=Decimal('0.01'))
    notes = serializers.CharField(required=False, allow_blank=True, max_length=500)
