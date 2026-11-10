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

from django.core.cache import cache
from django.urls import reverse

from Partner.landing import (
    add_advert_landing_author_header,
    strip_advert_landing_author_header,
)
from Partner.models import AdvertLandingPage
from SERVICE_INTERNAL.images import ImageUploadError


class AdvertLandingPageModelTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = Auth.objects.create_user(
            email="landing-admin@example.com", is_staff=True, is_admin=True
        )
        self.advert = AdvertImage.objects.create(
            author=self.admin,
            expiry_date=timezone.now() + timedelta(days=7),
            heading="Campus Hostel Rooms",
            body="Book a room & settle in.",
            image_url="https://cdn.example.com/ads/hostel.jpg",
            url="https://hostel.example.com",
        )

    def _landing(self, **kwargs):
        values = {
            "advert": self.advert,
            "author": self.admin,
            "html_public_id": "abureport/advert-landing/advert_1.html",
            "is_published": True,
        }
        values.update(kwargs)
        return AdvertLandingPage.objects.create(**values)

    def test_url_uses_the_heading_slug_with_the_id_last(self):
        landing = self._landing()

        self.assertEqual(
            landing.get_absolute_url(),
            f"/ads/campus-hostel-rooms-{self.advert.pk}/",
        )

    def test_metadata_falls_back_to_the_advert(self):
        landing = self._landing()

        self.assertEqual(landing.title_value, "Campus Hostel Rooms")
        self.assertEqual(landing.description_value, "Book a room & settle in.")
        self.assertEqual(landing.og_image_value, "https://cdn.example.com/ads/hostel.jpg")
        self.assertEqual(landing.robots, "noindex, nofollow")

    def test_only_published_pages_with_a_trusted_author_are_deliverable(self):
        landing = self._landing()
        self.assertTrue(landing.is_deliverable)

        landing.is_published = False
        landing.save(update_fields=["is_published"])
        self.assertFalse(landing.is_deliverable)

        landing.is_published = True
        landing.author.is_admin = False
        landing.author.save(update_fields=["is_admin"])
        self.assertFalse(landing.is_deliverable)

        self.admin.is_admin = True
        self.admin.is_active = False
        self.admin.save(update_fields=["is_admin", "is_active"])
        self.assertFalse(landing.is_deliverable)

    def test_author_header_is_a_traceable_comment_that_can_be_stripped(self):
        html = add_advert_landing_author_header("<!doctype html><html></html>", self.advert, self.admin)

        self.assertTrue(html.startswith("<!-- ABUREPORT-AD-LANDING"))
        self.assertIn(f"author_id={self.admin.pk}", html)
        self.assertIn(f"advert_id={self.advert.pk}", html)
        self.assertNotIn(self.admin.email, html)
        self.assertEqual(
            strip_advert_landing_author_header(html),
            "<!doctype html><html></html>",
        )


class AdvertLandingViewTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = Auth.objects.create_user(
            email="landing-view-admin@example.com", is_staff=True, is_admin=True
        )
        self.advert = AdvertImage.objects.create(
            author=self.admin,
            expiry_date=timezone.now() + timedelta(days=7),
            heading="Campus Hostel Rooms",
            body="Book a room & settle in.",
            image_url="https://cdn.example.com/ads/hostel.jpg",
            url="https://hostel.example.com/?from=ad",
        )
        self.landing = AdvertLandingPage.objects.create(
            advert=self.advert,
            author=self.admin,
            html_public_id="abureport/advert-landing/advert_1.html",
            is_published=True,
        )
        self.document = """<!-- ABUREPORT-AD-LANDING author_id=1 -->
<!doctype html><html><head>
<title>{{page_title}}</title>
<meta name="description" content="{{meta_description}}">
<meta name="robots" content="{{robots}}">
<link rel="canonical" href="{{canonical_url}}">
<meta property="og:image" content="{{og_image}}">
</head><body>
<h1>{{ad_heading}}</h1><p>{{ad_body}}</p><a href="{{ad_url}}">{{landing_url}}</a>
</body></html>"""

    def test_view_renders_the_document_with_tokens_and_no_site_chrome(self):
        with mock.patch("Partner.views.fetch_advert_landing_html", return_value=self.document):
            response = self.client.get(self.landing.get_absolute_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/html; charset=utf-8")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        html = response.content.decode()
        self.assertIn("<title>Campus Hostel Rooms</title>", html)
        self.assertIn("Book a room &amp; settle in.", html)
        self.assertIn('content="https://cdn.example.com/ads/hostel.jpg"', html)
        self.assertIn(f'href="http://testserver/ads/campus-hostel-rooms-{self.advert.pk}/"', html)
        self.assertIn('content="noindex, nofollow"', html)
        self.assertNotIn("site-header", html)
        self.assertNotIn("panel-nav", html)

    def test_old_heading_url_301s_to_the_current_slug_and_keeps_the_query(self):
        self.advert.heading = "New Hostel Heading"
        self.advert.save(update_fields=["heading"])

        response = self.client.get(f"/ads/old-heading-{self.advert.pk}/?utm_source=test")

        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response["Location"],
            f"/ads/new-hostel-heading-{self.advert.pk}/?utm_source=test",
        )

    def test_id_only_url_301s_to_the_canonical_url(self):
        response = self.client.get(f"/ads/{self.advert.pk}/")

        self.assertEqual(response.status_code, 301)
        self.assertEqual(
            response["Location"],
            f"/ads/campus-hostel-rooms-{self.advert.pk}/",
        )

    def test_unpublished_pages_and_untrusted_authors_never_run_the_document(self):
        cases = [
            ("unpublished", {"is_published": False}, None),
            ("inactive author", {"is_published": True}, "inactive"),
            ("demoted author", {"is_published": True}, "demoted"),
            ("missing author", {"is_published": True}, "missing"),
        ]
        for label, landing_values, author_state in cases:
            with self.subTest(label=label):
                self.landing.is_published = landing_values["is_published"]
                self.landing.author = self.admin
                self.landing.save(update_fields=["is_published", "author"])
                self.admin.is_active = True
                self.admin.is_admin = True
                self.admin.save(update_fields=["is_active", "is_admin"])
                if author_state == "inactive":
                    self.admin.is_active = False
                    self.admin.save(update_fields=["is_active"])
                elif author_state == "demoted":
                    self.admin.is_admin = False
                    self.admin.save(update_fields=["is_admin"])
                elif author_state == "missing":
                    self.landing.author = None
                    self.landing.save(update_fields=["author"])
                with mock.patch("Partner.views.fetch_advert_landing_html") as fetch:
                    response = self.client.get(self.landing.get_absolute_url())
                self.assertEqual(response.status_code, 404)
                fetch.assert_not_called()

    def test_cloudinary_failure_returns_plain_502_with_no_site_page(self):
        with mock.patch(
            "Partner.views.fetch_advert_landing_html",
            side_effect=ImageUploadError("The landing page file no longer exists."),
        ):
            response = self.client.get(self.landing.get_absolute_url())

        self.assertEqual(response.status_code, 502)
        self.assertEqual(response["Content-Type"], "text/plain; charset=utf-8")
        self.assertNotIn(b"site-header", response.content)


