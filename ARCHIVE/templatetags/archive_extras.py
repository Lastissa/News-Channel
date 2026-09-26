"""`{{ some_cloudinary_url|cloudinary_proxy }}` -- rewrites a Cloudinary
secure_url so the browser fetches it from this project's own domain
instead of res.cloudinary.com (see ARCHIVE.views.CloudinaryProxyView,
which does the real fetch behind the scenes). Used everywhere an <img>,
download link, or og:image in the project points at a picture this
project uploaded to Cloudinary (archive pictures, story hero images,
inline imgl/imgr/imgc pictures, avatars, ...).
"""

import re

from django import template
from django.conf import settings
from django.urls import reverse

register = template.Library()

#   Matches "https://res.cloudinary.com/<cloud_name>/<everything else>".
#   <everything else> (the resource type, delivery type, version and
#   public id, e.g. "image/upload/v123/abureport/archive/x.jpg") is exactly
#   what ARCHIVE.views.CloudinaryProxyView expects as `cloud_path`.
_CLOUDINARY_URL_RE = re.compile(r"^https?://res\.cloudinary\.com/([^/]+)/(.+)$")


@register.filter(name="cloudinary_proxy")
def cloudinary_proxy(url):
    """Returns a same-origin URL that serves the exact same picture, for
    any URL that is actually one of our own Cloudinary assets. Anything
    else (empty value, a placeholder image, an external URL a visitor
    pasted somewhere) is returned unchanged -- this filter only ever
    rewrites the domain, it never invents a picture that isn't there."""
    if not url:
        return url

    match = _CLOUDINARY_URL_RE.match(str(url))
    if not match:
        return url

    cloud_name, cloud_path = match.groups()
    if cloud_name != settings.CLOUDINARY_CLOUD_NAME:
        return url

    return reverse("archive:cdn_proxy", kwargs={"cloud_path": cloud_path})
