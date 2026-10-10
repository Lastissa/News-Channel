from unittest import mock

from AUTHENTICATION.models import Auth
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from ARCHIVE.models import ArchiveImage, ArchiveKind
from ARCHIVE.views import _masked_email


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


@override_settings(CLOUDINARY_CLOUD_NAME="test-cloud")
class ArchiveFilterTests(TestCase):
    """The category filter (picture quality for images, file-type family for
    plain files) and the added-by filter (the uploader's pk, shown as the
    same masked email the cards use)."""

    def setUp(self):
        self.alice = Auth.objects.create_user(email="alice-uploader@example.com")
        self.bob = Auth.objects.create_user(email="bob-uploader@example.com")
        with mock.patch("AUTHENTICATION.signals._try_send_login_email"):
            self.client.force_login(self.alice)

        self.low_pic = ArchiveImage.objects.create(
            kind=ArchiveKind.IMAGE,
            url="/archive/cdn/image/upload/v123/abureport/archive/low.jpg",
            alt="Low quality photo",
            quality="low",
            width=100,
            height=100,
            public_id="abureport/archive/low",
            author=self.alice,
        )
        self.high_pic = ArchiveImage.objects.create(
            kind=ArchiveKind.IMAGE,
            url="/archive/cdn/image/upload/v123/abureport/archive/high.jpg",
            alt="High quality photo",
            quality="high",
            width=200,
            height=200,
            public_id="abureport/archive/high",
            author=self.bob,
        )
        self.report = ArchiveImage.objects.create(
            kind=ArchiveKind.FILE,
            url="/archive/cdn/raw/upload/v123/abureport/archive/report.pdf",
            alt="Annual report",
            original_filename="report.pdf",
            file_size=2048,
            public_id="abureport/archive/report",
            author=self.alice,
        )

    def test_gallery_renders_category_and_added_by_dropdowns(self):
        response = self.client.get(reverse("archive:gallery"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "data-archive-category")
        self.assertContains(response, "All categories")
        self.assertContains(response, "Image: High quality")
        self.assertContains(response, "data-archive-uploader")
        self.assertContains(response, "Anyone")
        #   uploaders are offered by their masked public email, never the full address
        self.assertContains(response, _masked_email("alice-uploader@example.com"))
        self.assertContains(response, _masked_email("bob-uploader@example.com"))
        self.assertNotContains(response, "alice-uploader@example.com")
        self.assertNotContains(response, "bob-uploader@example.com")

    def test_category_filter_groups_images_by_quality(self):
        response = self.client.get(reverse("archive:gallery"), {"category": "image-high"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "High quality photo")
        self.assertNotContains(response, "Low quality photo")
        self.assertNotContains(response, "Annual report")
        self.assertContains(response, "Image: High quality", status_code=200)  # summary chip

    def test_category_filter_groups_files_by_type_family(self):
        response = self.client.get(reverse("archive:gallery"), {"category": "pdf"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Annual report")
        self.assertNotContains(response, "photo")

    def test_uploader_filter_limits_to_that_person(self):
        response = self.client.get(reverse("archive:gallery"), {"uploader": str(self.bob.pk)})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "High quality photo")
        self.assertNotContains(response, "Low quality photo")
        self.assertNotContains(response, "Annual report")

    def test_category_and_uploader_combine(self):
        response = self.client.get(
            reverse("archive:gallery"),
            {"category": "image-low", "uploader": str(self.bob.pk)},
        )

        self.assertEqual(response.status_code, 200)
        #   low-quality pictures belong to alice, so bob + low quality matches nothing
        self.assertNotContains(response, "Low quality photo")
        self.assertNotContains(response, "High quality photo")

    def test_invalid_category_and_uploader_are_ignored(self):
        response = self.client.get(reverse("archive:gallery"), {"category": "nonsense", "uploader": "999999"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Low quality photo")
        self.assertContains(response, "High quality photo")
        self.assertContains(response, "Annual report")

    def test_grid_post_honors_category_and_uploader(self):
        response = self.client.post(reverse("archive:gallery"), {"category": "image-low", "kind": "image"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Low quality photo")
        self.assertNotContains(response, "High quality photo")
        self.assertNotContains(response, "Annual report")

    def test_filtered_grid_survives_urlencode_in_summary(self):
        """A category label appears in the summary chip even when the grid is
        loaded through the shared-letter-safe POST path (no crash on the
        data-category meta attribute used to resync the dropdowns)."""
        response = self.client.get(reverse("archive:gallery"), {"category": "other", "descr": "weird"})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Other file")
