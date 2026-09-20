from django.urls import path
from django.views.generic import RedirectView

from . import views

app_name = "palay_trade"

urlpatterns = [
    path("", views.PalayTradeOverviewView.as_view(), name="overview"),
    # Products are fixed (Rice Palay + Bigas).
    path("products/", views.PalayTradeProductFeaturesListView.as_view(), name="product-list"),
    path(
        "products/add/",
        RedirectView.as_view(pattern_name="palay_trade:product-list", permanent=False),
        name="product-create",
    ),
    path(
        "products/<uuid:pk>/edit/",
        views.PalayTradeProductUpdateView.as_view(),
        name="product-edit",
    ),
    path("credit/overview/", views.PalayCreditOverviewView.as_view(), name="credit-overview"),
    path("credit/", views.PalayCreditDeskView.as_view(), name="credit-desk"),
    path("credit/settings/", views.PalayCreditConfigureView.as_view(), name="credit-settings"),
    path(
        "credit/configure/",
        RedirectView.as_view(pattern_name="palay_trade:credit-settings", permanent=False),
        name="credit-configure",
    ),
    path("api/search-members/", views.api_palay_search_members, name="api-search-members"),
    path(
        "credit/members/<int:member_id>/settle/",
        views.PalayCreditMemberSettleView.as_view(),
        name="credit-settle-member",
    ),
    path(
        "trades/<uuid:pk>/settle-credit/",
        views.PalayCreditSettleView.as_view(),
        name="credit-settle",
    ),
    path("trades/new/", views.PalayTradeCreateView.as_view(), name="trade-create"),
    path("trades/<uuid:pk>/", views.PalayTradeDetailView.as_view(), name="trade-detail"),
    path("trades/<uuid:pk>/delete/", views.PalayTradeDeleteView.as_view(), name="trade-delete"),
    path("trades/<uuid:pk>/receipt/", views.PalayTradeReceiptView.as_view(), name="trade-receipt"),
    path("reports/inout/", views.export_palay_inout_report, name="export-inout"),
]
