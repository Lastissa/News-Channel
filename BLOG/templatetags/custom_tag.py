from django import template

register = template.Library()

@register.filter
def before_at(value):
    """RETURN ONLY THE LASTISSA AND REMVE THE DOMAIN OF @GMAIL.COM"""
    return value.split('@')[0]


@register.filter
def in_list(value, collection):
    """`{{ comment.id|in_list:liked_comment_ids }}` -> True when the id is in the list."""
    return value in (collection or [])
