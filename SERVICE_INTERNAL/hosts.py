"""Host helpers for the public site, the ads site and per-advert subdomains.

The ads page lives on its own host (for example ``ads.abureport.com.ng``)
instead of a path on the news domain. Both hosts are served by the same Django
project, so this module is the single place that answers four questions:

* which host is the canonical news site;
* which host is the shared ads site;
* which base host a manager should append ``newads.`` to;
* which path the public ads page should use on the host serving the request.

Nothing here calls the ORM. The values come from settings (``ADS_HOST`` plus
the first usable ``ALLOWED_HOSTS`` entry), which keeps the host logic testable
without a database.
"""
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.urls import reverse

_ADVERT_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")

#   Subdomain labels the site keeps for itself. Every OTHER label under the
#   base host is an advert host (new.localhost, newads.example.com, ...).
#   "ads" is the promote-your-bussiness page. To fix another dedicated host
#   later, add its label here: the admin form, the host helpers and the
#   middleware all read this one set.
RESERVED_SUBDOMAINS = frozenset({"ads", "www"})


def clean_host(value):
    """Return a bare lowercase hostname, or "" for something unusable.

    Values may arrive from an environment variable with a scheme, a path or a
    port attached. Only the hostname is kept; an invalid value is dropped
    rather than allowed to leak into ``ALLOWED_HOSTS`` or a redirect.
    """
    value = (value or "").strip()
    if not value:
        return ""
    if "://" in value:
        value = urlsplit(value).hostname or ""
    else:
        value = value.split("/", 1)[0]
        #   Bracketed IPv6 addresses are not used for the ads host.
        if value.startswith("["):
            return ""
        value = value.split(":", 1)[0]
    value = value.strip().lower().rstrip(".").lstrip(".")
    if not value or any(char.isspace() for char in value):
        return ""
    if any(char not in "abcdefghijklmnopqrstuvwxyz0123456789.-*" for char in value):
        return ""
    return value


def can_derive_ads_host(value):
    """True when a host can be prefixed with ``ads.``.

    Localhost is deliberately allowed: development uses ``ads.localhost`` just
    like production uses ``ads.<domain>``.
    """
    value = clean_host(value)
    return bool(value and "*" not in value)


def canonical_host():
    """The main news host: the first usable ``ALLOWED_HOSTS`` entry."""
    for value in getattr(settings, "ALLOWED_HOSTS", []) or []:
        host = clean_host(value)
        if host and "*" not in host:
            return host
    return ""


def ads_host():
    """The configured shared ads host (``ads.<base>``), or "" when unset."""
    host = clean_host(getattr(settings, "ADS_HOST", ""))
    return "" if host == "*" else host


def ads_base_host():
    """The base a per-advert subdomain is attached to.

    ``www.abureport.com.ng`` becomes ``abureport.com.ng`` so a manager enters
    ``newads`` and gets ``newads.abureport.com.ng``. On localhost the base is
    ``localhost``, which makes the development host ``newads.localhost``.
    """
    host = canonical_host()
    if not host:
        return ""
    return host[4:] if host.startswith("www.") else host


def advert_host(subdomain):
    """Full host for one advert's chosen subdomain, or "" when unusable."""
    label = clean_host(subdomain)
    base = ads_base_host()
    if not label or not base or not _ADVERT_LABEL_RE.fullmatch(label):
        return ""
    #   These are infrastructure hosts, not customer advert hosts.
    if label in RESERVED_SUBDOMAINS:
        return ""
    return f"{label}.{base}"


def advert_subdomain_from_host(value):
    """Extract a manager-assigned label from a request host.

    Returns "" for the canonical news host, the shared ads host, any
    infrastructure label (www/ads), and hosts that are not below the ads base.
    """
    host = clean_host(value)
    base = ads_base_host()
    if not host or not base or host in {canonical_host(), ads_host()}:
        return ""
    suffix = f".{base}"
    if not host.endswith(suffix):
        return ""
    label = host[: -len(suffix)]
    if not label or not _ADVERT_LABEL_RE.fullmatch(label):
        return ""
    if label in RESERVED_SUBDOMAINS:
        return ""
    return label


def request_host(request):
    if request is None:
        return ""
    return clean_host(request.get_host())


def is_ads_subdomain(request):
    host = ads_host()
    return bool(host and request is not None and request_host(request) == host)


def _origin(host, request=None):
    if not host:
        return ""
    #   In DEBUG the local server is plain HTTP and may sit on port 8000.
    #   Production is always HTTPS behind the proxy, where request.get_port()
    #   can still report the proxy's internal port; never leak that into a
    #   canonical URL or redirect.
    debug = getattr(settings, "DEBUG", False)
    scheme = "http" if debug else "https"
    if debug and request is not None:
        port = request.get_port()
        if port and port not in {"80", "443"}:
            host = f"{host}:{port}"
    return f"{scheme}://{host}"


def canonical_origin(request=None):
    return _origin(canonical_host(), request)


def ads_origin(request=None):
    return _origin(ads_host(), request)


def advert_origin(subdomain, request=None):
    return _origin(advert_host(subdomain), request)


def promote_path(request=None):
    """The public ads page path on the host currently serving the request."""
    return "/" if is_ads_subdomain(request) else reverse("home:promote")


def promote_lead_path(request=None):
    """The enquiry endpoint path on the host currently serving the request."""
    return "/enquiry/" if is_ads_subdomain(request) else reverse("home:promote_lead")


def promote_public_url():
    """Absolute canonical URL for the ads page, for sitemaps and llms.txt."""
    if ads_host():
        return f"{ads_origin()}/"
    origin = canonical_origin()
    return f"{origin}{reverse('home:promote')}" if origin else reverse("home:promote")
