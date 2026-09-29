import itertools
from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from AUTHENTICATION.models import Auth
from BLOG.models import Blog
from STAFF.models import StaffProfile


_counter = itertools.count(1)


class QuietTestCase(TestCase):
    """force_login fires AUTHENTICATION.signals.track_login, which sends a real
    "New login" email through Resend. Tests must never email anyone, so that
    one call is stubbed out for every test in a subclass."""

    def setUp(self):
        super().setUp()
        patcher = mock.patch("AUTHENTICATION.signals._try_send_login_email")
        patcher.start()
        self.addCleanup(patcher.stop)


def make_staff(email="editor@example.com"):
    user = Auth.objects.create_user(email=email, is_staff=True)
    StaffProfile.objects.create(auth=user, gender="M", full_name="Test Editor", get_blog_notification=False)
    return user


def make_story(author, heading="Original Heading", category="GENERAL", **extra):
    data = dict(
        author=author,
        heading=heading,
        category=category,
        content="Original content.",
        image_1="https://example.com/original.jpg",
        image_info="Original caption.",
    )
    data.update(extra)
    return Blog.objects.create(**data)


@mock.patch("HOME.views.ping_indexnow")
class EditNewsViewTests(QuietTestCase):
    def setUp(self):
        super().setUp()
        self.author = make_staff()
        self.blog = make_story(self.author)
        self.url = reverse("home:edit_news", args=[self.blog.id])
        self.client.force_login(self.author)

    def post(self, **fields):
        payload = {
            "image_1": self.blog.image_1 or "",
            "image_info": self.blog.image_info,
            "category": self.blog.category,
            "content": self.blog.content,
        }
        payload.update(fields)
        return self.client.post(self.url, payload)

    #   ------------------------------------------------------------ access
    def test_anonymous_and_non_staff_are_sent_to_profile(self, _ping):
        self.client.logout()
        self.assertRedirects(self.client.get(self.url), reverse("home:profile"), fetch_redirect_response=False)

        member = Auth.objects.create_user(email="member@example.com")
        self.client.force_login(member)
        self.assertRedirects(self.client.get(self.url), reverse("home:profile"), fetch_redirect_response=False)
        response = self.client.post(self.url, {"content": "hijack", "category": "GENERAL"})
        self.assertEqual(response.status_code, 302)
        self.blog.refresh_from_db()
        self.assertEqual(self.blog.content, "Original content.")

    def test_staff_cannot_open_or_edit_someone_elses_story(self, _ping):
        other = make_staff("other@example.com")
        theirs = make_story(other, heading="Theirs")
        url = reverse("home:edit_news", args=[theirs.id])

        self.assertRedirects(self.client.get(url), reverse("home:profile"), fetch_redirect_response=False)
        response = self.client.post(url, {"content": "hijack", "category": "GENERAL"})
        self.assertEqual(response.status_code, 404)
        theirs.refresh_from_db()
        self.assertEqual(theirs.content, "Original content.")
        self.assertIsNone(theirs.last_edited)

    #   ------------------------------------------------------------ GET
    def test_get_opens_prefilled_with_locked_heading(self, _ping):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "HOME/edit_news.html")
        self.assertContains(response, 'value="Original Heading"')
        self.assertContains(response, 'value="https://example.com/original.jpg"')
        self.assertContains(response, 'value="Original caption."')
        self.assertContains(response, ">Original content.</textarea>")
        self.assertContains(response, '<option value="GENERAL" selected>')
        self.assertContains(response, "edit-news-editor.js")
        self.assertContains(response, "add-news.css")
        #   the heading input is disabled and has no name, so it can never be submitted
        html = response.content.decode()
        heading_input = html[html.index('id="editor-heading"'):]
        heading_input = heading_input[: heading_input.index(">")]
        self.assertIn("disabled", heading_input)
        self.assertNotIn("name=", heading_input)

    def test_get_keeps_a_retired_category_selectable(self, _ping):
        legacy = make_story(self.author, heading="Old one", category="SECURITY")
        response = self.client.get(reverse("home:edit_news", args=[legacy.id]))
        self.assertContains(response, '<option value="SECURITY" selected>')

    def test_content_with_markup_is_escaped_in_the_textarea(self, _ping):
        tricky = make_story(self.author, heading="Tricky", content="</textarea><script>alert(1)</script>")
        response = self.client.get(reverse("home:edit_news", args=[tricky.id]))
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "&lt;/textarea&gt;&lt;script&gt;")

    #   ------------------------------------------------------------ POST: what can change
    def test_banner_category_and_content_can_be_edited(self, _ping):
        before = self.blog.last_updated
        response = self.post(
            image_1="https://example.com/new.jpg",
            image_info="New caption.",
            category="SCHOLARSHIP",
            content="Brand new content.",
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["changed"])
        self.assertEqual(body["story_url"], reverse("blog:story_detail", args=[self.blog.slug]))

        self.blog.refresh_from_db()
        self.assertEqual(self.blog.image_1, "https://example.com/new.jpg")
        self.assertEqual(self.blog.image_info, "New caption.")
        self.assertEqual(self.blog.category, "SCHOLARSHIP")
        self.assertEqual(self.blog.content, "Brand new content.")
        self.assertIsNotNone(self.blog.last_edited)
        self.assertGreater(self.blog.last_updated, before)

    def test_heading_can_never_be_edited_even_with_a_tampered_post(self, _ping):
        slug = self.blog.slug
        response = self.post(heading="HACKED HEADING", content="Changed body.")
        self.assertEqual(response.status_code, 200)
        self.blog.refresh_from_db()
        self.assertEqual(self.blog.heading, "Original Heading")
        self.assertEqual(self.blog.slug, slug)
        self.assertEqual(self.blog.content, "Changed body.")

    def test_save_never_writes_heading_views_or_likes(self, _ping):
        with mock.patch.object(Blog, "save", autospec=True, side_effect=Blog.save) as spy:
            self.post(content="Changed body.")
        fields = spy.call_args.kwargs["update_fields"]
        self.assertNotIn("heading", fields)
        self.assertNotIn("views", fields)
        self.assertNotIn("likes", fields)
        self.assertNotIn("slug", fields)
        self.assertIn("last_edited", fields)
        self.assertIn("last_updated", fields)

    def test_views_that_arrive_during_an_edit_are_not_wiped(self, _ping):
        Blog.objects.filter(pk=self.blog.pk).update(views=41, likes=3)
        self.post(content="Changed body.")
        self.blog.refresh_from_db()
        self.assertEqual((self.blog.views, self.blog.likes), (41, 3))

    def test_edit_that_changes_nothing_is_not_saved(self, _ping):
        before = Blog.objects.get(pk=self.blog.pk).last_updated
        response = self.post()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["changed"])
        self.blog.refresh_from_db()
        self.assertIsNone(self.blog.last_edited)
        self.assertEqual(self.blog.last_updated, before)

    def test_browser_style_line_endings_do_not_count_as_a_change(self, _ping):
        Blog.objects.filter(pk=self.blog.pk).update(content="Line one.\r\n\r\nLine two.")
        self.blog.refresh_from_db()
        response = self.post(content="Line one.\n\nLine two.")
        self.assertFalse(response.json()["changed"])

    #   ------------------------------------------------------------ POST: validation
    def test_validation_errors(self, _ping):
        for fields, needle in [
            ({"content": "   "}, "content cannot be empty"),
            ({"category": "NOPE"}, "valid category"),
            ({"category": ""}, "valid category"),
            ({"image_1": "javascript:alert(1)"}, "valid http or https"),
            ({"image_1": "https://example.com/" + "a" * 300}, "too long"),
            ({"image_info": "x" * 101}, "100 characters"),
        ]:
            with self.subTest(fields=fields):
                response = self.post(**fields)
                self.assertEqual(response.status_code, 400)
                self.assertIn(needle, response.json()["detail"])
        self.blog.refresh_from_db()
        self.assertIsNone(self.blog.last_edited)

    def test_moving_into_a_category_that_already_has_the_same_heading_is_refused(self, _ping):
        make_story(self.author, heading="original heading", category="WAEC")
        response = self.post(category="WAEC")
        self.assertEqual(response.status_code, 400)
        self.assertIn("already have a story", response.json()["detail"])
        self.blog.refresh_from_db()
        self.assertEqual(self.blog.category, "GENERAL")

    def test_retired_category_can_stay_but_cannot_be_newly_picked(self, _ping):
        legacy = make_story(self.author, heading="Old one", category="SECURITY", content="Old body.")
        url = reverse("home:edit_news", args=[legacy.id])
        payload = {"image_1": legacy.image_1, "image_info": legacy.image_info, "category": "SECURITY", "content": "New body."}
        self.assertEqual(self.client.post(url, payload).status_code, 200)
        legacy.refresh_from_db()
        self.assertEqual((legacy.category, legacy.content), ("SECURITY", "New body."))

        #   a different story cannot be moved INTO the retired category
        self.assertEqual(self.post(category="SECURITY").status_code, 400)

    #   ------------------------------------------------------------ POST: banner handling
    def test_uploaded_file_overwrites_the_same_cloudinary_asset(self, _ping):
        Blog.objects.filter(pk=self.blog.pk).update(image_public_id="abureport/news/abc123")
        upload = SimpleUploadedFile("pic.jpg", b"fake-bytes", content_type="image/jpeg")
        with mock.patch(
            "HOME.views.upload_news_image",
            return_value={"secure_url": "https://res.cloudinary.com/x/image/upload/v2/abureport/news/abc123.jpg", "public_id": "abureport/news/abc123"},
        ) as uploader:
            response = self.client.post(
                self.url,
                {"image_file": upload, "image_quality": "high", "image_info": "Original caption.", "category": "GENERAL", "content": "Original content."},
            )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["changed"])
        self.assertEqual(uploader.call_args.kwargs["public_id"], "abureport/news/abc123")
        self.assertEqual(uploader.call_args.kwargs["quality"], "high")
        self.blog.refresh_from_db()
        self.assertEqual(self.blog.image_1, "https://res.cloudinary.com/x/image/upload/v2/abureport/news/abc123.jpg")
        self.assertEqual(self.blog.image_public_id, "abureport/news/abc123")
        self.assertIsNotNone(self.blog.last_edited)

    def test_first_upload_on_a_story_with_a_pasted_link_saves_the_new_public_id(self, _ping):
        upload = SimpleUploadedFile("pic.png", b"fake-bytes", content_type="image/png")
        with mock.patch(
            "HOME.views.upload_news_image",
            return_value={"secure_url": "https://res.cloudinary.com/x/new.png", "public_id": "abureport/news/fresh"},
        ) as uploader:
            self.client.post(self.url, {"image_file": upload, "category": "GENERAL", "content": "Original content."})
        self.assertIsNone(uploader.call_args.kwargs["public_id"])
        self.blog.refresh_from_db()
        self.assertEqual(self.blog.image_public_id, "abureport/news/fresh")

    def test_failed_upload_changes_nothing(self, _ping):
        from SERVICE_INTERNAL.images import ImageUploadError

        upload = SimpleUploadedFile("pic.png", b"fake-bytes", content_type="image/png")
        with mock.patch("HOME.views.upload_news_image", side_effect=ImageUploadError("Cloudinary is down.")):
            response = self.client.post(self.url, {"image_file": upload, "category": "GENERAL", "content": "Changed body."})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"], "Cloudinary is down.")
        self.blog.refresh_from_db()
        self.assertEqual(self.blog.content, "Original content.")
        self.assertIsNone(self.blog.last_edited)

    def test_refused_edit_never_reaches_cloudinary(self, _ping):
        make_story(self.author, heading="original heading", category="WAEC")
        upload = SimpleUploadedFile("pic.png", b"fake-bytes", content_type="image/png")
        with mock.patch("HOME.views.upload_news_image") as uploader:
            response = self.client.post(self.url, {"image_file": upload, "category": "WAEC", "content": "Original content."})
        self.assertEqual(response.status_code, 400)
        uploader.assert_not_called()

    def test_prefilled_cloudinary_link_coming_back_keeps_the_public_id(self, _ping):
        link = "https://res.cloudinary.com/x/image/upload/v1/abureport/news/abc123.jpg"
        Blog.objects.filter(pk=self.blog.pk).update(image_1=link, image_public_id="abureport/news/abc123")
        self.blog.refresh_from_db()
        response = self.post(content="Changed body.")
        self.assertEqual(response.status_code, 200)
        self.blog.refresh_from_db()
        self.assertEqual(self.blog.image_1, link)
        self.assertEqual(self.blog.image_public_id, "abureport/news/abc123")

    def test_switching_an_uploaded_banner_to_a_pasted_link_clears_the_public_id(self, _ping):
        Blog.objects.filter(pk=self.blog.pk).update(image_public_id="abureport/news/abc123")
        self.blog.refresh_from_db()
        self.post(image_1="https://example.com/external.jpg")
        self.blog.refresh_from_db()
        self.assertEqual(self.blog.image_1, "https://example.com/external.jpg")
        self.assertEqual(self.blog.image_public_id, "")

    def test_clearing_the_link_removes_the_banner(self, _ping):
        self.post(image_1="")
        self.blog.refresh_from_db()
        self.assertIsNone(self.blog.image_1)

    def test_blank_caption_falls_back_to_the_model_default(self, _ping):
        self.post(image_info="   ")
        self.blog.refresh_from_db()
        self.assertEqual(self.blog.image_info, "The image is self explanatory.")

    def test_successful_edit_pings_indexnow(self, ping):
        self.post(content="Changed body.")
        self.assertEqual(ping.call_count, 1)
        self.assertTrue(ping.call_args.args[0].endswith(reverse("blog:story_detail", args=[self.blog.slug])))

    def test_no_change_does_not_ping_indexnow(self, ping):
        self.post()
        ping.assert_not_called()


