from django.urls import path

from . import views

app_name = "loans"

urlpatterns = [
    path("settings/", views.LoanSettingsView.as_view(), name="settings"),
    path("products/", views.LoanProductListView.as_view(), name="product-list"),
    path("products/add/", views.LoanProductCreateView.as_view(), name="product-create"),
    path("inquiries/new/", views.LoanInquiryCreateView.as_view(), name="inquiry-create"),
    path("apply/", views.LoanApplicationCreateView.as_view(), name="application-create"),
    path("", views.LoanApplicationListView.as_view(), name="application-list"),
    path(
        "<uuid:pk>/delete/",
        views.LoanApplicationDeleteView.as_view(),
        name="application-delete",
    ),
    path("<uuid:pk>/", views.LoanApplicationDetailView.as_view(), name="application-detail"),
    path(
        "<uuid:pk>/verify/",
        views.EligibilityVerificationView.as_view(),
        name="eligibility-verify",
    ),
    path(
        "<uuid:pk>/investigate/",
        views.CreditInvestigationView.as_view(),
        name="credit-investigate",
    ),
    path(
        "<uuid:pk>/committee-review/",
        views.CommitteeReviewView.as_view(),
        name="committee-review",
    ),
    path("<uuid:pk>/approve/", views.LoanApproveView.as_view(), name="approve"),
    path("<uuid:pk>/reject/", views.LoanRejectView.as_view(), name="reject"),
    path(
        "<uuid:pk>/insurance/",
        views.InsuranceEnrollmentView.as_view(),
        name="insurance-enroll",
    ),
    path(
        "<uuid:pk>/documentation/",
        views.LoanDocumentationView.as_view(),
        name="documentation-sign",
    ),
    path("<uuid:pk>/disburse/", views.DisbursementView.as_view(), name="disburse"),
    path(
        "<uuid:pk>/disburse/receipt/",
        views.DisbursementReceiptView.as_view(),
        name="disbursement-receipt",
    ),
    path(
        "<uuid:pk>/payment-option/",
        views.PaymentOptionSelectView.as_view(),
        name="payment-option",
    ),
    # Receipt routes must be registered before the bare payments/ path.
    path(
        "<uuid:pk>/payments/receipts/",
        views.PaymentReceiptBatchView.as_view(),
        name="payment-receipts-all",
    ),
    path(
        "<uuid:pk>/payments/<int:payment_id>/receipt/",
        views.PaymentReceiptView.as_view(),
        name="payment-receipt",
    ),
    path(
        "<uuid:pk>/payments/",
        views.PaymentCollectionView.as_view(),
        name="payment-collect",
    ),
]
