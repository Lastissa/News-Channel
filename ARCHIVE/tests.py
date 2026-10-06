from unittest import mock

from AUTHENTICATION.models import Auth
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from ARCHIVE.models import ArchiveImage, ArchiveKind


class ArchiveIframeTests(TestCase):
    def test_gallery_allows_same_origin_iframe_embedding(self):
        user = Auth.objects.create_user(email="archive-frame@example.com")
        with mock.patch("AUTHENTICATION.signals._try_send_login_email"):
            self.client.force_login(user)

        response = self.client.get(reverse("archive:gallery"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("X-Frame-Options"), "SAMEORIGIN")


@override_settings(CLOUDINARY_CLOUD_NAME="test-cloud")
class ArchiveAssetManagementTests(TestCase):
    def setUp(self):
        self.user = Auth.objects.create_user(email="archive-assets@example.com")
        with mock.patch("AUTHENTICATION.signals._try_send_login_email"):
            self.client.force_login(self.user)

    def test_image_upload_persists_project_proxy_url(self):
        upload_result = {
            "secure_url": "https://res.cloudinary.com/test-cloud/image/upload/v123/abureport/archive/photo.jpg",
            "public_id": "abureport/archive/photo",
            "resource_type": "image",
            "width": 640,
            "height": 480,
        }
        with (
            mock.patch("ARCHIVE.views.is_rate_limited", return_value=(0, False)),
            mock.patch("ARCHIVE.views.upload_archive_image", return_value=upload_result),
        ):
            response = self.client.post(
                reverse("archive:upload"),
                {
                    "alt": "A sample photo",
                    "quality": "medium",
                    "width": "800",
                    "height": "600",
                    "upload_file": SimpleUploadedFile("photo.jpg", b"image", content_type="image/jpeg"),
                },
            )

        self.assertEqual(response.status_code, 201)
        item = ArchiveImage.objects.get()
        self.assertEqual(
            item.url,
            "/archive/cdn/image/upload/v123/abureport/archive/photo.jpg",
        )
        self.assertNotIn("res.cloudinary.com", item.url)

    def test_description_and_quality_can_be_updated_without_reupload(self):
        item = ArchiveImage.objects.create(
            kind=ArchiveKind.IMAGE,
            url="/archive/cdn/image/upload/v123/abureport/archive/photo.jpg",
            alt="Before",
            quality="medium",
            width=640,
            height=480,
            public_id="abureport/archive/photo",
            author=self.user,
        )
        with mock.patch(
            "ARCHIVE.views.archive_image_delivery_url",
            return_value="https://res.cloudinary.com/test-cloud/image/upload/q_auto:best/v123/abureport/archive/photo.jpg",
        ) as delivery_url:
            response = self.client.post(
                reverse("archive:item_edit", args=[item.pk]),
                {"alt": "After", "quality": "high"},
            )

        self.assertEqual(response.status_code, 200)
        item.refresh_from_db()
        self.assertEqual(item.alt, "After")
        self.assertEqual(item.quality, "high")
        self.assertEqual(item.url, "/archive/cdn/image/upload/q_auto:best/v123/abureport/archive/photo.jpg")
        delivery_url.assert_called_once_with(
            item.public_id,
            "high",
            width=640,
            height=480,
        )

    def test_delete_keeps_database_row_when_cloudinary_purge_fails(self):
        item = ArchiveImage.objects.create(
            kind=ArchiveKind.IMAGE,
            url="/archive/cdn/image/upload/v123/abureport/archive/photo.jpg",
            alt="A sample photo",
            public_id="abureport/archive/photo",
            author=self.user,
        )
        with mock.patch("ARCHIVE.views.destroy_archive_asset", return_value=False) as destroy_asset:
            response = self.client.post(reverse("archive:item_delete", args=[item.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(ArchiveImage.objects.filter(pk=item.pk).exists())
        self.assertContains(response, "archive item was kept")
        destroy_asset.assert_called_once_with("abureport/archive/photo", "image")

    def test_delete_removes_row_only_after_cloudinary_purge_succeeds(self):
        item = ArchiveImage.objects.create(
            kind=ArchiveKind.IMAGE,
            url="/archive/cdn/image/upload/v123/abureport/archive/legacy-photo.jpg",
            alt="A legacy photo",
            author=self.user,
        )
        with mock.patch("ARCHIVE.views.destroy_archive_asset", return_value=True) as destroy_asset:
            response = self.client.post(reverse("archive:item_delete", args=[item.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ArchiveImage.objects.filter(pk=item.pk).exists())
        destroy_asset.assert_called_once_with("abureport/archive/legacy-photo", "image")