class AdvertLandingCloudinaryHelperTests(TestCase):
    def test_upload_overwrites_the_deterministic_raw_html_asset(self):
        from SERVICE_INTERNAL.images import upload_advert_landing_html

        with mock.patch(
            "SERVICE_INTERNAL.images.cloudinary.uploader.upload",
            return_value={
                "public_id": "abureport/advert-landing/advert_9.html",
                "bytes": 234,
                "secure_url": "https://res.cloudinary.com/test/raw/authenticated/x.html",
            },
        ) as upload:
            result = upload_advert_landing_html("<html>ok</html>", 9)

        self.assertEqual(result["public_id"], "abureport/advert-landing/advert_9.html")
        self.assertEqual(result["bytes"], 234)
        kwargs = upload.call_args.kwargs
        self.assertEqual(kwargs["public_id"], "abureport/advert-landing/advert_9")
        self.assertEqual(kwargs["format"], "html")
        self.assertEqual(kwargs["resource_type"], "raw")
        self.assertEqual(kwargs["type"], "authenticated")
        self.assertTrue(kwargs["overwrite"])
        self.assertTrue(kwargs["invalidate"])

    def test_fetch_uses_a_signed_authenticated_url_without_appending_format(self):
        from SERVICE_INTERNAL.images import fetch_advert_landing_html

        with mock.patch(
            "SERVICE_INTERNAL.images.cloudinary.utils.cloudinary_url",
            return_value=("https://res.cloudinary.com/test/raw/authenticated/x.html", {}),
        ) as cloudinary_url, mock.patch(
            "SERVICE_INTERNAL.images.requests.get"
        ) as get:
            get.return_value.status_code = 200
            get.return_value.content = b"<html>ok</html>"
            result = fetch_advert_landing_html("abureport/advert-landing/advert_9.html")

        self.assertEqual(result, "<html>ok</html>")
        cloudinary_url.assert_called_once_with(
            "abureport/advert-landing/advert_9.html",
            resource_type="raw",
            type="authenticated",
            sign_url=True,
            secure=True,
        )

    def test_destroy_removes_the_returned_public_id(self):
        from SERVICE_INTERNAL.images import destroy_advert_landing_html

        with mock.patch(
            "SERVICE_INTERNAL.images.cloudinary.uploader.destroy",
            return_value={"result": "ok"},
        ) as destroy:
            result = destroy_advert_landing_html("abureport/advert-landing/advert_9.html")

        self.assertTrue(result)
        destroy.assert_called_once_with(
            "abureport/advert-landing/advert_9.html",
            resource_type="raw",
            type="authenticated",
            invalidate=True,
        )


