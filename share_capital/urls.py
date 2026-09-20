from django.urls import path

from . import views

app_name = "share_capital"

urlpatterns = [
    path("", views.ShareCapitalOverviewView.as_view(), name="overview"),
    path("products/", views.ShareCapitalProductListView.as_view(), name="product-list"),
    path("products/add/", views.ShareCapitalProductCreateView.as_view(), name="product-create"),
    path(
        "products/<uuid:pk>/edit/",
        views.ShareCapitalProductUpdateView.as_view(),
        name="product-edit",
    ),
    path("contribute/", views.ShareCapitalContributeView.as_view(), name="contribute"),
    path(
        "members/<int:pk>/",
        views.ShareCapitalMemberDetailView.as_view(),
        name="member-detail",
    ),
    path(
        "members/<int:pk>/move/",
        views.ShareCapitalMemberMoveView.as_view(),
        name="member-move",
    ),
]
