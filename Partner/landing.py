"""Advert landing-page rendering and the code-editor contract.

The HTML is stored in Cloudinary exactly as the admin wrote it, with simple
``{{token}}`` placeholders for the values that come from the advert/landing
row. This module is the one place that knows those token names, the default
template shown on an advert with no page yet, and the small author header that
makes the stored file traceable back to the account that wrote it.

The public view checks the landing row (and its author) before calling this
module, so rendering here is deliberately just token substitution -- no
Django template compilation, no request context, no site chrome.
"""

import re

from django.utils import timezone
from django.utils.html import escape
from django.utils.text import slugify


ROBOTS_DEFAULT = "noindex, nofollow"

#   Shown in the panel's "Available tokens" help and used by the default
#   template. Keep the descriptions short; the panel renders these as a list.
ADVERT_LANDING_TOKENS = (
    ("page_title", "The advert heading, without any metadata override."),
    ("meta_title", "The metadata title, for the document <title> (falls back to the advert heading)."),
    ("meta_description", "The metadata description (falls back to the advert text)."),
    ("og_title", "Open Graph title (same fallback as the metadata title)."),
    ("og_description", "Open Graph description (same fallback as the metadata description)."),
    ("og_image", "The OG image URL (falls back to the advert picture)."),
    ("canonical_url", "This landing page's own absolute URL."),
    ("landing_url", "Alias of canonical_url."),
    ("robots", "The selected robots value, e.g. noindex, nofollow."),
    ("ad_heading", "The advert heading."),
    ("ad_body", "The advert text."),
    ("ad_url", "The advertiser link saved on the advert."),
    ("ad_image", "The advert picture URL."),
    ("ad_id", "The numeric advert id."),
    ("year", "The current four-digit year."),
)


DEFAULT_ADVERT_LANDING_TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{{meta_title}}</title>
  <meta name="description" content="{{meta_description}}">
  <meta name="robots" content="{{robots}}">
  <link rel="canonical" href="{{canonical_url}}">
  <meta property="og:type" content="website">
  <meta property="og:title" content="{{og_title}}">
  <meta property="og:description" content="{{og_description}}">
  <meta property="og:image" content="{{og_image}}">
  <meta property="og:url" content="{{canonical_url}}">
  <meta name="twitter:card" content="summary_large_image">
  <style>
    :root { color-scheme: light; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px;
      background: #f6f2e9;
      color: #172033;
      font-family: system-ui, -apple-system, Segoe UI, sans-serif;
    }
    main {
      width: min(720px, 100%);
      overflow: hidden;
      background: #fff;
      border: 1px solid #e4dccd;
      border-radius: 22px;
      box-shadow: 0 24px 70px rgba(23, 32, 51, .12);
    }
    img { display: block; width: 100%; aspect-ratio: 16 / 9; object-fit: cover; background: #eee7da; }
    .copy { padding: clamp(22px, 5vw, 42px); }
    h1 { margin: 0 0 14px; font-size: clamp(1.6rem, 4vw, 2.6rem); line-height: 1.1; }
    p { margin: 0 0 22px; color: #526078; line-height: 1.65; }
    a.cta {
      display: inline-block;
      padding: 12px 20px;
      background: #172033;
      color: #fff;
      border-radius: 999px;
      font-weight: 700;
      text-decoration: none;
    }
  </style>
</head>
<body>
  <main>
    <img src="{{ad_image}}" alt="{{ad_heading}}">
    <div class="copy">
      <h1>{{ad_heading}}</h1>
      <p>{{ad_body}}</p>
      <a class="cta" href="{{ad_url}}">Learn more</a>
    </div>
  </main>
</body>
</html>
"""


_TOKEN_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")
_AUTHOR_HEADER_RE = re.compile(
    r"\A<!--\s*ABUREPORT-AD-LANDING\b.*?-->\s*",
    re.DOTALL | re.IGNORECASE,
)


def advert_landing_slug(advert) -> str:
    return slugify(getattr(advert, "heading", "") or "") or "advert"


def advert_landing_url(advert) -> str:
    from django.urls import reverse

    return reverse(
        "partner:advert_landing",
        kwargs={"slug": advert_landing_slug(advert), "pk": advert.pk},
    )


def _comment_safe(value) -> str:
    return str(value or "").replace("--", "- -").replace(">", "").replace("\n", " ").strip()


def add_advert_landing_author_header(html_text: str, advert, author) -> str:
    """Attach the editor identity to the stored file itself.

    This is deliberately a comment, not visible page content. The panel strips
    it again before showing the file in the editor, then a save writes a fresh
    one, so the Cloudinary object always names the account that last touched
    it even if the database row is later changed or removed.
    """
    from STAFF.models import StaffProfile

    profile = StaffProfile.objects.filter(auth=author).only("full_name").first()
    #   The header is stored in the public document, so it names the account by
    #   id and public staff name -- never the admin's email address.
    label = (profile.full_name if profile else "") or f"account {getattr(author, 'pk', '')}"
    header = (
        "<!-- ABUREPORT-AD-LANDING "
        f"author_id={getattr(author, 'pk', '')} "
        f"author={_comment_safe(label)} "
        f"advert_id={getattr(advert, 'pk', '')} "
        f"updated={_comment_safe(timezone.now().isoformat())} -->\n"
    )
    return header + strip_advert_landing_author_header(html_text)


def strip_advert_landing_author_header(html_text: str) -> str:
    return _AUTHOR_HEADER_RE.sub("", html_text or "", count=1)


def render_advert_landing_document(
    *,
    advert,
    request,
    html_text: str,
    meta_title: str = "",
    meta_description: str = "",
    og_image: str = "",
    robots: str = ROBOTS_DEFAULT,
) -> str:
    """Substitute every known token and return the complete HTML document.

    Values are escaped for HTML text/attribute contexts. Unknown tokens are
    left untouched so a typo is visible in the page source instead of silently
    disappearing.
    """
    heading = (getattr(advert, "heading", "") or "Advert").strip()
    body = (getattr(advert, "body", "") or "").strip()
    ad_image = (getattr(advert, "image_url", "") or "").strip()
    ad_url = (getattr(advert, "url", "") or "").strip()

    title = (meta_title or heading).strip()
    description = (meta_description or body).strip()
    share_image = (og_image or ad_image).strip()
    canonical = request.build_absolute_uri(advert_landing_url(advert))

    values = {
        "page_title": escape(heading),
        "meta_title": escape(title),
        "meta_description": escape(description),
        "og_title": escape(title),
        "og_description": escape(description),
        "og_image": escape(share_image),
        "canonical_url": escape(canonical),
        "landing_url": escape(canonical),
        "robots": escape(robots or ROBOTS_DEFAULT),
        "ad_heading": escape(heading),
        "ad_body": escape(body),
        "ad_url": escape(ad_url),
        "ad_image": escape(ad_image),
        "ad_id": str(getattr(advert, "pk", "")),
        "year": str(timezone.localdate().year),
    }

    def replace(match):
        return values.get(match.group(1), match.group(0))

    return _TOKEN_RE.sub(replace, html_text or "")
