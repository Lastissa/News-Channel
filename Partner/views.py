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
from types import SimpleNamespace

from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views import View

from SERVICE_INTERNAL.abstract import error_logger
from SERVICE_INTERNAL.images import ImageUploadError, fetch_advert_landing_html

from .landing import (
    DEFAULT_ADVERT_BUILDING_TEMPLATE,
    DEFAULT_ADVERT_LANDING_TEMPLATE,
    ROBOTS_DEFAULT,
    advert_landing_slug,
    render_advert_landing_document,
)
from .models import AdvertEvent, AdvertImage, AdvertLandingPage, AdvertPage, AdvertReference
from .plans import advert_allows, advert_subdomain_url, plan_allows
from .tracking import (
    append_utm_source,
    record_advert_click,
    record_advert_view,
    tracking_pixel_response,
)

logger = logging.getLogger(__name__)


def _redirect_to_canonical(landing, request):
    target = landing.get_absolute_url()
    query = request.META.get("QUERY_STRING", "")
    if query:
        target = f"{target}?{query}"
    return redirect(target, permanent=True)


def serve_landing(request, landing, canonical_url=""):
    """Show an advert's landing page. Used by the /ads/ path route and by the
    advert's own subdomain root."""
    reference = getattr(landing.advert, "reference", None)
    pk = landing.advert_id
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
        canonical_url=canonical_url,
    )

    response = HttpResponse(html_text, content_type="text/html; charset=utf-8")
    #   The page is code the admin controls, so it must never be reused
    #   from a browser/CDN cache after the landing row is unpublished,
    #   deleted, or its author is deactivated.
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["X-Robots-Tag"] = landing.robots or ROBOTS_DEFAULT
    return response


def render_default_landing(request, advert=None, reference=None, canonical_url="", building=False):
    """Serve the built-in responsive advert page when no custom HTML exists.

    Regular adverts get the original "Learn more" page. Paid adverts on their
    own subdomain get the same page with an honest "being built" line while the
    custom landing file is prepared. Both are real 200 pages: no 404, and no
    redirect away from the branded address. The destination on "Learn more"
    comes from the reference's Public page URL, falling back to the advert link.
    """
    if reference is not None and reference.is_live:
        record_advert_view(reference, request)

    html_text = DEFAULT_ADVERT_BUILDING_TEMPLATE if building else DEFAULT_ADVERT_LANDING_TEMPLATE
    fallback = SimpleNamespace(
        pk="",
        heading="Advert",
        body="",
        image_url="",
        url="",
        reference=reference,
    )
    html_text = render_advert_landing_document(
        advert=advert if advert is not None else fallback,
        request=request,
        html_text=html_text,
        canonical_url=canonical_url or request.build_absolute_uri(request.path),
    )
    response = HttpResponse(html_text, content_type="text/html; charset=utf-8")
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    response["X-Robots-Tag"] = ROBOTS_DEFAULT
    return response


class AdvertLandingView(View):
    def get(self, request, slug, pk):
        advert = (
            AdvertImage.objects.select_related(
                "reference", "landing_page", "landing_page__author"
            )
            .filter(pk=pk)
            .first()
        )
        if advert is None:
            raise Http404("Advert landing page not found.")
        reference = getattr(advert, "reference", None)
        if reference and not reference.is_live:
            raise Http404("Advert landing page not found.")

        #   A paid advert with a subdomain always opens there, custom HTML or
        #   not. The subdomain renders the built-in page while HTML is prepared.
        subdomain_url = advert_subdomain_url(advert)
        if subdomain_url:
            return redirect(subdomain_url)

        landing = getattr(advert, "landing_page", None)
        has_custom = bool(
            landing and landing.is_deliverable and advert_allows(advert, "landing_page")
        )
        canonical_slug = advert_landing_slug(advert)
        if slug != canonical_slug:
            if has_custom:
                return _redirect_to_canonical(landing, request)
            return redirect(
                reverse("partner:advert_landing", kwargs={"slug": canonical_slug, "pk": pk}),
                permanent=True,
            )
        if has_custom:
            return serve_landing(request, landing)

        #   Every linked advert still has a page. Regular gets the original
        #   layout; a paid advert that leaked through without a subdomain gets
        #   the same "being built" page rather than a 404.
        return render_default_landing(
            request,
            advert,
            reference,
            building=bool(reference and plan_allows(reference.plan, "subdomain")),
        )


class AdvertLandingIdRedirectView(View):
    def get(self, request, pk):
        advert = (
            AdvertImage.objects.select_related("reference", "landing_page")
            .filter(pk=pk)
            .first()
        )
        if advert is None:
            raise Http404("Advert landing page not found.")
        reference = getattr(advert, "reference", None)
        if reference and not reference.is_live:
            raise Http404("Advert landing page not found.")
        subdomain_url = advert_subdomain_url(advert)
        if subdomain_url:
            return redirect(subdomain_url)
        landing = getattr(advert, "landing_page", None)
        if landing and landing.is_deliverable and advert_allows(advert, "landing_page"):
            return _redirect_to_canonical(landing, request)
        return redirect(
            reverse("partner:advert_landing", kwargs={"slug": advert_landing_slug(advert), "pk": pk}),
            permanent=True,
        )


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
        subdomain_url = advert_subdomain_url(advert)
        if subdomain_url:
            return redirect(f"{subdomain_url}{path}/")
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

    Paid references open on their subdomain (or the external link when one was
    set instead); Regular references open their own /ads/ page. The "Learn more"
    on those pages carries the destination: the ads desk Public page URL, else
    the advert's saved link. Abureport adds ``utm_source=abureport`` so the
    advertiser's own analytics can tell our traffic apart from every source.
    A paid reference with neither subdomain nor destination is a setup error and
    is reported as JSON for the on-site toast.
    """

    def get(self, request, reference):
        row = _reference_or_404(reference)
        if not row.is_live:
            #   A paused or expired campaign must stop sending readers to the
            #   advertiser, even if someone kept an old tracked link.
            return redirect(reverse("home:promote"))
        #   The rail calls this first with ?check=1 so it can read the setup
        #   error as JSON and show a bottom toast instead of a raw JSON page.
        #   Direct opens of /ads/ or the subdomain never return JSON.
        check = (request.GET.get("check") or "").lower() in {"1", "true", "json"}
        target = (row.public_target or "").strip()
        if not target:
            return JsonResponse({"detail": "this ads was not set properly"}, status=400)
        target = append_utm_source(target, AdvertEvent.SOURCE_ABUREPORT)
        record_advert_click(row, request, target)
        if check:
            return JsonResponse({"ok": True, "target": target})
        return redirect(target)
