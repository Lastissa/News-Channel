from unittest import mock

from datetime import timedelta

from django.contrib import admin
from django.contrib.sessions.models import Session
from django.contrib.sessions.backends.db import SessionStore
from django.core.cache import cache
from django.test import Client, RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from AUTHENTICATION.models import Auth, KnownDevice, UserSession
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
