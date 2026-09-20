"""Shared product tagging for member / senior–PWD segment discounts (keep in sync with checkout)."""

# Default seed for inventory.ProductDiscountGroup (display names are edited in Django admin).
SEGMENT_PRODUCT_GROUP_CHOICES = [
    ('dairy_1l_500ml', 'Dairy — 1L or 500ml only'),
    ('dairy_250ml', 'Dairy — 250ml only'),
    ('pastillas', 'Pastillas'),
    ('espasol_polvoron', 'Espasol & Polvoron'),
]

# Product field: blank = not in any segment discount group.
PRODUCT_DISCOUNT_GROUP_CHOICES = [('', '— (none)')] + SEGMENT_PRODUCT_GROUP_CHOICES
