
from django.conf import settings
from django.http import HttpResponse
from SERVICE_INTERNAL.config import About


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
