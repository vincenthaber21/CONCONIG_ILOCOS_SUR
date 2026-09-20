"""Shared store branding for printable receipts across services."""


def get_store_profile():
    try:
        from admin_panel.models import StoreProfile

        return StoreProfile.get()
    except Exception:
        return None


def get_receipt_store_context(request, store_profile=None):
    """Return store profile, absolute logo URL, and shop name for receipts."""
    profile = store_profile or get_store_profile()
    shop_name = "Cooperative"
    logo_url = ""
    if profile:
        shop_name = profile.store_name or shop_name
        if profile.logo:
            try:
                logo_url = request.build_absolute_uri(profile.logo.url)
            except Exception:
                logo_url = profile.logo.url
    return {
        "store_profile": profile,
        "store_logo_url": logo_url,
        "shop_name": shop_name,
    }


def merge_receipt_store_context(request, context, store_profile=None):
    context.update(get_receipt_store_context(request, store_profile))
    return context
