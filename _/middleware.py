
from django.conf import settings
from django.http import (
    Http404,
    HttpResponse,
    HttpResponsePermanentRedirect,
    HttpResponseRedirect,
)
from django.urls import reverse
from SERVICE_INTERNAL.config import About
from SERVICE_INTERNAL.hosts import (
    ads_host,
    ads_origin,
    advert_subdomain_from_host,
    canonical_origin,
    request_host,
)


class SecurityHeadersMiddleware:
    """Adds a report-only Content-Security-Policy.

    Report-only is deliberate: the AdSense tag, the inline theme boot script
    and the inline splash script all need to keep running while the site is
    under review. Once the reports are clean, the same policy can be promoted
    to ``Content-Security-Policy`` (or the inline scripts can be nonce'd).
    HSTS itself is handled by Django's SecurityMiddleware from settings.
    """

    CSP_REPORT_ONLY = (
        "default-src 'self'; "
        "base-uri 'self'; "
        "object-src 'none'; "
        "frame-ancestors 'self'; "
        "form-action 'self'; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' "
        "https://pagead2.googlesyndication.com https://*.googlesyndication.com "
        "https://*.google.com https://*.gstatic.com https://*.googleusercontent.com "
        "https://*.doubleclick.net https://*.adtrafficquality.google; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://*.gstatic.com; "
        "img-src 'self' data: blob: https:; "
        "font-src 'self' data: https://fonts.gstatic.com https://*.gstatic.com; "
        "connect-src 'self' https://*.google-analytics.com "
        "https://*.googlesyndication.com https://*.doubleclick.net "
        "https://*.google.com https://*.adtrafficquality.google; "
        "frame-src 'self' https://abureport.com.ng https://www.abureport.com.ng "
        "https://*.doubleclick.net "
        "https://*.google.com https://*.adtrafficquality.google "
        "https://fundingchoicesmessages.google.com "
        "https://www.youtube.com https://youtube.com https://www.youtube-nocookie.com "
        "https://player.vimeo.com; "
        "media-src 'self' blob: https:; "
        "worker-src 'self' blob:; "
        "manifest-src 'self'"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        #   Advert landing pages are staff-authored and run off the normal
        #   template, so their third-party assets would only create report
        #   noise. Keep the policy itself, but do not attach the report
        #   endpoint for /ads/ responses.
        report_url = ""
        if getattr(settings, "CSP_REPORT_ENABLED", True) and not request.path.startswith("/ads/"):
            try:
                report_url = request.build_absolute_uri(reverse("csp_report"))
            except Exception:
                report_url = ""

        policy = self.CSP_REPORT_ONLY
        if report_url:
            policy = f"{policy}; report-uri {report_url}; report-to csp-endpoint"
            response["Reporting-Endpoints"] = f'csp-endpoint="{report_url}"'

        if not response.has_header("Content-Security-Policy-Report-Only"):
            response["Content-Security-Policy-Report-Only"] = policy
        return response


class AdsSubdomainMiddleware:
    """Serve the ads page at ``ads.<domain>/`` and route per-advert hosts.

    The ads host is a real host, not a cosmetic redirect: the root of the ads
    host resolves the existing promote view, ``/enquiry/`` posts to its lead
    endpoint, and the old main-domain promote URL permanently redirects here.
    Navigation on the ads host (about, categories, stories, the account
    dashboard) belongs on the news host, so those paths bounce back to the
    canonical domain instead of turning the ads host into a second copy of the
    site.

    A manager can also give one advert a subdomain such as
    ``newads.<base>``. That host is the advert's own entry point: its root
    serves the custom landing page when one is published, otherwise a built-in
    responsive "being built" page (still a 200). Unknown or non-advert labels
    never resolve. Because ``ADS_HOST`` is also derived on localhost,
    development uses ``ads.localhost`` and ``newads.localhost`` exactly the way
    production uses the real hosts.
    """

    _PROMOTE_PATHS = {
        "/promote-your-bussiness/",
        "/promote-your-bussiness/enquiry/",
    }
    _ADS_PREFIXES = (
        "/static/",
        "/media/",
        "/auth/",
        "/promote-ads/",
        "/ads/view/",
        "/ads/click/",
        "/csp-report/",
    )
    _ADS_PATHS = {
        "/promote-your-bussiness/",
        "/promote-your-bussiness/enquiry/",
        "/enquiry/",
        "/favicon.ico",
        "/favicon.svg",
        "/apple-touch-icon.png",
        "/site.webmanifest",
        "/robots.txt",
        "/ads.txt",
        "/health",
        "/health/",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def _ads_path_allowed(self, path):
        return path in self._ADS_PATHS or path.startswith(self._ADS_PREFIXES)

    def _serve_advert_host(self, request, label):
        """Resolve one manager-assigned advert subdomain as a tracked link.

        The custom host is a branded entry point, not a second copy of the
        site. Its root serves the advert's landing page -- custom HTML when
        available, the built-in page while it is still being built.
        """
        from Partner.models import AdvertReference

        from Partner.plans import plan_allows
        from Partner.views import render_default_landing, serve_extra_page, serve_landing

        row = (
            AdvertReference.objects.select_related(
                "advert", "advert__landing_page", "advert__landing_page__author"
            )
            .filter(subdomain__iexact=label)
            .first()
        )
        if row is None:
            raise Http404("No advert uses this subdomain.")
        #   A plan without subdomains (Regular) never answers on one.
        if not plan_allows(row.plan, "subdomain"):
            raise Http404("No advert uses this subdomain.")

        request.advert_subdomain = label
        path = request.path_info
        if path != "/":
            #   A valid advert host still needs its own assets and icons. Every
            #   other path is not part of this one-advert site.
            if path.startswith(("/static/", "/media/")) or path in {
                "/favicon.ico",
                "/favicon.svg",
                "/apple-touch-icon.png",
                "/site.webmanifest",
            }:
                return self.get_response(request)
            #   Any other path is one of the advert's extra pages, if it has one.
            if row.advert_id:
                return serve_extra_page(request, row.advert, path.strip("/"))
            raise Http404("Not found on this advert host.")

        if not row.is_live:
            origin = ads_origin(request)
            return HttpResponseRedirect(
                f"{origin}/" if origin else reverse("home:promote")
            )

        #   The custom landing page wins when it is published and deliverable.
        landing = getattr(row.advert, "landing_page", None) if row.advert_id else None
        if landing and landing.is_deliverable and plan_allows(row.plan, "landing_page"):
            return serve_landing(request, landing, canonical_url=request.build_absolute_uri("/"))

        #   No custom HTML yet: answer here with the built-in responsive page
        #   and a "being built" note. It stays on the branded host with a 200
        #   instead of a 404 or a redirect away from the subdomain.
        return render_default_landing(
            request,
            row.advert,
            row,
            canonical_url=request.build_absolute_uri("/"),
            building=True,
        )

    def __call__(self, request):
        host = request_host(request)
        configured_ads_host = ads_host()
        if not configured_ads_host:
            return self.get_response(request)

        if host == configured_ads_host:
            request.is_ads_subdomain = True
            path = request.path_info

            #   The public page is the root of the ads host. Resolve it to the
            #   existing view without changing request.path, so templates and
            #   login return URLs see "/" while Django still matches the view.
            if path in ("", "/"):
                request.path_info = "/promote-your-bussiness/"
                request.META["PATH_INFO"] = request.path_info
                return self.get_response(request)
            if path == "/enquiry/":
                request.path_info = "/promote-your-bussiness/enquiry/"
                request.META["PATH_INFO"] = request.path_info
                return self.get_response(request)
            if self._ads_path_allowed(path):
                return self.get_response(request)

            main_origin = canonical_origin(request)
            if main_origin:
                return HttpResponsePermanentRedirect(
                    f"{main_origin}{request.get_full_path()}"
                )
            return self.get_response(request)

        custom_label = advert_subdomain_from_host(host)
        if custom_label:
            return self._serve_advert_host(request, custom_label)

        #   The old main-domain URL is a permanent invite to the new home of
        #   the ads page. Only safe methods are redirected here; a legacy form
        #   POST still reaches the lead view and is not turned into a GET.
        if (
            host != "testserver"
            and request.path_info in self._PROMOTE_PATHS
            and request.method in {"GET", "HEAD"}
        ):
            origin = ads_origin(request)
            if origin:
                query = request.META.get("QUERY_STRING", "")
                location = f"{origin}/"
                if query:
                    location = f"{location}?{query}"
                return HttpResponsePermanentRedirect(location)

        return self.get_response(request)


class MaintenanceModeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Check whether maintenance mode is enabled.
        value = getattr(settings, "MAINTENANCE_MODE", "TRUE")

        if str(value).upper() == "TRUE":
            html_message = f"""
            <!DOCTYPE html>
            <html lang="en">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport"
                          content="width=device-width, initial-scale=1.0">
                    <title>Service Down</title>
                </head>
                <body style="font-family: Arial, sans-serif;
                             text-align: center;
                             padding: 50px;">
                    <h1>Maintenance Mode</h1>
                    <p>System is currently in maintenance mode.</p>
                    <p>Please try again later.</p>
                    <p>We are sorry for the inconvenience.</p>
                    <p>This downtime is temporary.</p>
                    <p>{About.project_name} team cares.</p>
                </body>
            </html>
            """

            return HttpResponse(
                html_message,
                content_type="text/html; charset=utf-8",
                status=503,
            )

        response = self.get_response(request)
        return response
