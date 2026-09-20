from django.urls import path

from . import views

app_name = "savings"

urlpatterns = [
    path("", views.SavingsOverviewView.as_view(), name="overview"),
    path(
        "export/interest/",
        views.SavingsInterestExportView.as_view(),
        name="interest-export",
    ),
    path("products/", views.SavingsProductListView.as_view(), name="product-list"),
    path("products/add/", views.SavingsProductCreateView.as_view(), name="product-create"),
    path("products/<uuid:pk>/edit/", views.SavingsProductUpdateView.as_view(), name="product-edit"),
    path("accounts/open/", views.OpenSavingsAccountView.as_view(), name="account-open"),
    path("accounts/<uuid:pk>/", views.SavingsAccountDetailView.as_view(), name="account-detail"),
    path("accounts/<uuid:pk>/delete/", views.SavingsAccountDeleteView.as_view(), name="account-delete"),
    path("accounts/<uuid:pk>/move/", views.SavingsAccountMoveView.as_view(), name="account-move"),
    path(
        "accounts/<uuid:pk>/interest/",
        views.SavingsAccountCreditInterestView.as_view(),
        name="account-credit-interest",
    ),
    path("accounts/<uuid:pk>/close/", views.SavingsAccountCloseView.as_view(), name="account-close"),
    path(
        "accounts/<uuid:pk>/receipts/",
        views.SavingsReceiptBatchView.as_view(),
        name="account-receipts-all",
    ),
    path(
        "accounts/<uuid:pk>/transactions/<int:txn_id>/receipt/",
        views.SavingsTransactionReceiptView.as_view(),
        name="transaction-receipt",
    ),
]
