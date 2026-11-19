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
from django.urls import reverse
from django.views import View

from SERVICE_INTERNAL.abstract import error_logger
from SERVICE_INTERNAL.images import ImageUploadError, fetch_advert_landing_html

from .landing import (
    ROBOTS_DEFAULT,
    advert_landing_slug,
    render_advert_landing_document,
)
from .models import AdvertEvent, AdvertImage, AdvertLandingPage, AdvertPage, AdvertReference
from .plans import advert_allows, plan_allows
from .tracking import (
    append_utm_source,
    record_advert_click,
    record_advert_view,
    tracking_pixel_response,
)

logger = logging.getLogger(__name__)


def _landing_for_request(pk):
    """One fresh row per request. `select_related` keeps the author check from
    adding a second query, but the row itself is never cached between requests:
    unpublishing, deleting the author, or demoting the author takes effect on
    the very next hit."""
    return (
        AdvertLandingPage.objects.select_related(
            "advert",
            "advert__reference",
            "author",
        )
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
        reference = getattr(landing.advert, "reference", None)
        if reference and not reference.is_live:
            raise Http404("Advert landing page not found.")
        #   The plan decides, on every request, whether this page may show.
        if not advert_allows(landing.advert, "landing_page"):
            raise Http404("Advert landing page not found.")

        canonical_slug = advert_landing_slug(landing.advert)
        if slug != canonical_slug:
            return _redirect_to_canonical(landing, request)

        if reference:
            record_advert_view(reference, request)

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
        reference = getattr(landing.advert, "reference", None)
        if reference and not reference.is_live:
            raise Http404("Advert landing page not found.")
        if not advert_allows(landing.advert, "landing_page"):
            raise Http404("Advert landing page not found.")
        return _redirect_to_canonical(landing, request)


def serve_extra_page(request, advert, path):
    """Show one extra page (like /about/) of an advert, or raise 404.

    Used by the /ads/<name>-<id>/<path>/ route and by the advert subdomain,
    so both apply the same rules: the reference is live, the plan still
    includes extra pages, the page is published and its writer is still an
    admin.
    """
    reference = getattr(advert, "reference", None)
    if reference is None or not reference.is_live:
        raise Http404("Page not found.")
    if not plan_allows(reference.plan, "extra_pages"):
        raise Http404("Page not found.")

    page = AdvertPage.objects.select_related("author").filter(advert=advert, path=path).first()
    if page is None or not page.is_deliverable:
        raise Http404("Page not found.")

    record_advert_view(reference, request)
    try:
        html_text = fetch_advert_landing_html(page.html_public_id)
    except ImageUploadError as exc:
        error_logger(logger=logger, msg=f"ADVERT PAGE: fetch failed for advert {advert.pk} /{path}/: {exc}")
        return HttpResponse(
            "This page is temporarily unavailable.",
            status=502,
            content_type="text/plain; charset=utf-8",
        )

    landing = getattr(advert, "landing_page", None)
    robots = (landing.robots if landing else "") or ROBOTS_DEFAULT
    html_text = render_advert_landing_document(
        advert=advert,
        request=request,
        html_text=html_text,
        meta_title=landing.meta_title if landing else "",
        meta_description=landing.meta_description if landing else "",
        og_image=landing.og_image if landing else "",
        robots=robots,
        canonical_url=request.build_absolute_uri(request.path),
    )
    response = HttpResponse(html_text, content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["X-Robots-Tag"] = robots
    return response


class AdvertPageView(View):
    def get(self, request, slug, pk, path):
        advert = AdvertImage.objects.select_related("reference", "landing_page").filter(pk=pk).first()
        if advert is None:
            raise Http404("Page not found.")
        if slug != advert_landing_slug(advert):
            return redirect(f"{reverse('partner:advert_landing', kwargs={'slug': advert_landing_slug(advert), 'pk': pk})}{path}/", permanent=True)
        return serve_extra_page(request, advert, path)


def _reference_or_404(value):
    reference = (
        AdvertReference.objects.select_related("advert", "advert__landing_page")
        .filter(reference=(value or "").strip().upper())
        .first()
    )
    if reference is None:
        raise Http404("Advert reference not found.")
    return reference


class AdvertViewTrackView(View):
    """Tiny pixel written when an advert becomes the focused slide.

    The response is always the same transparent GIF, even when the event is
    ignored as a duplicate or a bot, so the browser has nothing to act on.
    """

    def get(self, request, reference):
        row = _reference_or_404(reference)
        if row.is_live:
            record_advert_view(row, request)
        return tracking_pixel_response()


class AdvertClickView(View):
    """Tracked outbound click for a referenced advert.

    The target comes from the reference row (staff-entered public URL, the
    advert's published landing page, or the advert's saved link). Abureport
    adds ``utm_source=abureport`` so the advertiser's own analytics can tell
    our traffic apart from every other source.
    """

    def get(self, request, reference):
        row = _reference_or_404(reference)
        if not row.is_live:
            #   A paused or expired campaign must stop sending readers to the
            #   advertiser, even if someone kept an old tracked link.
            return redirect(reverse("home:promote"))
        target = row.public_target or reverse("home:promote")
        target = append_utm_source(target, AdvertEvent.SOURCE_ABUREPORT)
        record_advert_click(row, request, target)
        return redirect(target)
