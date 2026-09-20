from django.contrib import admin

from . import models


@admin.register(models.ShareCapitalProduct)
class ShareCapitalProductAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "par_value",
        "min_shares",
        "max_shares",
        "dividend_rate",
        "allows_withdrawal",
        "is_active",
    )
    list_filter = ("is_active", "allows_withdrawal", "required_for_membership")
    search_fields = ("name", "code", "description")
    list_editable = ("is_active",)
    fieldsets = (
        (
            None,
            {
                "fields": ("name", "code", "description", "is_active"),
            },
        ),
        (
            "Share rules",
            {
                "fields": (
                    "par_value",
                    "min_shares",
                    "max_shares",
                    "min_contribution",
                ),
            },
        ),
        (
            "Dividends & withdrawals",
            {
                "fields": (
                    "dividend_rate",
                    "allows_withdrawal",
                    "required_for_membership",
                ),
            },
        ),
    )
