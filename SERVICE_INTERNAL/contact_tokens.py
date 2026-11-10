"""Dynamic contact details for story content.

Writers can drop ``{{ support_email }}`` or ``{{ customer_support_mobile }}``
into a story. The stored text keeps the token, so the values are read from
PANEL (ADMIN.models.SiteSettings) every time the story is rendered. Changing
the support address or customer-care number therefore updates every published
story that used the token instead of leaving stale contact information in the
body.

The values are deliberately kept out of the story row; only the token is
stored. Both the public story parser and the editor preview use the helpers
here so the preview shows the same mailto/tel links the reader will get.
"""
from __future__ import annotations

import html
import re
from urllib.parse import quote

CONTACT_TOKEN_RE = re.compile(
    r"\{\{\s*(support_email|customer_support_mobile)\s*\}\}",
    re.IGNORECASE,
)


def contact_values():
    """Return the current (support email, customer-care number) pair.

    The same cache entry the site context processor uses is reused, so a
    story page does not add a settings query for every token. The SiteSettings
    save/delete signals invalidate that entry.
    """
    from ADMIN.models import SiteSettings
    from SERVICE_INTERNAL.abstract import cache_or_run

    row = cache_or_run("site_settings_socials", SiteSettings.get_solo, timeout=None)
    return (
        (row.support_email or "").strip() if row else "",
        (row.customer_support_mobile or "").strip() if row else "",
    )


def _contact_href(kind, value):
    if kind == "support_email":
        return "mailto:" + quote(value, safe="@._+-")
    return "tel:" + quote(value, safe="+")


def replace_contact_tokens(text, support_email="", customer_support_mobile="", link=False):
    """Replace contact tokens in ``text``.

    ``link`` is True for rendered story HTML: the token becomes a safe
    ``mailto:``/``tel:`` anchor. It is False for excerpts, ticker text and
    other plain-text surfaces, where only the current value belongs.
    """
    if not text:
        return text

    def _replace(match):
        kind = match.group(1).lower()
        value = support_email if kind == "support_email" else customer_support_mobile
        value = (value or "").strip()
        if not value:
            value = "customer care" if kind == "support_email" else "customer care number"
        label = html.escape(value)
        if not link:
            return label
        href = html.escape(_contact_href(kind, value), quote=True)
        return f'<a href="{href}" rel="noopener noreferrer">{label}</a>'

    return CONTACT_TOKEN_RE.sub(_replace, text)
