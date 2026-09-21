from django import template

register = template.Library()

@register.filter
def before_at(value):
    """RETURN ONLY THE LASTISSA AND REMVE THE DOMAIN OF @GMAIL.COM"""
    return value.split('@')[0]