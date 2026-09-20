from django.urls import path

from . import member_views

urlpatterns = [
    path("", member_views.member_savings_list, name="member_savings_list"),
    path(
        "accounts/<uuid:pk>/",
        member_views.member_savings_account,
        name="member_savings_account",
    ),
    path(
        "accounts/<uuid:pk>/receipts/",
        member_views.member_savings_receipts_all,
        name="member_savings_receipts_all",
    ),
    path(
        "accounts/<uuid:pk>/transactions/<int:txn_id>/receipt/",
        member_views.member_savings_receipt,
        name="member_savings_receipt",
    ),
]
