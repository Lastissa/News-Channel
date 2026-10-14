from datetime import timedelta
from unittest import mock

from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.utils import timezone

from AUTHENTICATION.models import Auth
from Partner.models import AdvertImage


class AdvertImageAdminDeleteReleasesAssetTests(TestCase):
    """Deleting an advert from the hidden Django admin (_admin/) releases its
    Cloudinary picture, so the backdoor cannot orphan it (PANEL already does
    this in ADMIN.views.PanelImageAdvertDeleteView)."""

    def setUp(self):
        self.author = Auth.objects.create_user(email="admin-advert@example.com")
        self.model_admin = admin.site._registry[AdvertImage]
        self.request = RequestFactory().get("/_admin/")

    def _make_advert(self, public_id, heading="Admin advert"):
        return AdvertImage.objects.create(
            author=self.author,
            expiry_date=timezone.now() + timedelta(days=7),
            image_url="https://res.cloudinary.com/test/image/upload/v1/abureport/adverts/banner.jpg",
            image_public_id=public_id,
            url="https://example.com",
            heading=heading,
        )

    def test_delete_model_releases_the_picture(self):
        advert = self._make_advert("abureport/adverts/admin-banner")
        advert_pk = advert.pk
        with mock.patch("Partner.admin.destroy_archive_asset", return_value=True) as destroy_asset:
            self.model_admin.delete_model(self.request, advert)
        self.assertFalse(AdvertImage.objects.filter(pk=advert_pk).exists())
        destroy_asset.assert_called_once_with("abureport/adverts/admin-banner")

    def test_delete_queryset_releases_each_picture(self):
        self._make_advert("abureport/adverts/one")
        self._make_advert("abureport/adverts/two", heading="Second advert")
        with mock.patch("Partner.admin.destroy_archive_asset", return_value=True) as destroy_asset:
            self.model_admin.delete_queryset(self.request, AdvertImage.objects.all())
        self.assertEqual(destroy_asset.call_count, 2)
