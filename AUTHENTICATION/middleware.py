import time

from django.core.cache import cache
from django.shortcuts import redirect, render
from django.contrib.auth import logout
from django.utils import timezone


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


class ActiveSessionTracker:
    """Keeps the UserSession row in step with the live Django session.

    The row is written once at sign-in, and its expiry was a copy of the
    cookie age taken at that moment. A browser session does not end there:
    Django slides the session's own expiry forward every time the session is
    saved, so a reader who stays signed in for days had a UserSession row
    that had already expired -- and the PANEL and the profile, which both read
    that row, told them nobody was logged in while they were plainly signed
    in.

    This middleware refreshes the row instead: its expiry becomes the session
    session's real expiry, and its "last seen" stamp becomes the real last
    seen. The write is throttled to one row update a minute so a page full
    of assets does not turn into a page full of writes, and it never raises:
    a failed refresh must not break the page the reader asked for.
    """

    REFRESH_SECONDS = 60

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        self._refresh(request)
        return response

    def _refresh(self, request):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return
        session_key = getattr(request.session, "session_key", None)
        if not session_key:
            return

        try:
            from .models import UserSession

            row = UserSession.objects.filter(user=user, session_key=session_key).first()
            if row is None:
                return

            now = timezone.now()
            age = (now - row.last_seen).total_seconds()
            if age < self.REFRESH_SECONDS:
                return

            expires_at = request.session.get_expiry_date()
            UserSession.objects.filter(pk=row.pk).update(
                last_seen=now,
                expires_at=expires_at,
            )
        except Exception as exc:  # pragma: no cover - a tracker must never 500 a page
            from SERVICE_INTERNAL.abstract import error_logger

            error_logger(msg=f"ACTIVE SESSION TRACKER: refresh failed error={exc}")