@mock.patch("HOME.views.ping_indexnow")
class ProfileEditLinkTests(QuietTestCase):
    def setUp(self):
        super().setUp()
        self.author = make_staff()
        self.blog = make_story(self.author)
        self.client.force_login(self.author)

    def test_published_list_carries_the_edit_url(self, _ping):
        response = self.client.get(reverse("home:profile_published"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{reverse("home:edit_news", args=[self.blog.id])}"')

    def test_profile_page_lists_an_edit_link_per_story(self, _ping):
        response = self.client.get(reverse("home:profile"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{reverse("home:edit_news", args=[self.blog.id])}"')


class EditedGapLabelTests(TestCase):
    def label(self, **delta):
        n = next(_counter)
        author = Auth.objects.create_user(email=f"gap{n}@example.com", is_staff=True)
        blog = make_story(author, heading=f"Gap {n}")
        blog.last_edited = blog.date_created + timedelta(**delta)
        return blog.edited_gap_label

    def test_never_edited_is_empty(self):
        author = make_staff("never@example.com")
        self.assertEqual(make_story(author).edited_gap_label, "")

    def test_wording(self):
        cases = [
            (dict(seconds=30), "less than a minute"),
            (dict(minutes=1), "1 minute"),
            (dict(minutes=5), "5 minutes"),
            (dict(hours=1), "1 hour"),
            (dict(hours=23), "23 hours"),
            (dict(days=1), "1 day"),
            (dict(days=3), "3 days"),
            (dict(days=6, hours=23), "6 days"),
            (dict(days=7), "1 week"),
            (dict(days=13), "1 week"),
            (dict(days=15), "2 weeks"),
        ]
        for delta, expected in cases:
            with self.subTest(delta=delta):
                self.assertEqual(self.label(**delta), expected)

    def test_clock_skew_never_goes_negative(self):
        self.assertEqual(self.label(seconds=-90), "less than a minute")


@mock.patch("HOME.views.ping_indexnow")
class StoryUpdatedNoticeTests(QuietTestCase):
    def setUp(self):
        super().setUp()
        self.author = make_staff()
        self.blog = make_story(self.author)

    def story(self):
        return self.client.get(reverse("blog:story_detail", args=[self.blog.slug]))

    def test_never_edited_story_shows_no_notice(self, _ping):
        response = self.story()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context["messages"]), [])
        self.assertNotContains(response, "story-edited")

    def test_edited_story_shows_the_notice_with_days(self, _ping):
        Blog.objects.filter(pk=self.blog.pk).update(last_edited=self.blog.date_created + timedelta(days=3))
        response = self.story()
        notices = list(response.context["messages"])
        self.assertEqual(len(notices), 1)
        self.assertEqual(str(notices[0]), "This post was last updated 3 days after its initial publication.")
        self.assertIn("story-edited", notices[0].tags)
        self.assertContains(response, 'class="django-message story-edited info"')

    def test_edited_story_shows_the_notice_with_weeks(self, _ping):
        Blog.objects.filter(pk=self.blog.pk).update(last_edited=self.blog.date_created + timedelta(days=15))
        notices = list(self.story().context["messages"])
        self.assertEqual(str(notices[0]), "This post was last updated 2 weeks after its initial publication.")

    def test_notice_shows_on_every_open_not_just_the_first(self, _ping):
        Blog.objects.filter(pk=self.blog.pk).update(last_edited=self.blog.date_created + timedelta(days=2))
        for _ in range(3):
            self.assertEqual(len(list(self.story().context["messages"])), 1)

    def test_notice_does_not_leak_onto_other_pages(self, _ping):
        Blog.objects.filter(pk=self.blog.pk).update(last_edited=self.blog.date_created + timedelta(days=2))
        self.story()
        self.assertNotContains(self.client.get(reverse("home:home")), "last updated")

    def test_editing_through_the_view_then_reading_shows_the_notice(self, _ping):
        self.client.force_login(self.author)
        response = self.client.post(
            reverse("home:edit_news", args=[self.blog.id]),
            {"image_1": self.blog.image_1, "image_info": self.blog.image_info, "category": "GENERAL", "content": "Fixed a typo."},
        )
        self.assertEqual(response.status_code, 200)
        self.client.logout()

        notices = list(self.story().context["messages"])
        self.assertEqual(str(notices[0]), "This post was last updated less than a minute after its initial publication.")


@mock.patch("HOME.views.ping_indexnow")
class ProfileListSearchTests(QuietTestCase):
    """Published stories, bookmarks and reading history are HTMX lists: each
    endpoint answers `?q=` with a rendered fragment filtered by story heading."""

    def setUp(self):
        super().setUp()
        self.author = make_staff()
        self.jamb = make_story(self.author, heading="JAMB result checker opens")
        self.waec = make_story(self.author, heading="WAEC timetable released")
        self.client.force_login(self.author)

    def test_published_search_filters_by_heading(self, _ping):
        response = self.client.get(reverse("home:profile_published"), {"q": "jamb"})
        self.assertContains(response, "JAMB result checker opens")
        self.assertNotContains(response, "WAEC timetable released")

    def test_published_search_only_covers_the_signed_in_authors_stories(self, _ping):
        other = make_staff("other@example.com")
        make_story(other, heading="JAMB story by someone else")
        response = self.client.get(reverse("home:profile_published"), {"q": "jamb"})
        self.assertNotContains(response, "someone else")

    def test_published_search_with_no_match_says_so(self, _ping):
        response = self.client.get(reverse("home:profile_published"), {"q": "zzz"})
        self.assertContains(response, "No published stories match")

    def test_published_search_is_staff_only(self, _ping):
        self.client.logout()
        member = Auth.objects.create_user(email="member2@example.com")
        self.client.force_login(member)
        response = self.client.get(reverse("home:profile_published"), {"q": "jamb"})
        self.assertEqual(response.status_code, 401)

    def test_bookmark_search_filters_by_heading(self, _ping):
        from HOME.models import Bookmark
        Bookmark.objects.create(user=self.author, blog=self.jamb)
        Bookmark.objects.create(user=self.author, blog=self.waec)
        response = self.client.get(reverse("home:profile_bookmarks"), {"q": "waec"})
        self.assertContains(response, "WAEC timetable released")
        self.assertNotContains(response, "JAMB result checker opens")

    def test_history_search_filters_by_heading(self, _ping):
        self.jamb.non_anonymous_viewer.add(self.author)
        self.waec.non_anonymous_viewer.add(self.author)
        response = self.client.get(reverse("home:profile_history"), {"q": "timetable"})
        self.assertContains(response, "WAEC timetable released")
        self.assertNotContains(response, "JAMB result checker opens")

    def test_pager_keeps_the_search_box_value(self, _ping):
        for n in range(6):
            make_story(self.author, heading=f"Scholarship update {n}")
        response = self.client.get(reverse("home:profile_published"), {"q": "scholarship"})
        self.assertContains(response, 'hx-include="#published-search"')
        self.assertContains(response, f'hx-get="{reverse("home:profile_published")}?page=2"')

    def test_profile_page_renders_all_three_search_boxes(self, _ping):
        response = self.client.get(reverse("home:profile"))
        for box_id in ("published-search", "bookmark-search", "history-search"):
            self.assertContains(response, f'id="{box_id}"')
