import logging
import secrets
import string
from urllib.parse import quote, urlsplit

from django.contrib.auth import authenticate, login, logout
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views import View
from django.contrib import messages

from django.contrib.auth import get_user_model
from SERVICE_INTERNAL.abstract import _response, is_rate_limited
from SERVICE_INTERNAL.config import About
from SERVICE_INTERNAL.email_single import _try_send_login_email, _try_send_password_reset_email

logger = logging.getLogger(__name__)

#   THE TWO RANDOM HALVES OF THE PASSWORD RESET LINK: a 6 digit numeric key
#   and a 10 character alphanumeric sign. Both are stored in the db against
#   the account and both must still be there for a password change to pass.
RESET_KEY_LENGTH = 6
RESET_SIGN_LENGTH = 10


def _return_to(request):
    """Return a safe, local path supplied by the guest auth flow."""

    target = (request.POST.get("to") or request.GET.get("to") or "").strip()
    if not target or target.startswith(("//", "/\\")):
        return "/"

    parsed = urlsplit(target)
    if (
        not target.startswith("/")
        or parsed.scheme
        or parsed.netloc
        or not url_has_allowed_host_and_scheme(
            target,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )
    ):
        return "/"
    return target


def _auth_context(request, **context):
    return {"return_to": _return_to(request), **context}


class LoginView(View):
    def get(self, request): 

        if request.user.is_authenticated:
            messages.info(request, message=f"Hello {request.user.email}, welcome back.".upper())
            return redirect(_return_to(request))
        #i noticed that if the password is visible, the login btn will not click; dont know if its a feature of a bug but currenlty, i am taking it as a feature
        # "SHow the information below to users for them to know the login btn is not broken but image is not showing in the ui, need fixing"
        messages.info(request, "Hide password to enable login.")
        return render(request, "auth/login.html", _auth_context(request))
    
    def post(self, request):
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        # rate limting here
        remaining_time, _rate_limit = is_rate_limited(request, timeout_window=15, max_requests=3)
        if _rate_limit:
            error = f"Too Frequent Request, try again in {remaining_time} seconds"
            if is_ajax:
                return _response({"detail": error}, status=429)
            return render(request, 'auth/login.html', _auth_context(request, error=error), status=429)

        email = (request.POST.get("email") or "").strip()
        password = (request.POST.get("password") or "").strip()
        if not email or not password:
            if is_ajax:
                return _response({"detail": "Email and password are required."}, status=400)
            return render(request, "auth/login.html", _auth_context(request, error="Email and password are required."), status=400)
        user = get_user_model().objects.filter(email__iexact = email).first()
        if user is None or not user.check_password(password):
            if is_ajax:
                return _response({"detail": "Invalid email or password."}, status=401)
            return render(request, "auth/login.html", _auth_context(request, error="Invalid email or password."), status=401)


        if user is not None and user.is_active:
            login(request, user)
            return_to = _return_to(request)
            if is_ajax:
                return _response({"detail": "Login successful.", "redirect_to": return_to}, status=200)
            return redirect(return_to)
        if user is not None and not user.is_active:
            if is_ajax:
                return _response({"detail": "Account Have Been Suspended."}, status=403)
            return render(request, "auth/login.html", _auth_context(request, error="Account Have Been Suspended."), status=403)
        if is_ajax:
            return _response({"detail": "Invalid email or password."}, status=401)
        return render(request, "auth/login.html", _auth_context(request, error="Invalid email or password."), status=401)


class LogoutView(View):
    def post(self, request):
        logout(request)
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return _response({"detail": "success"}, status=200)
        return redirect("/")


class RegisterView(View):
    def get(self, request):
        if request.user.is_authenticated:
            messages.info(request, message=f"Hello {request.user.email}, welcome back.".upper())
            return redirect(_return_to(request))
        return render(request, "auth/register.html", _auth_context(request))

    def post(self, request):
        is_ajax = request.headers.get("X-Requested-With") == "XMLHttpRequest"
        email = (request.POST.get("email") or "").strip()
        password = (request.POST.get("password") or "").strip()
        confirm = (request.POST.get("password_confirm") or "").strip()

        if not email or not password:
            error = "Email and password are required."
        elif "@" not in email:
            error = "Enter a valid email address."
        elif password != confirm:
            error = "Passwords do not match."
        elif len(password) < 6:
            error = "Password must be at least 6 characters long."
        elif get_user_model().objects.filter(email__iexact=email).exists():
            error = "Email Taken OR Email Not Allowed"
        else:
            error = None

        if error is not None:
            if is_ajax:
                return _response({"detail": error}, status=400)
            return render(request, "auth/register.html", _auth_context(request, error=error), status=400)

        user = get_user_model().objects.create_user(email=email, password=password)
        login(request, user)
        return_to = _return_to(request)
        if is_ajax:
            return _response({"detail": "Account created successfully.", "redirect_to": return_to}, status=200)
        return redirect(return_to)


def _generate_reset_key():
    """The 6 digit numeric half of the reset link."""
    return "".join(secrets.choice(string.digits) for _ in range(RESET_KEY_LENGTH))


