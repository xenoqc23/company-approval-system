from decimal import Decimal
from django import template
register = template.Library()

@register.filter
def amount(value):
    try:
        return f'{Decimal(value):,.2f}'.rstrip('0').rstrip('.')
    except (TypeError, ValueError):
        return value

@register.filter
def money(value):
    try:
        return f'{Decimal(value):,.2f}'.rstrip('0').rstrip('.')
    except (TypeError, ValueError):
        return value
