import time

from django.core.cache import cache
from django.shortcuts import redirect, render
from django.contrib.auth import logout


class AuthEndpointThrottleMiddleware:
    """Protect auth GET endpoini from rapid refresh / bot-like abuse."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == "GET" and request.path.startswith("/auth/"):
            ban_duration , maximum_attempt = 4,3
            if self._is_blocked(request, ban_duration, maximum_attempt):
                return render(request,"auth/endpoint_rate_limit.html",{"retry_after": ban_duration},status=429)
        return self.get_response(request)

    def _is_blocked(self, request, ban_dur, max_attempt):
        ip = request.META.get("REMOTE_ADDR") or "unknown"
        path = request.path
        key = f"auth-get-throttle:{ip}:{path}"
        ban_key = f"{key}-ban"
        now = time.time()

        ban_until = cache.get(ban_key)  #   A TIME.TIME() RESPONSE
        if ban_until is not None:
            if now < float(ban_until):
                return True
            cache.delete(ban_key)

        timestamps = cache.get(key, [])
        if not isinstance(timestamps, list):
            timestamps = []

        timestamps = [i for i in timestamps if now - float(i) <= ban_dur-1]
        timestamps.append(now)
        cache.set(key, timestamps, timeout=10)

        if len(timestamps) >= max_attempt:
            cache.set(ban_key, now + ban_dur, timeout=ban_dur)
            return True

        return False



from django.db import connection
from django.conf import settings

class QueryCountMiddleware:
    """ONLY FOR PRINTING THE Q COUNTS, and only while DEBUG is on: in
    production this middleware does nothing at all, so a page view never pays
    for the forced template render or the print."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if not settings.DEBUG:
            return response
        # Template rendering has finished by now
        if hasattr(response, "render") and callable(response.render):
            response.render()
        print(f"[{request.path}] queries: {len(connection.queries)}")
        if 1 != 1:
            for i in connection.queries:
                print(i['sql'])
                print(" ")
        return response


class AdminMaxPeriod:
    def __init__(self, get_response):
        self.get_response = get_response
        
    def __call__(self, request):
        # ADMIN HAVE TO BE LOGGED OUT FAST TO PREVENT HAKCER USING THEIR CREDS.
        if request.user.is_authenticated and request.user.is_admin:
            tracker = request.session.get('last_activity')
            now = time.time()
            timeout = getattr(settings, "ADMIN_MAX_AGE_TOO", 1 * 60 * 60)
            if tracker and now - tracker > timeout:
                logout(request)
                from django.contrib import messages

                messages.error(request, "ADMIN (logged out)!")
                return redirect("auth:login")
            request.session['last_activity'] = now

        return self.get_response(request)