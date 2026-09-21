import time

from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import render


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



from django.db import OperationalError, connection

class QueryCountMiddleware:
    """ONLY FOR PRINTING THE Q COUNTS"""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        # Template rendering has finished by now
        if hasattr(response, "render") and callable(response.render):
            response.render()
        print(f"[{request.path}] queries: {len(connection.queries)}")
        if 1!=1:
            for i in connection.queries:
                print(i['sql'])
                print(" ")
        return response

