"""Shared session helpers.

The admin suspend control and the user facing "log out all sessions"
control both need to end every session an account holds, so the walk lives
here once instead of being copied per caller.
"""

from django.contrib.sessions.models import Session


def drop_sessions_for(account):
    """Delete every active session belonging to an account.
    Returns how many sessions were dropped.
    """
    from AUTHENTICATION.models import UserSession
    from django.contrib.sessions.models import Session

    session_keys = list(UserSession.objects.filter(user=account).values_list("session_key", flat=True))
    if not session_keys:
        return 0

    Session.objects.filter(session_key__in=session_keys).delete()
    UserSession.objects.filter(session_key__in=session_keys).delete()
    return len(session_keys)