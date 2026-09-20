from django.urls import path

from . import member_views

urlpatterns = [
    path("", member_views.member_loan_list, name="member_loan_list"),
    path("request/", member_views.member_loan_request, name="member_loan_request"),
    path("<uuid:pk>/", member_views.member_loan_detail, name="member_loan_detail"),
]
