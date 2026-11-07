"""`{{ some_cloudinary_url|cloudinary_proxy }}` -- rewrites a Cloudinary
secure_url so the browser fetches it from this project's own domain
instead of res.cloudinary.com (see ARCHIVE.views.CloudinaryProxyView,
which does the real fetch behind the scenes). Used everywhere an <img>,
download link, or og:image in the project points at a picture this
project uploaded to Cloudinary (archive pictures, story hero images,
inline imgl/imgr/imgc pictures, avatars, ...).
"""

import re
from urllib.parse import quote, urlparse

from django import template
from django.conf import settings
from django.urls import reverse

register = template.Library()

#   Matches "https://res.cloudinary.com/<cloud_name>/<everything else>".
#   <everything else> (the resource type, delivery type, version and
#   public id, e.g. "image/upload/v123/abureport/archive/x.jpg") is exactly
#   what ARCHIVE.views.CloudinaryProxyView expects as `cloud_path`.
_CLOUDINARY_URL_RE = re.compile(r"^https?://res\.cloudinary\.com/([^/]+)/(.+)$")
#   Cloudinary transformation specs are intentionally narrow here: letters,
#   digits, underscores, colons, dots, commas, slashes and hyphens. The slash
#   form ("f_auto/q_auto/w_640") is preferred because a comma inside a URL is
#   ambiguous in a srcset candidate list.
_TRANSFORM_SPEC_RE = re.compile(r"^[A-Za-z0-9_:.,/-]+$")


def _cloudinary_path(url):
    """Return the Cloudinary path for one of our own assets, else None."""
    if not url:
        return None

    #   Keep the query string out of cloud_path: reverse() would escape its
    #   "?" to "%3F", and _proxied_url already re-attaches the original query.
    parsed = urlparse(str(url))
    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    match = _CLOUDINARY_URL_RE.match(clean_url)
    if not match:
        return None

    cloud_name, cloud_path = match.groups()
    if cloud_name != settings.CLOUDINARY_CLOUD_NAME:
        return None
    return cloud_path


def _insert_transform(cloud_path, transform):
    """Insert a Cloudinary transformation segment after ``.../upload/``.

    Existing transformation segments are left in place and the new one is
    chained in front, which Cloudinary accepts. A path without an upload
    segment is returned unchanged.
    """
    parts = cloud_path.split("/")
    try:
        upload_at = parts.index("upload")
    except ValueError:
        return cloud_path
    parts.insert(upload_at + 1, transform)
    return "/".join(parts)


def _proxied_url(url, cloud_path):
    """Same-origin proxy URL, preserving any query string on the original."""
    proxied = reverse("archive:cdn_proxy", kwargs={"cloud_path": cloud_path})
    query = urlparse(str(url)).query
    return f"{proxied}?{query}" if query else proxied


@register.filter(name="cloudinary_proxy")
def cloudinary_proxy(url):
    """Returns a same-origin URL that serves the exact same picture, for
    any URL that is actually one of our own Cloudinary assets. Anything
    else (empty value, a placeholder image, an external URL a visitor
    pasted somewhere) is returned unchanged -- this filter only ever
    rewrites the domain, it never invents a picture that isn't there."""
    cloud_path = _cloudinary_path(url)
    if cloud_path is None:
        return url
    return _proxied_url(url, cloud_path)


@register.filter(name="cloudinary_image")
def cloudinary_image(url, transform="f_auto/q_auto"):
    """Same-origin Cloudinary URL with a transformation applied.

    ``{{ post.image_1|cloudinary_image:"f_auto/q_auto/w_1280" }}`` asks
    Cloudinary for an auto-format, auto-quality 1280px-wide version. A
    non-Cloudinary or empty value is returned unchanged, so templates can
    still fall back to a local placeholder.
    """
    if not url:
        return url
    cloud_path = _cloudinary_path(url)
    if cloud_path is None:
        return url
    transform = str(transform or "")
    if not transform or not _TRANSFORM_SPEC_RE.match(transform):
        return _proxied_url(url, cloud_path)
    return _proxied_url(url, _insert_transform(cloud_path, transform))


@register.filter(name="cloudinary_srcset")
def cloudinary_srcset(url, widths="320,480,640,960,1280"):
    """Build a responsive srcset for one of our Cloudinary images.

    The comma-separated ``widths`` argument is turned into one candidate per
    width using chained transformations (no commas inside the URL, so the
    srcset parser stays happy). Non-Cloudinary values return an empty string,
    which lets a template omit the attribute entirely.
    """
    cloud_path = _cloudinary_path(url)
    if cloud_path is None:
        return ""

    candidates = []
    for token in str(widths or "").split(","):
        token = token.strip()
        if not token.isdigit() or int(token) <= 0:
            continue
        width = int(token)
        transformed = _insert_transform(cloud_path, f"f_auto/q_auto/w_{width}")
        candidates.append(f"{_proxied_url(url, transformed)} {width}w")
    return ", ".join(candidates)


@register.filter(name="archive_absolute_url")
def archive_absolute_url(url, request):
    """Make relative proxy URLs copyable outside this page while leaving
    already-absolute, persisted URLs intact."""
    if not url or not request:
        return url
    if urlparse(str(url)).scheme:
        return url
    return request.build_absolute_uri(str(url))


@register.filter(name="archive_download_url")
def archive_download_url(url, filename):
    """Adds `?filename=` (or `&filename=` when the url already carries a
    query) so ARCHIVE.views.CloudinaryProxyView serves the item as a
    download under its original name. A blank filename (every picture)
    leaves the url untouched."""
    if not url or not filename:
        return url
    separator = "&" if "?" in str(url) else "?"
    return f"{url}{separator}filename={quote(str(filename))}"
