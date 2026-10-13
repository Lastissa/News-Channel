"""One place that runs Django's configured password validators.

Every password entry point in the project (register, password reset, admin
staff creation) keeps its own explicit "at least 6 characters" check for a
friendly message, then calls `first_password_error` so the same
AUTH_PASSWORD_VALIDATORS (minimum length, common password, numeric, similarity)
are enforced no matter which form the password arrived through. The validators
are intentionally NOT run inside AuthManager: accounts created by the system
itself (newsletter starter account, tests) must not be blocked by them.
"""

from django.contrib.auth import password_validation
from django.core.exceptions import ValidationError


def first_password_error(password, user=None):
    """Return the first validator message for `password`, or "" when it passes.

    `user`, when given, lets the similarity validator compare the password
    against the account's own email. Callers that create the account in the
    same request can pass an unsaved instance carrying just that email.
    """
    if not password:
        return "Password is required."
    try:
        password_validation.validate_password(password, user=user)
    except ValidationError as exc:
        if exc.messages:
            return exc.messages[0]
        return "Choose a stronger password."
    return ""
