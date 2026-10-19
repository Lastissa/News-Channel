"""Structured-data template helpers (see SERVICE_INTERNAL/schema.py).

    {% load seo_tags %}
    {% breadcrumb_schema "Home" home_url "About" %}

Emits a BreadcrumbList JSON-LD <script>. Pages own their own trail, so each
page decides its breadcrumb while the markup lives in one place.
"""
from django import template
from django.utils.safestring import mark_safe

from SERVICE_INTERNAL import schema

register = template.Library()


@register.simple_tag(takes_context=True)
def breadcrumb_schema(context, *items):
    """Build a BreadcrumbList from alternating name/url arguments.

        {% url 'home:home' as home_url %}
        {% url 'home:category' blog.category|slugify as category_url %}
        {% breadcrumb_schema "Home" home_url blog.get_category_display|title category_url blog.heading %}

    An odd number of arguments means the trailing one is the current page and
    gets no `item` url. Relative urls are made absolute against the canonical
    domain; a blank name is skipped.
    """
    args = list(items)
    if len(args) % 2:
        args.append("")

    pairs = []
    for name, url in zip(args[0::2], args[1::2]):
        name = (name or "").strip() if isinstance(name, str) else str(name or "").strip()
        if name:
            pairs.append((name, url))
    if not pairs:
        return ""

    node = schema.breadcrumb_list(pairs, context)
    return mark_safe(
        f'<script type="application/ld+json">{schema.dumps(node)}</script>'
    )
