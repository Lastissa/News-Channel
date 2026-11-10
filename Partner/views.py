"""Public advert landing pages.

These views are intentionally outside every site template: the response is the
stored HTML document itself, with no header, footer, nav, or global CSS. The
only Django-side input is a fresh database read (for the advert heading,
metadata, Cloudinary id, and the current author's account state), token
substitution, and the safety headers.

The Cloudinary file is authenticated raw storage. Nothing here redirects a
reader to Cloudinary: every request fetches the HTML server-side so the author
check cannot be bypassed by guessing a CDN URL.
"""

import logging

from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.views import View

from SERVICE_INTERNAL.abstract import error_logger
from SERVICE_INTERNAL.images import ImageUploadError, fetch_advert_landing_html

from .landing import (
    ROBOTS_DEFAULT,
    advert_landing_slug,
    render_advert_landing_document,
)
from .models import AdvertLandingPage

logger = logging.getLogger(__name__)


def _landing_for_request(pk):
    """One fresh row per request. `select_related` keeps the author check from
    adding a second query, but the row itself is never cached between requests:
    unpublishing, deleting the author, or demoting the author takes effect on
    the very next hit."""
    return (
        AdvertLandingPage.objects.select_related("advert", "author")
        .filter(advert_id=pk)
        .first()
    )


def _redirect_to_canonical(landing, request):
    target = landing.get_absolute_url()
    query = request.META.get("QUERY_STRING", "")
    if query:
        target = f"{target}?{query}"
    return redirect(target, permanent=True)


class AdvertLandingView(View):
    def get(self, request, slug, pk):
        landing = _landing_for_request(pk)
        if not landing or not landing.is_deliverable:
            raise Http404("Advert landing page not found.")

        canonical_slug = advert_landing_slug(landing.advert)
        if slug != canonical_slug:
            return _redirect_to_canonical(landing, request)

        try:
            html_text = fetch_advert_landing_html(landing.html_public_id)
        except ImageUploadError as exc:
            error_logger(
                logger=logger,
                msg=f"ADVERT LANDING: fetch failed for advert {pk}: {exc}",
            )
            return HttpResponse(
                "This landing page is temporarily unavailable.",
                status=502,
                content_type="text/plain; charset=utf-8",
            )

        html_text = render_advert_landing_document(
            advert=landing.advert,
            request=request,
            html_text=html_text,
            meta_title=landing.meta_title,
            meta_description=landing.meta_description,
            og_image=landing.og_image,
            robots=landing.robots or ROBOTS_DEFAULT,
        )

        response = HttpResponse(html_text, content_type="text/html; charset=utf-8")
        #   The page is code the admin controls, so it must never be reused
        #   from a browser/CDN cache after the landing row is unpublished,
        #   deleted, or its author is deactivated.
        response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response["Pragma"] = "no-cache"
        response["X-Robots-Tag"] = landing.robots or ROBOTS_DEFAULT
        return response


class AdvertLandingIdRedirectView(View):
    def get(self, request, pk):
        landing = _landing_for_request(pk)
        if not landing or not landing.is_deliverable:
            raise Http404("Advert landing page not found.")
        return _redirect_to_canonical(landing, request)
