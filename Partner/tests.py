from datetime import datetime, time, timedelta
from unittest import mock

from django.contrib import admin
from django.test import RequestFactory, TestCase
from django.utils import timezone

from AUTHENTICATION.models import Auth
from Partner.advert_analytics import build_advert_analytics
from Partner.models import AdvertEvent, AdvertImage, AdvertLead, AdvertPage, AdvertReference


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
from Partner.tracking import append_utm_source
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
                #   The untrusted document is never fetched, but the advert
                #   still gets its built-in page with a 200.
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"Learn more", response.content)
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


class AdvertReferenceTests(TestCase):
    """The permanent 16-character key and its independent paid period."""

    def setUp(self):
        self.owner = Auth.objects.create_user(email="grace.stores@example.com")
        self.admin = Auth.objects.create_user(
            email="reference-admin@example.com", is_staff=True, is_admin=True
        )

    def _advert(self, heading="Reference advert"):
        return AdvertImage.objects.create(
            author=self.admin,
            expiry_date=timezone.now() + timedelta(days=7),
            heading=heading,
            image_url="https://cdn.example.com/ads/reference.jpg",
            url="https://example.com/reference",
        )

    def _reference(self, advert=None, **kwargs):
        values = {
            "user": self.owner,
            "plan": "regular",
            "business_name": "Grace Stores",
        }
        values.update(kwargs)
        return AdvertReference.objects.create(advert=advert or self._advert(), **values)

    def test_reference_is_16_chars_and_starts_with_five_email_chars(self):
        row = self._reference()

        self.assertEqual(len(row.reference), 16)
        self.assertTrue(row.reference.startswith("GRACE"))
        self.assertRegex(row.reference, r"^GRACE\d{6}[A-Z2-9]{5}$")
        self.assertEqual(row.email_used, self.owner.email)

    def test_same_email_gets_a_new_reference_for_a_second_advert(self):
        first = self._reference()
        second = self._reference(advert=self._advert("Second advert"))

        self.assertNotEqual(first.reference, second.reference)
        self.assertEqual(AdvertReference.objects.filter(user=self.owner).count(), 2)

    def test_public_target_opens_landing_first_and_paid_subdomain_wins(self):
        advert = self._advert()
        row = self._reference(advert=advert, public_url="https://advance.example.com/page")
        #   Regular clicks open the built-in /ads/ page. The "Learn more" link
        #   on that page carries the public URL (tested in the renderer tests).
        self.assertEqual(row.public_target, f"/ads/reference-advert-{advert.pk}/")

        #   Paid advert: its own subdomain is the entry point.
        row.plan = "advance"
        row.subdomain = "graceads"
        row.save(update_fields=["plan", "subdomain"])
        self.assertTrue(row.public_target)
        self.assertEqual(row.public_target, row.public_page_url)

        #   A legacy paid advert with no subdomain may still open an external
        #   link: the ads desk URL first, then the advert's saved link.
        row.subdomain = ""
        row.save(update_fields=["subdomain"])
        self.assertEqual(row.public_target, "https://advance.example.com/page")
        row.public_url = ""
        row.save(update_fields=["public_url"])
        self.assertEqual(row.public_target, "https://example.com/reference")

        #   Paid with neither subdomain nor destination is a setup error.
        row.advert.url = ""
        row.advert.save(update_fields=["url"])
        row.refresh_from_db()
        self.assertEqual(row.public_target, "")

    def test_is_live_respects_pause_and_expiry(self):
        row = self._reference()
        self.assertTrue(row.is_live)

        row.status = AdvertReference.STATUS_PAUSED
        row.save(update_fields=["status"])
        self.assertFalse(row.is_live)

        row.status = AdvertReference.STATUS_ACTIVE
        row.expires_at = timezone.now() - timedelta(minutes=1)
        row.save(update_fields=["status", "expires_at"])
        self.assertFalse(row.is_live)
        self.assertTrue(row.is_expired)

    def test_append_utm_source_only_touches_http_links_and_keeps_an_existing_source(self):
        self.assertEqual(
            append_utm_source("https://example.com/page"),
            "https://example.com/page?utm_source=abureport",
        )
        self.assertEqual(
            append_utm_source("https://example.com/page?utm_source=partner"),
            "https://example.com/page?utm_source=partner",
        )
        self.assertEqual(append_utm_source("mailto:ads@example.com"), "mailto:ads@example.com")


