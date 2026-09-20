from django.urls import path

from . import member_views

urlpatterns = [
    path("", member_views.member_palay_credit, name="member_palay_credit"),
]