class AdvertLandingSignalTests(TestCase):
    def test_deleting_a_landing_page_destroys_its_cloudinary_html(self):
        admin = Auth.objects.create_user(
            email="signal-admin@example.com", is_staff=True, is_admin=True
        )
        advert = AdvertImage.objects.create(
            author=admin,
            expiry_date=timezone.now() + timedelta(days=7),
            heading="Signal advert",
            image_url="https://cdn.example.com/ads/signal.jpg",
            url="https://example.com",
        )
        landing = AdvertLandingPage.objects.create(
            advert=advert,
            author=admin,
            html_public_id="abureport/advert-landing/advert_signal.html",
            is_published=True,
        )

        with mock.patch(
            "SERVICE_INTERNAL.images.destroy_advert_landing_html", return_value=True
        ) as destroy:
            landing.delete()

        destroy.assert_called_once_with("abureport/advert-landing/advert_signal.html")


class PanelAdvertLandingTests(TestCase):
    def setUp(self):
        cache.clear()
        self.admin = Auth.objects.create_user(
            email="panel-landing-admin@example.com", is_staff=True, is_admin=True
        )
        self.other = Auth.objects.create_user(email="panel-other@example.com")
        self.advert = AdvertImage.objects.create(
            author=self.admin,
            expiry_date=timezone.now() + timedelta(days=7),
            heading="Panel advert",
            body="Panel body",
            image_url="https://cdn.example.com/ads/panel.jpg",
            url="https://example.com/panel",
        )
        self.client.force_login(self.admin)

    def _landing(self, **kwargs):
        values = {
            "advert": self.advert,
            "author": self.admin,
            "html_public_id": "abureport/advert-landing/advert_panel.html",
            "is_published": True,
        }
        values.update(kwargs)
        return AdvertLandingPage.objects.create(**values)

    def test_save_uploads_and_overwrites_the_page_with_metadata(self):
        url = reverse("control:panel_image_advert_landing", args=[self.advert.pk])
        with mock.patch(
            "ADMIN.views.upload_advert_landing_html",
            return_value={
                "public_id": "abureport/advert-landing/advert_panel.html",
                "bytes": 123,
            },
        ) as upload:
            response = self.client.post(
                url,
                {
                    "html": "<!doctype html><html><body>{{ad_heading}}</body></html>",
                    "meta_title": "Panel landing title",
                    "meta_description": "Panel landing description",
                    "og_image": "https://cdn.example.com/og.jpg",
                    "robots": "index, follow",
                    "is_published": "1",
                },
            )

        self.assertEqual(response.status_code, 200)
        landing = AdvertLandingPage.objects.get(advert=self.advert)
        self.assertEqual(landing.meta_title, "Panel landing title")
        self.assertEqual(landing.robots, "index, follow")
        self.assertTrue(landing.is_published)
        self.assertEqual(landing.author, self.admin)
        self.assertEqual(landing.html_public_id, "abureport/advert-landing/advert_panel.html")
        self.assertEqual(upload.call_count, 1)
        stored_html = upload.call_args.args[0]
        self.assertTrue(stored_html.startswith("<!-- ABUREPORT-AD-LANDING"))
        self.assertIn("{{ad_heading}}", stored_html)

    def test_get_strips_the_internal_author_header(self):
        self._landing()
        with mock.patch(
            "ADMIN.views.fetch_advert_landing_html",
            return_value="<!-- ABUREPORT-AD-LANDING author_id=1 -->\n<html>saved</html>",
        ):
            response = self.client.get(
                reverse("control:panel_image_advert_landing", args=[self.advert.pk])
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["html"], "<html>saved</html>")
        self.assertEqual(payload["item"]["landing_status"], "live")

    def test_preview_renders_unsaved_html_and_metadata(self):
        response = self.client.post(
            reverse("control:panel_image_advert_landing_preview", args=[self.advert.pk]),
            {
                "html": "<html><head><title>{{meta_title}}</title></head><body>{{ad_body}}</body></html>",
                "meta_title": "Preview title",
                "meta_description": "",
                "og_image": "",
                "robots": "noindex, follow",
                "is_published": "0",
            },
        )

        self.assertEqual(response.status_code, 200)
        html = response.json()["html"]
        self.assertIn("<title>Preview title</title>", html)
        self.assertIn("Panel body", html)

    def test_delete_removes_the_row_and_cloudinary_asset(self):
        self._landing()
        with mock.patch(
            "SERVICE_INTERNAL.images.destroy_advert_landing_html", return_value=True
        ) as destroy:
            response = self.client.post(
                reverse("control:panel_image_advert_landing_delete", args=[self.advert.pk])
            )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(AdvertLandingPage.objects.filter(advert=self.advert).exists())
        destroy.assert_called_once_with("abureport/advert-landing/advert_panel.html")

    def test_non_admin_cannot_read_or_write_the_editor(self):
        self.client.force_login(self.other)
        read = self.client.get(
            reverse("control:panel_image_advert_landing", args=[self.advert.pk])
        )
        write = self.client.post(
            reverse("control:panel_image_advert_landing", args=[self.advert.pk]),
            {"html": "<html>nope</html>", "robots": "noindex, nofollow"},
        )

        self.assertEqual(read.status_code, 403)
        self.assertEqual(write.status_code, 403)