class AdvertTrackingTests(TestCase):
    """Public tracking stays honest: no raw IPs, no bot hits, deduped views."""

    def setUp(self):
        self.owner = Auth.objects.create_user(email="tracker@example.com")
        self.admin = Auth.objects.create_user(
            email="tracking-admin@example.com", is_staff=True, is_admin=True
        )
        self.advert = AdvertImage.objects.create(
            author=self.admin,
            expiry_date=timezone.now() + timedelta(days=7),
            heading="Tracked advert",
            image_url="https://cdn.example.com/ads/tracked.jpg",
            url="https://example.com/tracked",
        )
        self.reference = AdvertReference.objects.create(
            user=self.owner,
            plan="pro",
            business_name="Tracked Business",
            advert=self.advert,
        )
        self.client.defaults["HTTP_USER_AGENT"] = "Mozilla/5.0 (TestBrowser)"
        self.client.defaults["HTTP_REFERER"] = "http://testserver/"

    def test_view_pixel_records_one_view_and_returns_a_gif(self):
        response = self.client.get(
            reverse("partner:advert_view", args=[self.reference.reference])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/gif")
        event = AdvertEvent.objects.get()
        self.assertEqual(event.event_type, AdvertEvent.EVENT_VIEW)
        self.assertEqual(event.source, AdvertEvent.SOURCE_ABUREPORT)
        self.assertTrue(event.ip_hash)
        self.assertNotEqual(event.ip_hash, "127.0.0.1")

    def test_repeated_view_inside_three_seconds_is_not_counted_twice(self):
        url = reverse("partner:advert_view", args=[self.reference.reference])
        self.client.get(url)
        self.client.get(url)

        self.assertEqual(AdvertEvent.objects.filter(event_type=AdvertEvent.EVENT_VIEW).count(), 1)

    def test_dedupe_is_three_seconds_per_ip_and_follows_cloudflare_ip(self):
        url = reverse("partner:advert_view", args=[self.reference.reference])
        count = lambda: AdvertEvent.objects.filter(event_type=AdvertEvent.EVENT_VIEW).count()

        self.client.get(url, HTTP_CF_CONNECTING_IP="102.89.1.1")
        self.client.get(url, HTTP_CF_CONNECTING_IP="102.89.1.1")
        self.assertEqual(count(), 1)

        #   Another device on another IP is never suppressed, even with the
        #   same proxy address in REMOTE_ADDR.
        self.client.get(url, HTTP_CF_CONNECTING_IP="102.89.2.2")
        self.assertEqual(count(), 2)

        #   After the window the same IP counts again.
        AdvertEvent.objects.update(created_at=timezone.now() - timedelta(seconds=4))
        self.client.get(url, HTTP_CF_CONNECTING_IP="102.89.1.1")
        self.assertEqual(count(), 3)

    def test_click_redirects_with_utm_source_and_records_the_click(self):
        response = self.client.get(
            reverse("partner:advert_click", args=[self.reference.reference])
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            "https://example.com/tracked?utm_source=abureport",
        )
        event = AdvertEvent.objects.get()
        self.assertEqual(event.event_type, AdvertEvent.EVENT_CLICK)
        self.assertEqual(event.source, AdvertEvent.SOURCE_ABUREPORT)
        self.assertEqual(event.target_url, response.url)

        #   A double click inside the three-second window still redirects, but
        #   it must not inflate the advertiser's click count.
        again = self.client.get(
            reverse("partner:advert_click", args=[self.reference.reference])
        )
        self.assertEqual(again.status_code, 302)
        self.assertEqual(AdvertEvent.objects.filter(event_type=AdvertEvent.EVENT_CLICK).count(), 1)

    def test_external_referrer_is_classified_as_external(self):
        self.client.defaults["HTTP_REFERER"] = "https://news.example.net/story"

        self.client.get(reverse("partner:advert_click", args=[self.reference.reference]))

        self.assertEqual(AdvertEvent.objects.get().source, AdvertEvent.SOURCE_EXTERNAL)

    def test_paused_reference_stops_clicks_and_landing_pages(self):
        self.reference.status = AdvertReference.STATUS_PAUSED
        self.reference.save(update_fields=["status"])

        click = self.client.get(
            reverse("partner:advert_click", args=[self.reference.reference])
        )
        self.assertRedirects(click, reverse("home:promote"), fetch_redirect_response=False)
        self.assertEqual(AdvertEvent.objects.count(), 0)

        AdvertLandingPage.objects.create(
            advert=self.advert,
            author=self.admin,
            html_public_id="abureport/advert-landing/tracked.html",
            is_published=True,
        )
        landing = self.client.get(f"/ads/tracked-advert-{self.advert.pk}/")
        self.assertEqual(landing.status_code, 404)

    def test_bot_user_agent_is_not_counted(self):
        self.client.defaults["HTTP_USER_AGENT"] = "Googlebot/2.1"

        response = self.client.get(
            reverse("partner:advert_view", args=[self.reference.reference])
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(AdvertEvent.objects.count(), 0)


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


class AdvertPlanServingTests(TestCase):
    """The plan on the reference decides, on every request, what may show."""

    def setUp(self):
        cache.clear()
        self.admin = Auth.objects.create_user(email="plan-admin@example.com", is_staff=True, is_admin=True)
        self.owner = Auth.objects.create_user(email="plan-owner@example.com")
        self.advert = AdvertImage.objects.create(
            author=self.admin,
            expiry_date=timezone.now() + timedelta(days=7),
            heading="Plan Shop",
            body="Shop text",
            image_url="https://cdn.example.com/ads/shop.jpg",
        )
        AdvertLandingPage.objects.create(
            advert=self.advert, author=self.admin, html_public_id="x/advert_1.html", is_published=True
        )
        AdvertPage.objects.create(
            advert=self.advert, path="about", author=self.admin, html_public_id="x/advert_1_p_about.html"
        )
        self.reference = AdvertReference.objects.create(
            user=self.owner, plan=AdvertLead.PLAN_PRO, business_name="Plan Shop", advert=self.advert
        )
        self.document = "<!doctype html><title>{{page_title}}</title><p>{{canonical_url}}</p>"

    def _get(self, url):
        with mock.patch("Partner.views.fetch_advert_landing_html", return_value=self.document):
            return self.client.get(url)

    def _set_plan(self, plan):
        self.reference.plan = plan
        self.reference.save()

    def test_landing_page_shows_for_pro_and_built_in_page_for_regular(self):
        url = f"/ads/plan-shop-{self.advert.pk}/"
        paid = self._get(url)
        self.assertEqual(paid.status_code, 200)
        self.assertIn(b"<!doctype html><title>Plan Shop</title>", paid.content)

        #   Regular cannot run the custom document; it still gets the built-in
        #   responsive page instead of a 404.
        self._set_plan(AdvertLead.PLAN_REGULAR)
        regular = self._get(url)
        self.assertEqual(regular.status_code, 200)
        self.assertNotIn(b"<!doctype html><title>Plan Shop</title>", regular.content)
        self.assertIn(b"Learn more", regular.content)

    def test_extra_pages_are_for_advance_only(self):
        url = f"/ads/plan-shop-{self.advert.pk}/about/"
        self.assertEqual(self._get(url).status_code, 404)

        self._set_plan(AdvertLead.PLAN_ADVANCE)
        response = self._get(url)
        self.assertEqual(response.status_code, 200)
        self.assertIn(f"http://testserver{url}", response.content.decode())

        #   A downgrade stops the page straight away.
        self._set_plan(AdvertLead.PLAN_PRO)
        self.assertEqual(self._get(url).status_code, 404)

    def test_extra_page_needs_to_be_published_and_its_writer_still_an_admin(self):
        self._set_plan(AdvertLead.PLAN_ADVANCE)
        url = f"/ads/plan-shop-{self.advert.pk}/about/"
        AdvertPage.objects.update(is_published=False)
        self.assertEqual(self._get(url).status_code, 404)
        AdvertPage.objects.update(is_published=True)
        Auth.objects.filter(pk=self.admin.pk).update(is_admin=False)
        self.assertEqual(self._get(url).status_code, 404)

    def test_a_paused_reference_stops_its_extra_pages(self):
        self._set_plan(AdvertLead.PLAN_ADVANCE)
        self.reference.status = AdvertReference.STATUS_PAUSED
        self.reference.save()
        self.assertEqual(self._get(f"/ads/plan-shop-{self.advert.pk}/about/").status_code, 404)


class DefaultAdvertLandingTests(TestCase):
    """Every live advert has a page, even before a custom HTML file exists."""

    def setUp(self):
        cache.clear()
        self.admin = Auth.objects.create_user(
            email="default-landing-admin@example.com", is_staff=True, is_admin=True
        )
        self.owner = Auth.objects.create_user(email="default-landing-owner@example.com")
        self.advert = AdvertImage.objects.create(
            author=self.admin,
            expiry_date=timezone.now() + timedelta(days=7),
            heading="Sunday Deals",
            body="Fresh deals every week.",
            image_url="https://cdn.example.com/ads/sunday.jpg",
            url="https://shop.example.com/whatsapp",
        )

    def _reference(self, plan="regular", **kwargs):
        return AdvertReference.objects.create(
            user=self.owner,
            plan=plan,
            business_name="Sunday Deals",
            advert=self.advert,
            **kwargs,
        )

    def test_regular_without_html_gets_built_in_page_and_public_url_wins_learn_more(self):
        self._reference(public_url="https://shop.example.com/campaign")
        url = f"/ads/sunday-deals-{self.advert.pk}/"

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("Sunday Deals", html)
        self.assertIn("Fresh deals every week.", html)
        self.assertIn("https://cdn.example.com/ads/sunday.jpg", html)
        self.assertIn("Learn more", html)
        #   Public page URL outranks the advert link, with our utm marker.
        self.assertIn(
            'href="https://shop.example.com/campaign?utm_source=abureport"', html
        )
        self.assertNotIn("being build", html)

    def test_learn_more_falls_back_to_the_advert_link(self):
        self._reference()
        response = self.client.get(f"/ads/sunday-deals-{self.advert.pk}/")
        self.assertIn(
            'href="https://shop.example.com/whatsapp?utm_source=abureport"',
            response.content.decode(),
        )

    def test_paid_subdomain_without_html_is_a_200_building_page(self):
        self._reference(plan="advance", subdomain="graceads")
        response = self.client.get("/", HTTP_HOST="graceads.localhost")
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("advertisement is being build, check back soon..", html)
        self.assertIn("Learn more", html)
        self.assertIn("Sunday Deals", html)
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")

    def test_paid_subdomain_with_custom_html_still_uses_the_document(self):
        reference = self._reference(plan="pro", subdomain="graceads")
        AdvertLandingPage.objects.create(
            advert=self.advert,
            author=self.admin,
            html_public_id="abureport/advert-landing/sunday.html",
            is_published=True,
        )
        document = "<!doctype html><title>{{page_title}}</title>"
        with mock.patch("Partner.views.fetch_advert_landing_html", return_value=document):
            response = self.client.get("/", HTTP_HOST="graceads.localhost")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"<title>Sunday Deals</title>", response.content)
        self.assertNotIn(b"being build", response.content)
        self.assertTrue(reference.is_live)

    def test_generic_path_redirects_a_paid_advert_to_its_subdomain_even_without_html(self):
        self._reference(plan="pro", subdomain="graceads")
        response = self.client.get(f"/ads/sunday-deals-{self.advert.pk}/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("graceads.localhost", response["Location"])

    def test_misconfigured_paid_click_returns_json_but_direct_pages_do_not(self):
        #   No subdomain, no public URL and no advert link: a legacy setup error.
        self.advert.url = ""
        self.advert.save(update_fields=["url"])
        self._reference(plan="pro")
        row = AdvertReference.objects.get(business_name="Sunday Deals")
        url = reverse("partner:advert_click", args=[row.reference])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "this ads was not set properly"})

        check = self.client.get(url, {"check": "1"})
        self.assertEqual(check.status_code, 400)
        self.assertEqual(check.json(), {"detail": "this ads was not set properly"})

        #   Direct opens are HTML, never JSON.
        for direct in (f"/ads/sunday-deals-{self.advert.pk}/",):
            direct_response = self.client.get(direct)
            self.assertEqual(direct_response.status_code, 200)
            self.assertEqual(direct_response["Content-Type"], "text/html; charset=utf-8")
            self.assertIn("being build", direct_response.content.decode())

    def test_check_endpoint_returns_the_landing_target_as_json(self):
        self._reference()
        url = reverse("partner:advert_click", args=[AdvertReference.objects.get().reference])
        response = self.client.get(url, {"check": "1"})
        self.assertEqual(response.status_code, 200)
        #   A relative in-site landing URL needs no utm marker; external
        #   "Learn more" links get it when they are rendered.
        self.assertEqual(
            response.json(),
            {"ok": True, "target": f"/ads/sunday-deals-{self.advert.pk}/"},
        )


