from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def eur(value):
    """Format a number as Spanish-locale euros: 1234.5 -> '1.234,50 €'."""
    try:
        value = Decimal(value)
    except (InvalidOperation, TypeError):
        return value

    sign = "-" if value < 0 else ""
    value = abs(value)
    whole, _, cents = f"{value:.2f}".partition(".")

    grouped = []
    while len(whole) > 3:
        grouped.insert(0, whole[-3:])
        whole = whole[:-3]
    grouped.insert(0, whole)
    whole_formatted = ".".join(grouped)

    return f"{sign}{whole_formatted},{cents} €"


@register.filter
def get_range(value):
    """Return range(1, value + 1) for building quantity <select> options."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return []
    return range(1, max(value, 1) + 1)
