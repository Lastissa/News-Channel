from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from AUTHENTICATION.models import Auth
from BLOG.views import STORY_ADS_CACHE_KEY, _load_story_ads_pool
from Partner.models import AdvertImage, AdvertReference


class StoryAdsPayloadTests(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.addCleanup(cache.clear)
        self.admin = Auth.objects.create_user(
            email="story-ads-admin@example.com", is_staff=True, is_admin=True
        )
        self.owner = Auth.objects.create_user(email="story-ads-owner@example.com")

    def _advert(self, heading, reference=None):
        advert = AdvertImage.objects.create(
            author=self.admin,
            expiry_date=timezone.now(),
            heading=heading,
            image_url=f"https://example.com/{heading}.jpg",
            url="https://example.com/shop",
        )
        if reference:
            AdvertReference.objects.create(
                user=self.owner,
                plan="pro",
                business_name=heading,
                advert=advert,
            )
        return advert

    def test_pool_exposes_view_and_click_urls_only_for_referenced_adverts(self):
        tracked = self._advert("Tracked", reference=True)
        plain = self._advert("Plain")

        pool = _load_story_ads_pool()
        by_id = {row["id"]: row for row in pool["ads"]}

        code = AdvertReference.objects.get(advert=tracked).reference
        self.assertEqual(by_id[tracked.pk]["reference"], code)
        self.assertEqual(
            by_id[tracked.pk]["view_url"],
            reverse("partner:advert_view", args=[code]),
        )
        self.assertEqual(
            by_id[tracked.pk]["click_url"],
            reverse("partner:advert_click", args=[code]),
        )
        self.assertEqual(by_id[plain.pk]["reference"], "")
        self.assertEqual(by_id[plain.pk]["view_url"], "")
        self.assertEqual(by_id[plain.pk]["click_url"], "")

    def test_story_ads_endpoint_serves_the_cached_tracked_payload(self):
        cache.set(
            STORY_ADS_CACHE_KEY,
            {
                "ads": [
                    {
                        "id": 17,
                        "image": "https://example.com/banner.jpg",
                        "heading": "Campus shop",
                        "body": "Open today.",
                        "url": "https://example.com/shop",
                        "landing_url": "",
                        "reference": "GRACE123456ABCDE",
                        "view_url": "/ads/view/GRACE123456ABCDE/",
                        "click_url": "/ads/click/GRACE123456ABCDE/",
                    }
                ]
            },
        )

        response = self.client.get(reverse("blog:story_ads"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-store")
        ad = response.json()["ad"]
        self.assertEqual(ad["view_url"], "/ads/view/GRACE123456ABCDE/")
        self.assertEqual(ad["click_url"], "/ads/click/GRACE123456ABCDE/")


class StoryAdsScriptTests(TestCase):
    def test_view_pixel_is_fired_after_the_popup_enters_the_page(self):
        script = (
            Path(settings.BASE_DIR) / "BLOG/static/blog/js/story-ads.js"
        ).read_text(encoding="utf-8")

        appended_at = script.index("document.body.appendChild(built.popup)")
        view_at = script.index("recordView(ready.ad.view_url)")
        self.assertGreater(view_at, appended_at)
        self.assertIn("ad.click_url || ad.landing_url || ad.url", script)
        self.assertIn("if (!viewUrl) return;", script)
