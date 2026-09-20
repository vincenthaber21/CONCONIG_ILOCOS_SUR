from django.urls import path

from . import views

app_name = "loans"

urlpatterns = [
    path("inquiries/new/", views.LoanInquiryCreateView.as_view(), name="inquiry-create"),
    path("apply/", views.LoanApplicationCreateView.as_view(), name="application-create"),
    path("", views.LoanApplicationListView.as_view(), name="application-list"),
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
        "<uuid:pk>/payment-option/",
        views.PaymentOptionSelectView.as_view(),
        name="payment-option",
    ),
    path(
        "<uuid:pk>/payments/",
        views.PaymentCollectionView.as_view(),
        name="payment-collect",
    ),
]
