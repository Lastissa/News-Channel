from __future__ import annotations

from typing import Callable


def is_authenticated(user) -> bool:
    return bool(user and getattr(user, "is_authenticated", False))


def staff_only(user) -> bool:
    return bool(
        is_authenticated(user)
        and (getattr(user, "is_staff", False) or getattr(user, "is_admin", False) or getattr(user, "is_superuser", False))
    )


def admin_only(user) -> bool:
    return bool(
        is_authenticated(user)
        and (getattr(user, "is_admin", False) or getattr(user, "is_superuser", False))
    )


def admin_or_staff(user) -> bool:
    return bool(staff_only(user) or admin_only(user))


def ads_staff_only(user) -> bool:
    """The advertising desk.

    Admin/superuser always qualify. A normal staff or reader account can be
    given ``Auth.is_ads_staff`` to issue references and see advert activity
    without receiving the rest of PANEL.
    """
    return bool(
        is_authenticated(user)
        and (
            getattr(user, "is_admin", False)
            or getattr(user, "is_superuser", False)
            or getattr(user, "is_ads_staff", False)
        )
    )


def permission_required(predicate: Callable[[object], bool], login_url: str = "/auth/login/"):
    def decorator(view_func):
        def wrapped(request, *args, **kwargs):
            if not predicate(request.user):
                from django.shortcuts import redirect

                return redirect(login_url)
            return view_func(request, *args, **kwargs)

        return wrapped

    return decorator
