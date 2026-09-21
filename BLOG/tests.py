import json

from django.test import TestCase

from AUTHENTICATION.models import Auth
from BLOG.models import Blog, Comment
from BLOG.views import parse_story_content


class BlogArticleFormattingTests(TestCase):
    def setUp(self):
        self.author = Auth.objects.create_user(email="author@example.com")

    def test_story_content_reformats_links_headers_and_lists(self):
        content = """# Admissions

The official portal is here: https://example.com/path

* First bullet item
* Second bullet item

1. First numbered item
2. Second numbered item

**Important update**

__Please note:__
"""

        html = parse_story_content(content)

        self.assertIn('<h2>Admissions</h2>', html)
        self.assertIn('<a href="https://example.com/path"', html)
        self.assertIn('<ul>', html)
        self.assertIn('<li>First bullet item</li>', html)
        self.assertIn('<ol>', html)
        self.assertIn('<li>First numbered item</li>', html)
        self.assertIn('<strong>Important update</strong>', html)
        self.assertIn('<em>Please note:</em>', html)

    def test_story_detail_page_renders_metrics(self):
        blog = Blog.objects.create(
            author=self.author,
            category="UNIVERSITY",
            heading="UNILAG Post UTME Form",
            content="# Admissions\n\nThe official portal is here: https://example.com/post\n\nThis is paragraph text.",
            image_1="https://example.com/image.jpg",
            image_info="Campus gate during screening.",
        )

        response = self.client.get(f"/story/{blog.id}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Views")
        self.assertContains(response, "Word count")
        self.assertContains(response, "Campus gate during screening.")

    def test_story_content_supports_official_news_markers(self):
        content = """# Admission Process

The official portal is here: https://example.edu/admission

**Late applications will not be accepted.**

__Please note:__ deadlines are strict.

* A valid email address
* A recent passport photo

1. Visit the official portal
2. Complete the form
"""

        html = parse_story_content(content)

        self.assertIn('<h2>Admission Process</h2>', html)
        self.assertIn('<a href="https://example.edu/admission"', html)
        self.assertIn('<strong>Late applications will not be accepted.</strong>', html)
        self.assertIn('<em>Please note:</em>', html)
        self.assertIn('<ul>', html)
        self.assertIn('<ol>', html)

    def test_blog_like_is_unique_per_user(self):
        blog = Blog.objects.create(
            author=self.author,
            category="GENERAL",
            heading="Daily news update",
            content="A short update.",
        )
        self.client.force_login(self.author)

        first = self.client.post(f"/story/{blog.id}/like/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        second = self.client.post(f"/story/{blog.id}/like/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(json.loads(first.content)["likes"], 1)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(json.loads(second.content)["likes"], 1)
        self.assertEqual(json.loads(second.content)["detail"], "You already liked this story.")

    def test_only_one_comment_per_story_is_allowed(self):
        blog = Blog.objects.create(
            author=self.author,
            category="GENERAL",
            heading="A commentable story",
            content="This is a story for comments.",
        )
        self.client.force_login(self.author)

        first = self.client.post(f"/story/{blog.id}/comment/", {"comment": "First comment"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        second = self.client.post(f"/story/{blog.id}/comment/", {"comment": "Second comment"}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 400)
        self.assertEqual(Comment.objects.filter(blog=blog, author=self.author).count(), 1)
