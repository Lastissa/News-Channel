"""Template helpers for the home page (HOME/templates/HOME/home.html and its
story card partial). Pure string helpers, no database access.

    {% load home_extras %}
    {{ post.content|story_excerpt:24 }}     clean first paragraph, N words
    {{ post.content|read_minutes }}         "4 min read"
    {{ post.image_1|cdn_image:"w_900" }}    Cloudinary resize, other hosts untouched
"""
import re

from django import template

register = template.Library()

#   WRITER MARKUP (see DOCS/NEWS_CONTENT_CONVENTION.MD) THAT MUST NEVER LEAK
#   INTO A CARD EXCERPT: image directives, filel lines, headings, bullets, bold.
_DIRECTIVE = re.compile(r"^(imgl|imgr|imgc|filel)\s+", re.IGNORECASE)
_HEADING = re.compile(r"^#{1,6}\s*")
_BULLET = re.compile(r"^([*\-]|\d+[.)])\s+")
_URL = re.compile(r"https?://\S+")
_EMPHASIS = re.compile(r"(\*\*\*|\*\*|__|\*|_|~~|`)")
_TAGS = re.compile(r"<[^>]+>")


def _first_paragraph(text):
    """First line of real prose: skips blanks, directives and bare URLs."""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or _DIRECTIVE.match(line):
            continue
        line = _HEADING.sub("", line)
        line = _BULLET.sub("", line)
        line = _URL.sub("", line)
        line = _TAGS.sub("", line)
        line = _EMPHASIS.sub("", line)
        line = re.sub(r"\s+", " ", line).strip()
        if len(line.split()) >= 3:
            return line
    return ""


@register.filter
def story_excerpt(value, words=24):
    try:
        limit = max(1, int(words))
    except (TypeError, ValueError):
        limit = 24
    parts = _first_paragraph(value).split()
    if len(parts) <= limit:
        return " ".join(parts)
    return " ".join(parts[:limit]).rstrip(".,;:!?-") + "\u2026"


@register.filter
def read_minutes(value):
    """Reading time at 200 words a minute, never below 1."""
    count = len(re.findall(r"\b\S+\b", value or ""))
    return f"{max(1, round(count / 200))} min read"


@register.filter
def cdn_image(url, transform="w_900"):
    """Ask Cloudinary for a smaller, auto-format copy of an uploaded image.

    Only URLs that already live on res.cloudinary.com/.../image/upload/ are
    rewritten (that is every image uploaded through this site). A pasted
    external URL is returned exactly as it came in, so nothing breaks.
    """
    if not url:
        return ""
    marker = "/image/upload/"
    if "res.cloudinary.com" not in url or marker not in url:
        return url
    head, tail = url.split(marker, 1)
    #   ALREADY TRANSFORMED (starts with a param block like "w_300,c_fill/")
    if re.match(r"^[a-z]{1,3}_[^/]+/", tail) and not re.match(r"^v\d+/", tail):
        return url
    return f"{head}{marker}{transform},c_limit,q_auto,f_auto/{tail}"


@register.filter
def cdn_srcset(url, widths="640,1024,1600"):
    """srcset string for an uploaded image ("<url> 640w, <url> 1024w, ..."),
    or "" for any other host so the template can skip the attribute."""
    if not url or "res.cloudinary.com" not in url or "/image/upload/" not in url:
        return ""
    sizes = [w.strip() for w in str(widths).split(",") if w.strip().isdigit()]
    return ", ".join(f"{cdn_image(url, f'w_{w}')} {w}w" for w in sizes)


@register.filter
def short_ago(value):
    """"23 hours, 34 minutes" -> "23 hours ago". Keeps only the largest unit."""
    from django.utils.timesince import timesince

    if not value:
        return ""
    text = timesince(value).replace("\xa0", " ")
    return text.split(",")[0].strip() + " ago"
