from unittest import mock

from AUTHENTICATION.models import Auth
from django.test import TestCase
from django.urls import reverse


class ArchiveIframeTests(TestCase):
    def test_gallery_allows_same_origin_iframe_embedding(self):
        user = Auth.objects.create_user(email="archive-frame@example.com")
        with mock.patch("AUTHENTICATION.signals._try_send_login_email"):
            self.client.force_login(user)

        response = self.client.get(reverse("archive:gallery"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-Frame-Options"), "SAMEORIGIN")
