"""Shared session helpers.

The admin suspend control and the user facing "log out all sessions"
control both need to end every session an account holds, so the walk lives
here once instead of being copied per caller.
"""

from django.contrib.sessions.models import Session


def drop_sessions_for(account):
    """Delete every active session belonging to an account. Returns how many
    sessions were dropped.

    The walk decodes every row in the session table, which is fine at the
    current scale; if the site grows this needs an index backed approach
    instead of a full table scan.
    """
    dropped = 0
    for session in Session.objects.filter(session_key__isnull=False).iterator():
        decoded = session.get_decoded() or {}
        if str(decoded.get("_auth_user_id")) == str(account.pk):
            session.delete()
            dropped += 1
    return dropped
