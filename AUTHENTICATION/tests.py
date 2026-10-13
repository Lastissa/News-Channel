from django.test import TestCase
from django.urls import reverse

from AUTHENTICATION.models import Auth


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
