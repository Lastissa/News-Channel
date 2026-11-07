
from django.conf import settings
from django.http import HttpResponse
from django.urls import reverse
from SERVICE_INTERNAL.config import About


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
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "img-src 'self' data: https: "
        "https://*.google.com https://*.gstatic.com https://*.googlesyndication.com "
        "https://*.doubleclick.net https://*.adtrafficquality.google; "
        "font-src 'self' data: https://fonts.gstatic.com; "
        "connect-src 'self' https://*.google-analytics.com "
        "https://*.googlesyndication.com https://*.doubleclick.net "
        "https://*.google.com https://*.adtrafficquality.google; "
        "frame-src 'self' https://googleads.g.doubleclick.net https://*.doubleclick.net "
        "https://*.google.com https://fundingchoicesmessages.google.com "
        "https://www.youtube.com https://youtube.com https://www.youtube-nocookie.com "
        "https://player.vimeo.com; "
        "media-src 'self' https:; "
        "worker-src 'self' blob:; "
        "manifest-src 'self'"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        report_url = ""
        if getattr(settings, "CSP_REPORT_ENABLED", True):
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
