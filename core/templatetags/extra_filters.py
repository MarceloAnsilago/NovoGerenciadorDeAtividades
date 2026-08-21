from django import template
register = template.Library()

WEEKDAYS_PT_BR = (
    "Segunda-feira",
    "Terca-feira",
    "Quarta-feira",
    "Quinta-feira",
    "Sexta-feira",
    "Sabado",
    "Domingo",
)

@register.filter
def get_item(d, key):
    try:
        return d.get(key)
    except Exception:
        return None


@register.filter
def date_with_weekday(value):
    if not value:
        return ""
    try:
        data_ref = value.date() if hasattr(value, "date") else value
        return f"{WEEKDAYS_PT_BR[data_ref.weekday()]}, {data_ref:%d/%m/%Y}"
    except Exception:
        return value