class AdvertAnalyticsTests(TestCase):
    """Chart payloads are derived from created_at, in the project timezone."""

    def setUp(self):
        self.owner = Auth.objects.create_user(email="analytics-owner@example.com")
        self.advert = AdvertImage.objects.create(
            author=self.owner,
            expiry_date=timezone.now() + timedelta(days=7),
            heading="Analytics advert",
            image_url="https://cdn.example.com/ads/analytics.jpg",
            url="https://example.com/analytics",
        )
        self.reference = AdvertReference.objects.create(
            advert=self.advert,
            user=self.owner,
            plan="pro",
            business_name="Analytics Shop",
        )

    def _event(self, event_type, source, moment=None):
        event = AdvertEvent.objects.create(
            reference=self.reference, event_type=event_type, source=source
        )
        if moment is not None:
            AdvertEvent.objects.filter(pk=event.pk).update(created_at=moment)
        return event

    def test_clicks_are_two_slices_and_direct_counts_as_other(self):
        self._event(AdvertEvent.EVENT_CLICK, AdvertEvent.SOURCE_ABUREPORT)
        self._event(AdvertEvent.EVENT_CLICK, AdvertEvent.SOURCE_DIRECT)
        self._event(AdvertEvent.EVENT_CLICK, AdvertEvent.SOURCE_EXTERNAL)
        self._event(AdvertEvent.EVENT_VIEW, AdvertEvent.SOURCE_ABUREPORT)

        payload = build_advert_analytics(self.reference.events.all(), "7")

        self.assertEqual(payload["click_chart"]["values"], [1, 2])
        self.assertEqual(
            payload["click_chart"]["labels"], ["From Abureport", "Other sources"]
        )
        self.assertEqual(payload["totals"], {
            "views": 1,
            "clicks": 3,
            "abureport_clicks": 1,
            "other_clicks": 2,
            "click_rate": 300.0,
        })

    def test_days_use_local_time_and_range_filters_old_events(self):
        tz = timezone.get_current_timezone()
        now = timezone.now()
        today = timezone.localtime(now, tz).date()
        midnight = timezone.make_aware(datetime.combine(today, time.min), tz)
        old_day = timezone.make_aware(
            datetime.combine(today - timedelta(days=10), time(12, 0)), tz
        )
        self._event(AdvertEvent.EVENT_VIEW, AdvertEvent.SOURCE_ABUREPORT, midnight + timedelta(minutes=1))
        self._event(AdvertEvent.EVENT_VIEW, AdvertEvent.SOURCE_ABUREPORT, old_day)

        week = build_advert_analytics(self.reference.events.all(), "7", now=now)
        self.assertEqual(week["view_chart"]["labels"][-1], today.strftime("%d %b"))
        self.assertEqual(week["view_chart"]["values"][-1], 1)
        self.assertEqual(sum(week["view_chart"]["values"]), 1)

        lifetime = build_advert_analytics(self.reference.events.all(), "all", now=now)
        self.assertEqual(sum(lifetime["view_chart"]["values"]), 2)
