from django.contrib import admin

from . import models


@admin.register(models.PalayCreditSettings)
class PalayCreditSettingsAdmin(admin.ModelAdmin):
    list_display = ("is_enabled", "member_max_outstanding", "grace_period_days", "updated_at")

    def has_add_permission(self, request):
        return not models.PalayCreditSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(models.PalayVariety)
class PalayVarietyAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    list_filter = ("is_active",)
    search_fields = ("name", "description")
    list_editable = ("is_active",)


@admin.register(models.PalayTradeProduct)
class PalayTradeProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "variety",
        "grade",
        "stock_kg",
        "buy_price_per_kg",
        "sell_price_per_kg",
        "is_active",
    )
    list_filter = ("grade", "season", "is_active", "members_only", "variety")
    search_fields = ("name", "code", "variety__name", "description")
    list_editable = ("is_active", "stock_kg")
    autocomplete_fields = ("variety",)
    fieldsets = (
        (
            None,
            {
                "fields": ("name", "code", "variety", "grade", "season", "description", "is_active"),
            },
        ),
        (
            "Prices",
            {
                "fields": ("buy_price_per_kg", "sell_price_per_kg"),
            },
        ),
        (
            "Rice stock",
            {
                "fields": ("stock_kg", "low_stock_kg"),
                "description": "Buys add to stock; sells deduct from stock.",
            },
        ),
        (
            "Quantity & access",
            {
                "fields": ("min_quantity_kg", "max_quantity_kg", "members_only"),
            },
        ),
    )


@admin.register(models.PalayTrade)
class PalayTradeAdmin(admin.ModelAdmin):
    list_display = (
        "reference",
        "trade_type",
        "product",
        "party_name",
        "net_kg",
        "net_amount",
        "status",
        "traded_at",
    )
    list_filter = ("trade_type", "status", "product")
    search_fields = (
        "reference",
        "party_name",
        "member__first_name",
        "member__last_name",
        "product__name",
    )
    autocomplete_fields = ("member", "product")
    readonly_fields = (
        "reference",
        "net_kg",
        "gross_amount",
        "net_amount",
        "performed_by",
        "created_at",
        "updated_at",
    )
