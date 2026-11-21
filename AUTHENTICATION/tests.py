import json
from unittest import mock

from datetime import timedelta

from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.models import Session
from django.contrib.sessions.backends.db import SessionStore
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from AUTHENTICATION.models import Auth, KnownDevice, UserSession
from AUTHENTICATION.views import csrf_failure
from BLOG.models import Blog
from SERVICE_INTERNAL.sessions import drop_single_session, live_sessions_for


class AuthReturnPathTests(TestCase):
    def test_guest_auth_links_preserve_the_current_local_path(self):
        response = self.client.get("/search/?q=admissions")

        self.assertContains(response, "/auth/login/?to=/search/%3Fq%3Dadmissions")
        self.assertContains(response, "/auth/register/?to=/search/%3Fq%3Dadmissions")
        self.assertContains(response, "data-category-filter")
        self.assertContains(response, "data-category-option")

    def test_login_redirects_to_the_requested_local_path(self):
        user = Auth.objects.create_user(email="returning@example.com", password="secret123")

        response = self.client.post(
            "/auth/login/",
            {"email": user.email, "password": "secret123", "to": "/privacy-policy/?section=data"},
        )

        self.assertRedirects(response, "/privacy-policy/?section=data", fetch_redirect_response=False)

    def test_registration_redirects_to_the_requested_local_path(self):
        response = self.client.post(
            "/auth/register/",
            {
                "email": "new-reader@example.com",
                "password": "testpass123",
                "password_confirm": "testpass123",
                "to": "/promote/",
            },
        )

        self.assertRedirects(response, "/promote/", fetch_redirect_response=False)

    def test_external_return_path_is_rejected(self):
        user = Auth.objects.create_user(email="safe-return@example.com", password="secret123")

        response = self.client.post(
            "/auth/login/",
            {"email": user.email, "password": "secret123", "to": "https://example.com/"},
        )

        self.assertRedirects(response, "/", fetch_redirect_response=False)


