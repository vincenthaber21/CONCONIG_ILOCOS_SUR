import secrets

from django.contrib import admin, messages
from django.db.models import Q, Sum
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import path, reverse
from django.utils.translation import gettext_lazy as _
from django.shortcuts import render, get_object_or_404
from import_export.admin import ExportMixin, ImportExportModelAdmin

from .models import (
    CreditPayment,
    CreditPaymentLine,
    RefundReason,
    RefundReturnWindow,
    Transaction,
    TransactionItem,
    WalkInCustomer,
    WalkInCustomerProductDiscount,
)
from .resources import (
    CreditPaymentLineResource,
    CreditPaymentResource,
    RefundReasonResource,
    RefundReturnWindowResource,
    TransactionItemResource,
    TransactionResource,
    WalkInCustomerProductDiscountResource,
    WalkInCustomerResource,
)

_TXN_ADD_NONCE_CACHE_PREFIX = "txn_admin_saved_nonce:"
_TXN_ADD_NONCE_CACHE_SECONDS = 86400
_WALK_IN_SALE_STATUSES = ('completed', 'partially_refunded')


class TransactionItemInline(admin.TabularInline):
    model = TransactionItem
    extra = 0
    readonly_fields = ['total_price', 'refunded_at']
    fields = [
        'product_name',
        'product_barcode',
        'quantity',
        'unit_price',
        'manual_discount_php',
        'total_price',
        'refunded_at',
    ]


class RefundReasonInline(admin.StackedInline):
    model = RefundReason
    extra = 0
    max_num = 1
    can_delete = True
    verbose_name = "Refund Reason"
    verbose_name_plural = "Refund Reason"


def request_refund(modeladmin, request, queryset):
    eligible = queryset.filter(status='completed')
    count = eligible.update(status='refund_requested')
    skipped = queryset.exclude(status='completed').count()
    if count:
        modeladmin.message_user(request, f"{count} transaction(s) marked as Refund Requested.", messages.SUCCESS)
    if skipped:
        modeladmin.message_user(request, f"{skipped} transaction(s) skipped (only completed transactions can request a refund).", messages.WARNING)

request_refund.short_description = "Request refund for selected completed transactions"


def approve_refund(modeladmin, request, queryset):
    eligible = queryset.filter(status='refund_requested')
    count = eligible.update(status='refunded')
    skipped = queryset.exclude(status='refund_requested').count()
    if count:
        modeladmin.message_user(request, f"{count} transaction(s) approved and marked as Refunded.", messages.SUCCESS)
    if skipped:
        modeladmin.message_user(request, f"{skipped} transaction(s) skipped (only refund-requested transactions can be approved).", messages.WARNING)

approve_refund.short_description = "Approve refund for selected refund-requested transactions"


def cancel_refund_request(modeladmin, request, queryset):
    eligible = queryset.filter(status='refund_requested')
    count = eligible.update(status='completed')
    skipped = queryset.exclude(status='refund_requested').count()
    if count:
        modeladmin.message_user(request, f"{count} refund request(s) cancelled — transactions restored to Completed.", messages.SUCCESS)
    if skipped:
        modeladmin.message_user(request, f"{skipped} transaction(s) skipped (only refund-requested transactions can be cancelled).", messages.WARNING)

cancel_refund_request.short_description = "Cancel refund request (restore to Completed)"


class WalkInCustomerProductDiscountInline(admin.TabularInline):
    model = WalkInCustomerProductDiscount
    extra = 0
    can_delete = False
    show_change_link = False
    fields = [
        'product_name',
        'product',
        'total_manual_discount_php',
        'line_count',
        'last_sale_at',
        'updated_at',
    ]
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(WalkInCustomer)
class WalkInCustomerAdmin(ImportExportModelAdmin):
    resource_classes = [WalkInCustomerResource]
    list_display = [
        'display_name',
        'total_purchase_amount_display',
        'total_manual_discount_display',
        'product_discount_count',
        'last_seen_at',
        'created_at',
    ]
    list_filter = ['created_at', 'last_seen_at']
    search_fields = ['display_name', 'name_key', 'product_discounts__product_name']
    readonly_fields = [
        'name_key',
        'total_manual_discount_php',
        'created_at',
        'updated_at',
        'last_seen_at',
    ]
    ordering = ['-last_seen_at']
    inlines = [WalkInCustomerProductDiscountInline]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        sale_filter = Q(transactions__status__in=_WALK_IN_SALE_STATUSES)
        return qs.annotate(
            total_purchase_amount=Sum('transactions__total_amount', filter=sale_filter),
        )

    @admin.display(description='Total purchases ₱', ordering='total_purchase_amount')
    def total_purchase_amount_display(self, obj):
        amount = obj.total_purchase_amount or 0
        return f'₱{amount:,.2f}'

    @admin.display(description='Total discount ₱', ordering='total_manual_discount_php')
    def total_manual_discount_display(self, obj):
        return f'₱{obj.total_manual_discount_php:,.2f}'

    @admin.display(description='Products discounted')
    def product_discount_count(self, obj):
        return obj.product_discounts.count()


