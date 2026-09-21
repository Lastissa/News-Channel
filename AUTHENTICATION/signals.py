from datetime import timedelta

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from django.conf import settings
from django.utils import timezone

from SERVICE_INTERNAL.abstract import info_logger
from SERVICE_INTERNAL.email_single import _try_send_login_email

from .models import UserSession

@receiver(user_logged_in)
def track_login(sender, request, user, **kwargs):
    if not request.session.session_key:
        return
    
    _try_send_login_email(user)
    UserSession.objects.update_or_create(
        session_key=request.session.session_key,
        # THE DEFAULT EXIST AS PER I AM USING A UPDATE OR CREATE AND IT NEED VARIBALE WHILE THE ABOVE IS THE REAL LOOKUP
        defaults={
            "user": user,
            "ip": request.META.get("REMOTE_ADDR"),
            "user_agent": request.META.get("HTTP_USER_AGENT", "")[:255],
            'expires_at': timezone.now() + timedelta(seconds=settings.SESSION_COOKIE_AGE),
        },
    )


@receiver(user_logged_out)
def track_logout(sender, request, user, **kwargs):
    if not request.session.session_key:
        return
    email = getattr(user, "email", None) or "Anonymous"
    info_logger(msg=f"ACCOUNT LOGOUT: {email} logged out successfully")
    UserSession.objects.filter(session_key=request.session.session_key).delete()