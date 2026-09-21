from django.test import TestCase

from AUTHENTICATION.models import Auth


class AuthReturnPathTests(TestCase):
    def test_guest_auth_links_preserve_the_current_local_path(self):
        response = self.client.get("/?q=admissions")

        self.assertContains(response, "/auth/login/?to=/%3Fq%3Dadmissions")
        self.assertContains(response, "/auth/register/?to=/%3Fq%3Dadmissions")
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
                "password": "secret123",
                "password_confirm": "secret123",
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