@admin.register(WalkInCustomerProductDiscount)
class WalkInCustomerProductDiscountAdmin(ExportMixin, admin.ModelAdmin):
    resource_classes = [WalkInCustomerProductDiscountResource]
    list_display = [
        'walk_in_customer',
        'product_name',
        'product',
        'total_manual_discount_php',
        'line_count',
        'last_sale_at',
    ]
    list_filter = ['last_sale_at', 'updated_at']
    search_fields = ['walk_in_customer__display_name', 'product_name']
    readonly_fields = [
        'walk_in_customer',
        'product',
        'product_name',
        'total_manual_discount_php',
        'line_count',
        'last_sale_at',
        'updated_at',
    ]
    ordering = ['-total_manual_discount_php', 'product_name']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Transaction)
class TransactionAdmin(ExportMixin, admin.ModelAdmin):
    resource_classes = [TransactionResource]
    list_display = [
        'transaction_number',
        'member',
        'guest_customer_name',
        'walk_in_customer',
        'total_amount',
        'payment_method',
        'status',
        'created_at',
    ]
    list_filter = ['payment_method', 'status', 'created_at']
    search_fields = [
        'transaction_number',
        'member__first_name',
        'member__last_name',
        'guest_customer_name',
        'walk_in_customer__display_name',
    ]
    readonly_fields = ['transaction_number', 'updated_at']
    inlines = [TransactionItemInline, RefundReasonInline]
    actions = [request_refund, approve_refund, cancel_refund_request]
    change_form_template = "admin/transactions/transaction/change_form.html"

    def add_view(self, request, form_url="", extra_context=None):
        if request.method == "POST":
            nonce = request.POST.get("_txn_add_nonce")
            if nonce:
                pk = cache.get(_TXN_ADD_NONCE_CACHE_PREFIX + nonce)
                if pk:
                    try:
                        obj = self.model.objects.get(pk=pk)
                    except self.model.DoesNotExist:
                        pass
                    else:
                        self.message_user(
                            request,
                            _("That transaction was already saved; duplicate submit was ignored."),
                            messages.INFO,
                        )
                        return self.response_add(request, obj)
        return super().add_view(request, form_url=form_url, extra_context=extra_context)

    def render_change_form(self, request, context, add=False, change=False, form_url="", obj=None):
        if add:
            nonce = secrets.token_hex(16)
            request.session["txn_admin_add_nonce"] = nonce
            context["txn_add_nonce"] = nonce
        return super().render_change_form(
            request, context, add=add, change=change, form_url=form_url, obj=obj
        )

    def get_form(self, request, obj=None, **kwargs):
        FormClass = super().get_form(request, obj, **kwargs)
        if obj is not None:
            return FormClass

        class TransactionAddForm(FormClass):
            def clean(self):
                cleaned_data = super().clean()
                nonce = self.data.get("_txn_add_nonce")
                expected = request.session.get("txn_admin_add_nonce")
                if not nonce or not expected or nonce != expected:
                    raise ValidationError(
                        _("This form has expired or is invalid. Open Add transaction again.")
                    )
                return cleaned_data

        return TransactionAddForm

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change and obj.pk:
            nonce = request.POST.get("_txn_add_nonce")
            if nonce:
                cache.set(
                    _TXN_ADD_NONCE_CACHE_PREFIX + nonce,
                    obj.pk,
                    _TXN_ADD_NONCE_CACHE_SECONDS,
                )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'refund-requests/',
                self.admin_site.admin_view(self.refund_requests_view),
                name='transactions_transaction_refund_requests',
            ),
            path(
                'refund-requests/<int:transaction_id>/approve/',
                self.admin_site.admin_view(self.approve_refund_view),
                name='transactions_transaction_approve_refund',
            ),
            path(
                'refund-requests/<int:transaction_id>/cancel/',
                self.admin_site.admin_view(self.cancel_refund_view),
                name='transactions_transaction_cancel_refund',
            ),
            path(
                'refund-requests/<int:transaction_id>/set-reason/',
                self.admin_site.admin_view(self.set_reason_view),
                name='transactions_transaction_set_reason',
            ),
        ]
        return custom_urls + urls

    def refund_requests_view(self, request):
        refund_transactions = (
            Transaction.objects.filter(status='refund_requested')
            .select_related('member', 'refund_reason')
            .prefetch_related('items')
            .order_by('-updated_at')
        )
        context = {
            **self.admin_site.each_context(request),
            'title': 'Refund Requests',
            'refund_transactions': refund_transactions,
            'opts': self.model._meta,
            'reason_choices': RefundReason.REASON_CHOICES,
        }
        return render(request, 'admin/transactions/transaction/refund_requests.html', context)

    def approve_refund_view(self, request, transaction_id):
        txn = get_object_or_404(Transaction, pk=transaction_id, status='refund_requested')
        txn.status = 'refunded'
        txn.save()
        self.message_user(request, f"Transaction {txn.transaction_number} approved and marked as Refunded.", messages.SUCCESS)
        return HttpResponseRedirect(reverse('admin:transactions_transaction_refund_requests'))

    def cancel_refund_view(self, request, transaction_id):
        txn = get_object_or_404(Transaction, pk=transaction_id, status='refund_requested')
        txn.status = 'completed'
        txn.save()
        self.message_user(request, f"Refund request for {txn.transaction_number} cancelled — restored to Completed.", messages.SUCCESS)
        return HttpResponseRedirect(reverse('admin:transactions_transaction_refund_requests'))

    def set_reason_view(self, request, transaction_id):
        if request.method != 'POST':
            return JsonResponse({'error': 'POST required'}, status=405)
        txn = get_object_or_404(Transaction, pk=transaction_id)
        reason_type = request.POST.get('reason_type', 'other')
        details = request.POST.get('details', '').strip()
        RefundReason.objects.update_or_create(
            transaction=txn,
            defaults={'reason_type': reason_type, 'details': details},
        )
        return JsonResponse({
            'ok': True,
            'reason_type': reason_type,
            'reason_label': dict(RefundReason.REASON_CHOICES).get(reason_type, reason_type),
            'details': details,
        })

    def changelist_view(self, request, extra_context=None):
        refund_count = Transaction.objects.filter(status='refund_requested').count()
        extra_context = extra_context or {}
        extra_context['refund_request_count'] = refund_count
        extra_context['refund_requests_url'] = reverse('admin:transactions_transaction_refund_requests')
        return super().changelist_view(request, extra_context=extra_context)


