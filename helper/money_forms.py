"""Money/amount form field that accepts and displays thousand separators."""
from decimal import Decimal, InvalidOperation

from django import forms


def normalize_money_string(value):
    """Strip currency symbols and thousand separators for parsing."""
    if value is None:
        return value
    if isinstance(value, (int, float, Decimal)):
        return value
    text = str(value).strip()
    if not text:
        return text
    for token in ("₱", "Php", "PHP", "php", ","):
        text = text.replace(token, "")
    return text.strip()


def format_money_display(value, decimal_places=2):
    """Format a numeric value as 1,234.56 for display in inputs."""
    if value is None or value == "":
        return ""
    try:
        num = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return str(value)
    quant = Decimal("1").scaleb(-decimal_places)
    num = num.quantize(quant)
    return f"{num:,.{decimal_places}f}"


class MoneyInput(forms.TextInput):
    """Text input that shows amounts with thousand separators."""

    def __init__(self, attrs=None, decimal_places=2):
        self.decimal_places = decimal_places
        default = {
            "type": "text",
            "inputmode": "decimal",
            "autocomplete": "off",
            "class": "js-money-input",
            "data-decimal-places": str(decimal_places),
            "placeholder": "0." + ("0" * decimal_places),
        }
        if attrs:
            merged = {**default, **attrs}
            extra_class = attrs.get("class", "")
            parts = ["js-money-input"]
            if extra_class:
                parts.extend(
                    c for c in str(extra_class).split() if c and c != "js-money-input"
                )
            merged["class"] = " ".join(parts)
            default = merged
        super().__init__(attrs=default)

    def format_value(self, value):
        if value is None or value == "":
            return ""
        # Keep partially typed invalid values as-is on redisplay
        if isinstance(value, str):
            cleaned = normalize_money_string(value)
            try:
                Decimal(cleaned)
            except (InvalidOperation, ValueError):
                return value
            return format_money_display(cleaned, self.decimal_places)
        return format_money_display(value, self.decimal_places)


class MoneyField(forms.DecimalField):
    """Decimal field that accepts 50,000.00 style input."""

    def __init__(self, *args, decimal_places=2, widget=None, **kwargs):
        if widget is None:
            widget = MoneyInput(decimal_places=decimal_places)
        elif isinstance(widget, type):
            widget = widget()
        kwargs.setdefault("decimal_places", decimal_places)
        super().__init__(*args, widget=widget, **kwargs)

    def to_python(self, value):
        value = normalize_money_string(value)
        return super().to_python(value)


def money_input(**attrs):
    """Shortcut widget factory for ModelForm Meta.widgets."""
    return MoneyInput(attrs=attrs or None)