def _generate_reset_sign():
    """The 10 character alphanumeric half of the reset link."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(RESET_SIGN_LENGTH))


def _build_reset_link(user, key, sign):
    """domain/auth/password-reset/?email=...&key=...&sign=..."""
    return (
        f"{About.domain}/auth/password-reset/"
        f"?email={quote(user.email)}&key={quote(key)}&sign={quote(sign)}"
    )


def _reset_link_payload(request):
    """Pull email, key and sign off the link (query string or posted hidden
    fields). Returns them stripped, empty strings when absent."""
    source = request.POST if request.method == "POST" else request.GET
    return (
        (source.get("email") or "").strip(),
        (source.get("key") or "").strip(),
        (source.get("sign") or "").strip(),
    )


def _match_reset_row(email, key, sign):
    """The stateless link is only trusted when its email, key and sign trio
    is still stored in the db. Returns the row or None."""
    from AUTHENTICATION.models import PasswordResetKey

    if not email or not key or not sign:
        return None
    return (
        PasswordResetKey.objects.select_related("user")
        .filter(user__email__iexact=email, key=key, sign=sign)
        .first()
    )


class PasswordResetView(View):
    """Forgotten password flow.

    GET  /auth/password-reset/                          -> email request form
    GET  /auth/password-reset/?email=&key=&sign=        -> new password form
                                                            (or invalid link page)
    POST stage=request  (email)                         -> "sends" the link
    POST stage=confirm  (email, key, sign, passwords)   -> updates password

    The link carries no identity beyond its three parameters, so before any
    password update the email + key + sign trio is verified against the db
    and the row is deleted on success: one link, one use.
    """

    def get(self, request):
        email, key, sign = _reset_link_payload(request)
        if email or key or sign:
            if _match_reset_row(email, key, sign) is not None:
                return render(
                    request,
                    "auth/password_reset.html",
                    {"stage": "confirm", "email": email, "key": key, "sign": sign},
                )
            return render(request, "auth/password_reset.html", {"stage": "invalid"}, status=400)
        return render(request, "auth/password_reset.html", {"stage": "request"})

    def post(self, request):
        stage = (request.POST.get("stage") or "").strip()
        if stage == "confirm":
            return self._confirm(request)
        return self._request_link(request)

    def _request_link(self, request):
        remaining_time, is_limited = is_rate_limited(request, timeout_window=60, max_requests=3)
        if is_limited:
            return render(
                request,
                "auth/password_reset.html",
                {"stage": "request", "error": f"Too frequent requests. Try again in {remaining_time} seconds."},
                status=429,
            )

        email = (request.POST.get("email") or "").strip()
        if not email or "@" not in email:
            return render(
                request,
                "auth/password_reset.html",
                {"stage": "request", "error": "Enter a valid email address."},
                status=400,
            )

        #   The response text is deliberately the same whether or not the
        #   email has an account, so nobody can probe which emails exist.
        user = get_user_model().objects.filter(email__iexact=email).first()
        if user is not None:
            key, sign = _generate_reset_key(), _generate_reset_sign()
            from AUTHENTICATION.models import PasswordResetKey

            #   One live link per account: an older row is replaced, never
            #   duplicated, so only the newest link can ever work.
            PasswordResetKey.objects.filter(user=user).delete()
            PasswordResetKey.objects.create(user=user, key=key, sign=sign)
            _try_send_password_reset_email(user, _build_reset_link(user, key, sign))
            info_logger(msg=f"PASSWORD RESET: link generated for {user.email}")

        return render(request, "auth/password_reset.html", {"stage": "sent", "email": email})

    def _confirm(self, request):
        remaining_time, is_limited = is_rate_limited(request, timeout_window=60, max_requests=5)
        if is_limited:
            return render(
                request,
                "auth/password_reset.html",
                {"stage": "invalid", "error": f"Too frequent requests. Try again in {remaining_time} seconds."},
                status=429,
            )

        email, key, sign = _reset_link_payload(request)
        reset_row = _match_reset_row(email, key, sign)
        if reset_row is None:
            #   Forged, stale or already used trio: nothing in the db to
            #   match it, so no password is ever touched.
            return render(request, "auth/password_reset.html", {"stage": "invalid"}, status=400)

        new_password = (request.POST.get("new_password") or "").strip()
        confirm_password = (request.POST.get("confirm_password") or "").strip()
        if not new_password or not confirm_password:
            return render(
                request,
                "auth/password_reset.html",
                {"stage": "confirm", "email": email, "key": key, "sign": sign, "error": "Enter and confirm the new password."},
                status=400,
            )
        if new_password != confirm_password:
            return render(
                request,
                "auth/password_reset.html",
                {"stage": "confirm", "email": email, "key": key, "sign": sign, "error": "Passwords do not match."},
                status=400,
            )
        if len(new_password) < 6:
            return render(
                request,
                "auth/password_reset.html",
                {"stage": "confirm", "email": email, "key": key, "sign": sign, "error": "Password must be at least 6 characters long."},
                status=400,
            )

        user = reset_row.user
        user.set_password(new_password)
        user.save(update_fields=["password"])
        #   Single use: the moment the password is updated the key and sign
        #   are wiped, so this exact link can never reset anything again.
        reset_row.delete()
        info_logger(logger, msg=f"PASSWORD RESET: {user.email} updated their password through a reset link")

        messages.success(request, "Password updated. You can now sign in with your new password.")
        return redirect("auth:login")


from SERVICE_INTERNAL.abstract import info_logger
def csrf_failure(request, exception=None, **args):
    info_logger(msg=f"CSRF_ERROR: {request.user or 'Anonymous user'} tried to perform some action but experienced CSRF error")
    # return JsonResponse({'detail': 'csrf error'}, status = 403)
    return render(request, "csrf_fail.html", status=403)