@admin.register(TransactionItem)
class TransactionItemAdmin(ExportMixin, admin.ModelAdmin):
    resource_classes = [TransactionItemResource]
    list_display = ['transaction', 'product_name', 'quantity', 'unit_price', 'total_price', 'created_at']
    list_filter = ['created_at']
    search_fields = ['product_name', 'transaction__transaction_number']
    readonly_fields = ['total_price']


@admin.register(RefundReason)
class RefundReasonAdmin(ExportMixin, admin.ModelAdmin):
    resource_classes = [RefundReasonResource]
    list_display = ['transaction', 'reason_type', 'details_short', 'created_at']
    list_filter = ['reason_type', 'created_at']
    search_fields = ['transaction__transaction_number', 'details']
    readonly_fields = ['created_at', 'updated_at']

    @admin.display(description='Details')
    def details_short(self, obj):
        return (obj.details[:60] + '…') if len(obj.details) > 60 else obj.details or '—'


@admin.register(RefundReturnWindow)
class RefundReturnWindowAdmin(ExportMixin, admin.ModelAdmin):
    resource_classes = [RefundReturnWindowResource]
    list_display = ['transaction', 'return_deadline', 'is_returned', 'approved_by', 'approved_at']
    list_filter = ['is_returned', 'return_deadline']
    search_fields = ['transaction__transaction_number']
    readonly_fields = ['approved_at', 'return_confirmed_at']


@admin.register(CreditPayment)
class CreditPaymentAdmin(ExportMixin, admin.ModelAdmin):
    resource_classes = [CreditPaymentResource]
    list_display = [
        'settlement_number',
        'member',
        'amount_paid',
        'payment_method',
        'performed_by',
        'created_at',
    ]
    list_filter = ['payment_method', 'created_at']
    search_fields = [
        'settlement_number',
        'member__first_name',
        'member__last_name',
        'member__rfid_card_number',
    ]
    readonly_fields = ['settlement_number', 'created_at']


@admin.register(CreditPaymentLine)
class CreditPaymentLineAdmin(ExportMixin, admin.ModelAdmin):
    resource_classes = [CreditPaymentLineResource]
    list_display = ['payment', 'item', 'amount_applied']
    search_fields = ['payment__settlement_number', 'item__product_name']