class AdvertiserSignupTests(TestCase):
    """The advertising sign-up is a separate door from the reader register
    page: same account system, but the new account carries the advertiser tag."""

    def test_advertiser_signup_page_uses_advertiser_copy(self):
        response = self.client.get(reverse("auth:advertiser_register"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create your advertiser account")
        self.assertContains(response, "advertising dashboard")
        self.assertContains(response, "See the weekly rates")
        self.assertContains(response, 'name="password_confirm"')
        #   The shared navbar/footer must stay in the advertiser flow here too.
        self.assertNotContains(response, reverse("auth:register"))

    def test_advertiser_signup_tags_the_new_account(self):
        response = self.client.post(
            reverse("auth:advertiser_register"),
            {
                "email": "new-advertiser@example.com",
                "password": "testpass123",
                "password_confirm": "testpass123",
            },
        )

        self.assertRedirects(
            response,
            reverse("home:advertise_dashboard"),
            fetch_redirect_response=False,
        )
        user = Auth.objects.get(email="NEW-ADVERTISER@EXAMPLE.COM")
        self.assertTrue(user.is_advertiser)

    def test_advertiser_signup_honours_a_safe_return_path(self):
        response = self.client.post(
            reverse("auth:advertiser_register"),
            {
                "email": "returning-advertiser@example.com",
                "password": "testpass123",
                "password_confirm": "testpass123",
                "to": reverse("home:promote"),
            },
        )

        self.assertRedirects(
            response,
            reverse("home:promote"),
            fetch_redirect_response=False,
        )
        self.assertTrue(
            Auth.objects.get(email="RETURNING-ADVERTISER@EXAMPLE.COM").is_advertiser
        )

    def test_reader_registration_does_not_set_the_advertiser_tag(self):
        response = self.client.post(
            reverse("auth:register"),
            {
                "email": "plain-reader@example.com",
                "password": "testpass123",
                "password_confirm": "testpass123",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Auth.objects.get(email="PLAIN-READER@EXAMPLE.COM").is_advertiser)


class GateConfirmPasswordTests(TestCase):
    """The guest "Sign in" popup no longer asks for a confirm password (see
    auth/gate.html); the full register page keeps its confirm box, and the
    register endpoint still rejects a mismatched confirm when one is sent."""

    def test_gate_popup_has_no_confirm_password_field(self):
        response = self.client.get(reverse("auth:gate"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create account")
        self.assertContains(response, "Sign in")
        self.assertNotContains(response, "Confirm password")
        self.assertNotContains(response, "password_confirm")

    def test_registration_without_confirm_password_succeeds(self):
        response = self.client.post(
            "/auth/register/",
            {"email": "no-confirm@example.com", "password": "testpass123"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Auth.objects.filter(email="NO-CONFIRM@EXAMPLE.COM").exists())

    def test_registration_rejects_a_common_password(self):
        #   The 6 character minimum is not enough on its own: the project also
        #   runs Django's password validators (see SERVICE_INTERNAL.passwords),
        #   so a well known password is refused even though it is long enough.
        response = self.client.post(
            "/auth/register/",
            {"email": "weak@example.com", "password": "password"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Auth.objects.filter(email="WEAK@EXAMPLE.COM").exists())

    def test_registration_with_mismatched_confirm_is_still_rejected(self):
        response = self.client.post(
            "/auth/register/",
            {"email": "mismatch@example.com", "password": "secret123", "password_confirm": "different"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Auth.objects.filter(email="MISMATCH@EXAMPLE.COM").exists())


class AuthAdminDeleteReleasesCloudinaryAssetsTests(TestCase):
    """Deleting an account from the hidden Django admin (_admin/) releases every
    Cloudinary asset the cascade removes (its story banners, image adverts,
    archive uploads and avatar), exactly like
    HOME.views.ProfileDeleteAccountView does."""

    def setUp(self):
        self.user = Auth.objects.create_user(email="admin-delete-me@example.com")
        self.user_pk = self.user.pk
        Auth.objects.filter(pk=self.user.pk).update(
            profile_img="https://res.cloudinary.com/test/image/upload/v1/abureport/avatars/user_x.jpg"
        )
        self.user.refresh_from_db()
        Blog.objects.create(
            author=self.user,
            heading="Admin account story",
            category="GENERAL",
            content="Body.",
            image_1="https://example.com/banner.jpg",
            image_public_id="abureport/news/admin-account",
        )
        self.model_admin = admin.site._registry[Auth]
        self.request = RequestFactory().get("/_admin/")

    def test_delete_model_releases_the_story_banner_and_avatar(self):
        with mock.patch("HOME.views.destroy_archive_asset", return_value=True) as destroy_asset:
            self.model_admin.delete_model(self.request, self.user)
        self.assertFalse(Auth.objects.filter(pk=self.user_pk).exists())
        self.assertEqual(
            {call.args for call in destroy_asset.call_args_list},
            {("abureport/news/admin-account", "image"), (f"abureport/avatars/user_{self.user_pk}",)},
        )


def _login_from(email, password, ip, user_agent):
    """Sign a brand new client in from a given network + browser so the login
    signal records a session for that "device"."""
    client = Client()
    client.post(
        "/auth/login/",
        {"email": email, "password": password},
        REMOTE_ADDR=ip,
        HTTP_USER_AGENT=user_agent,
    )
    return client


class SessionTrackingTests(TestCase):
    """The login signal records a UserSession per sign-in and flags a login
    from a device the account has never used before as suspicious. That flag
    rides on the session row, so ending the session clears it."""

    def setUp(self):
        self.user = Auth.objects.create_user(email="sessions@example.com", password="secret123")
        #   The login view rate-limits per IP and the cache outlives a test,
        #   so clear it or a later test from the same IP is served a 429.
        cache.clear()

    def test_first_device_is_not_suspicious(self):
        _login_from(self.user.email, "secret123", "10.0.0.1", "AgentA")

        session = UserSession.objects.get(user=self.user)
        self.assertFalse(session.is_suspicious)
        self.assertTrue(KnownDevice.objects.filter(user=self.user).exists())

    def test_login_from_a_new_device_is_suspicious(self):
        _login_from(self.user.email, "secret123", "10.0.0.1", "AgentA")
        _login_from(self.user.email, "secret123", "10.0.0.2", "AgentB")

        self.assertEqual(UserSession.objects.filter(user=self.user).count(), 2)
        self.assertEqual(
            UserSession.objects.filter(user=self.user, is_suspicious=True).count(), 1
        )

    def test_returning_device_stays_recognised(self):
        _login_from(self.user.email, "secret123", "10.0.0.1", "AgentA")
        _login_from(self.user.email, "secret123", "10.0.0.2", "AgentB")
        _login_from(self.user.email, "secret123", "10.0.0.1", "AgentA")

        #   The third sign-in is from the already-known first device, so only
        #   the second-device session carries the flag.
        self.assertEqual(
            UserSession.objects.filter(user=self.user, is_suspicious=True).count(), 1
        )

    def test_expired_sessions_are_not_live(self):
        _login_from(self.user.email, "secret123", "10.0.0.1", "AgentA")
        session = UserSession.objects.get(user=self.user)
        session.expires_at = timezone.now() - timedelta(minutes=1)
        session.save(update_fields=["expires_at"])

        self.assertEqual(live_sessions_for(self.user), [])

    def test_sessions_without_a_django_row_are_not_live(self):
        _login_from(self.user.email, "secret123", "10.0.0.1", "AgentA")
        session = UserSession.objects.get(user=self.user)
        Session.objects.filter(session_key=session.session_key).delete()

        self.assertEqual(live_sessions_for(self.user), [])

    def test_drop_single_session_only_ends_that_one(self):
        first_client = _login_from(self.user.email, "secret123", "10.0.0.1", "AgentA")
        _login_from(self.user.email, "secret123", "10.0.0.2", "AgentB")
        first_key = first_client.session.session_key

        self.assertTrue(drop_single_session(first_key))

        remaining = UserSession.objects.filter(user=self.user)
        self.assertEqual(remaining.count(), 1)
        self.assertNotEqual(remaining.first().session_key, first_key)


class ActiveSessionTrackerTests(TestCase):
    """A signed in reader's session row has to keep up with the live Django
    session. The row used to carry a frozen copy of the cookie age taken at
    sign-in, so a reader who stayed signed in for longer than that was told
    by the PANEL and by the profile that nobody was logged in while they were
    plainly signed in."""

    def setUp(self):
        cache.clear()
        self.user = Auth.objects.create_user(email="tracker@example.com", password="secret123")

    def test_the_row_is_refreshed_while_the_reader_browses(self):
        client = _login_from(self.user.email, "secret123", "10.0.0.1", "AgentA")
        row = UserSession.objects.get(user=self.user)

        stale = timezone.now() - timedelta(hours=1)
        UserSession.objects.filter(pk=row.pk).update(last_seen=stale, expires_at=stale)

        client.get("/")

        row.refresh_from_db()
        self.assertGreater(row.expires_at, timezone.now())
        self.assertGreater(row.last_seen, stale)

    def test_a_session_that_is_still_running_stays_live(self):
        client = _login_from(self.user.email, "secret123", "10.0.0.1", "AgentA")
        row = UserSession.objects.get(user=self.user)

        stale = timezone.now() - timedelta(hours=1)
        UserSession.objects.filter(pk=row.pk).update(last_seen=stale, expires_at=stale)
        self.assertEqual(live_sessions_for(self.user), [])

        client.get("/")

        self.assertEqual(len(live_sessions_for(self.user)), 1)

    def test_the_refresh_is_throttled_to_one_write_a_minute(self):
        client = _login_from(self.user.email, "secret123", "10.0.0.1", "AgentA")
        row = UserSession.objects.get(user=self.user)
        first_seen = row.last_seen

        client.get("/")

        row.refresh_from_db()
        self.assertEqual(row.last_seen, first_seen)


class ProfileSessionPlacardTests(TestCase):
    """The profile "Active sessions" control opens a placard listing the live
    sessions, and each row can end exactly one session."""

    def setUp(self):
        self.user = Auth.objects.create_user(email="placard@example.com", password="secret123")
        self.client.force_login(self.user)

    def _make_other_session(self):
        store = SessionStore()
        store.create()
        UserSession.objects.create(
            user=self.user,
            session_key=store.session_key,
            ip="10.0.0.9",
            user_agent="OtherAgent/9.0",
            expires_at=timezone.now() + timedelta(hours=1),
            is_suspicious=True,
        )
        return store.session_key

    def test_placard_lists_sessions_and_tags_the_current_one(self):
        self._make_other_session()

        response = self.client.get(reverse("home:profile_sessions_placard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Active sessions")
        self.assertContains(response, "This device")
        self.assertContains(response, "Unrecognised")

    def test_ending_another_session_keeps_the_current_one(self):
        other_key = self._make_other_session()

        response = self.client.post(
            reverse("home:profile_session_logout"), {"session_key": other_key}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["removed"], "other")
        self.assertFalse(UserSession.objects.filter(session_key=other_key).exists())

    def test_ending_the_current_session_signs_the_browser_out(self):
        current_key = self.client.session.session_key

        response = self.client.post(
            reverse("home:profile_session_logout"), {"session_key": current_key}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["removed"], "current")
        self.assertIn("redirect_to", response.json())
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_cannot_end_a_session_belonging_to_someone_else(self):
        stranger = Auth.objects.create_user(email="stranger@example.com", password="secret123")
        store = SessionStore()
        store.create()
        UserSession.objects.create(
            user=stranger,
            session_key=store.session_key,
            expires_at=timezone.now() + timedelta(hours=1),
        )

        response = self.client.post(
            reverse("home:profile_session_logout"), {"session_key": store.session_key}
        )

        self.assertEqual(response.status_code, 404)
        self.assertTrue(UserSession.objects.filter(session_key=store.session_key).exists())


class PanelActiveSessionsAccuracyTests(TestCase):
    """PANEL's "Active Logins" list counts only sessions that are genuinely
    live: an account whose only row is past its expiry is not listed at all."""

    def test_expired_accounts_are_not_counted(self):
        from ADMIN.views import _active_sessions_page

        cache.clear()
        live_user = Auth.objects.create_user(email="live-session@example.com", password="secret123")
        gone_user = Auth.objects.create_user(email="gone-session@example.com", password="secret123")
        _login_from(live_user.email, "secret123", "10.1.1.1", "Agent")
        _login_from(gone_user.email, "secret123", "10.1.1.2", "Agent")

        UserSession.objects.filter(user=gone_user).update(
            expires_at=timezone.now() - timedelta(hours=1)
        )

        _paginator, _page, rows, total = _active_sessions_page(1)
        ids = {row["id"] for row in rows}

        self.assertIn(live_user.pk, ids)
        self.assertNotIn(gone_user.pk, ids)
        self.assertEqual(total, len(rows))

    def test_live_row_exposes_per_session_detail(self):
        from ADMIN.views import _active_sessions_page

        cache.clear()
        user = Auth.objects.create_user(email="detail-session@example.com", password="secret123")
        _login_from(user.email, "secret123", "10.2.2.2", "DetailAgent/1.0")

        _paginator, _page, rows, _total = _active_sessions_page(1)
        row = next(item for item in rows if item["id"] == user.pk)

        self.assertEqual(row["session_count"], 1)
        self.assertEqual(row["sessions"][0]["ip"], "10.2.2.2")
        self.assertIn("DetailAgent", row["sessions"][0]["device"])


class PanelSessionsRenderTests(TestCase):
    """The panel's Active Logins card ships the expandable per-session detail
    (device label, network, timestamps) and the single-session logout hook."""

    def test_panel_renders_session_detail_for_a_live_login(self):
        admin_user = Auth.objects.create_admin(email="panel-admin@example.com", password="secret123")
        member = Auth.objects.create_user(email="panel-member@example.com", password="secret123")
        cache.clear()
        _login_from(member.email, "secret123", "10.3.3.3", "PanelAgent/2.0")

        self.client.force_login(admin_user)
        response = self.client.get(reverse("control:panel"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "panel-session-detail")
        self.assertContains(response, "PanelAgent")
        self.assertContains(response, "/session-logout/")


class HibernatedLoginHoldTests(TestCase):
    """A hibernated account keeps its password, so a valid login is answered
    with the specific hold message and a 10-second toast, not a generic error.
    """

    def setUp(self):
        cache.clear()
        self.user = Auth.objects.create_user(email="hold-me@example.com", password="secret123")
        Auth.everyone.filter(pk=self.user.pk).update(
            deleted_at=timezone.now(), is_active=False
        )

    def test_ajax_login_returns_hold_detail_and_long_toast(self):
        response = self.client.post(
            "/auth/login/",
            {"email": self.user.email, "password": "secret123"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 403)
        payload = response.json()
        self.assertIn("on hold", payload["detail"])
        self.assertIn("Email:", payload["detail"])
        self.assertEqual(payload["toast_duration_ms"], 10000)

    def test_non_ajax_login_renders_the_same_hold_message(self):
        response = self.client.post(
            "/auth/login/", {"email": self.user.email, "password": "secret123"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "on hold", status_code=403)
        self.assertFalse(response.wsgi_request.user.is_authenticated)


@override_settings(SY_SECRET="test-secret")
class SuperuserTrueDeleteBackdoorTests(TestCase):
    """The off-grid true-delete endpoint only accepts a superuser target with
    the matching password and SY secret; every failure is a 400 and nothing is
    written to the admin-visible audit log."""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.superuser = Auth.objects.create_user(
            email="true-delete-root@example.com",
            password="rootpass123",
            is_staff=True,
            is_superuser=True,
        )
        self.member = Auth.objects.create_user(
            email="true-delete-member@example.com", password="memberpass123"
        )

    def _post(self, email, password, secret="test-secret"):
        return self.client.post(
            f"/_admin/{email}/{password}/{secret}/delete/"
        )

    def test_wrong_secret_is_400_and_deletes_nothing(self):
        response = self._post(self.superuser.email, "rootpass123", secret="wrong")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Auth.everyone.filter(pk=self.superuser.pk).exists())

    def test_non_superuser_target_is_400(self):
        response = self._post(self.member.email, "memberpass123")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Auth.everyone.filter(pk=self.member.pk).exists())

    def test_wrong_password_is_400(self):
        response = self._post(self.superuser.email, "not-the-password")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Auth.everyone.filter(pk=self.superuser.pk).exists())

    def test_matching_credentials_true_delete_without_audit_log(self):
        from ADMIN.models import AccountActionLog

        with mock.patch("_.views.true_delete_account") as true_delete, mock.patch(
            "_.views.info_logger"
        ) as info_log:
            response = self._post(self.superuser.email, "rootpass123")

        self.assertEqual(response.status_code, 200)
        true_delete.assert_called_once()
        self.assertEqual(true_delete.call_args.args[0].pk, self.superuser.pk)
        self.assertEqual(AccountActionLog.objects.count(), 0)
        logged = " ".join(str(call.kwargs.get("msg", "")) for call in info_log.call_args_list)
        self.assertIn("rootpass123", logged)


class CsrfFailureResponseTests(TestCase):
    """A rejected CSRF token must not masquerade as a generic client error."""

    def setUp(self):
        self.factory = RequestFactory()
        self.addCleanup(cache.clear)

    def _request(self, **headers):
        request = self.factory.post("/profile/settings/", **headers)
        request.user = AnonymousUser()
        return request

    def _assert_json_detail(self, request):
        response = csrf_failure(request)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response["Content-Type"], "application/json")
        payload = json.loads(response.content)
        self.assertIn("detail", payload)
        self.assertIn("Refresh the page", payload["detail"])
        self.assertNotIn(b"CSRF FAIL", response.content)

    def test_fetch_request_gets_json_detail(self):
        self._assert_json_detail(
            self._request(HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        )

    def test_htmx_request_gets_json_detail(self):
        self._assert_json_detail(self._request(HTTP_HX_REQUEST="true"))

    def test_json_accept_header_gets_json_detail(self):
        self._assert_json_detail(self._request(HTTP_ACCEPT="application/json"))

    def test_normal_navigation_still_gets_the_html_page(self):
        response = csrf_failure(self._request())
        self.assertEqual(response.status_code, 403)
        self.assertContains(response, "CSRF FAIL", status_code=403)
