
from django.conf import settings
from django.http import HttpResponse
from django.utils.deprecation import MiddlewareMixin
from SERVICE_INTERNAL.config import About

class MaintenanceModeMiddleware(MiddlewareMixin):
    
    def process_request(self, request):
        # Check if maintenance mode is enabled in settings
        value = getattr(settings, 'MAINTENANCE_MODE', "TRUE")
        if value.upper() == "TRUE":
            html_message = f"""
            <html>
                <head>
                    <title>Service Down</title>
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    
                    </head>
                <body style="font-family: Arial, sans-serif; text-align: center; padding: 50px;">
                    <h1>Maintenance Mode</h1>
                    <p>System is currently in maintenance mode.</p>
                    <p>Please try again later.</p>
                    <p>We are very sorry for the inconvenience.</p>
                    <p>This downtime is temporary.</p>
                    <p>{About.project_name} team cares.</p>
                </body>
            </html>
            """
            return HttpResponse(html_message, content_type="text/html", status=503)
        return None