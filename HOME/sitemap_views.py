import math
from datetime import timedelta

from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views import View

from BLOG.models import Blog, Category, get_category_choices
from SERVICE_INTERNAL.config import About
from STAFF.models import StaffProfile
from ARCHIVE.models import ArchiveImage, ArchiveKind
from ARCHIVE.templatetags.archive_extras import cloudinary_proxy


NEWS_PUBLICATION_NAME = getattr(About, 'project_name', 'AbuReport')
NEWS_LANGUAGE = 'en'


class SitemapIndexView(View):
    """Sitemap index at /sitemap.xml linking to all child sitemaps."""
    
    def get(self, request):
        domain = About.domain.rstrip('/')
        now = timezone.now()
        
        # Count stories for pagination
        total_stories = Blog.objects.exclude(slug__isnull=True).exclude(slug='').count()
        news_pages = max(1, math.ceil(total_stories / 1000)) if total_stories > 0 else 0
        
        # Check if there are recent news (last 2 days)
        two_days_ago = now - timedelta(days=2)
        has_recent_news = Blog.objects.exclude(slug__isnull=True).exclude(slug='').filter(
            date_created__gte=two_days_ago
        ).exists()
        
        # Count categories with stories
        published_categories = set(
            Blog.objects.exclude(slug__isnull=True)
            .exclude(slug="")
            .values_list("category", flat=True)
            .distinct()
        )
        has_categories = len(published_categories) > 0 or Category.objects.exists()
        
        sitemaps = []
        
        if has_recent_news:
            sitemaps.append({
                'loc': f'{domain}/recent-news-sitemap.xml',
                'lastmod': now.date().isoformat()
            })
        
        if news_pages > 0:
            for i in range(1, news_pages + 1):
                sitemaps.append({
                    'loc': f'{domain}/all-news-sitemap-{i}.xml',
                    'lastmod': now.date().isoformat()
                })
        
        if has_categories:
            sitemaps.append({
                'loc': f'{domain}/story-categories-sitemap.xml',
                'lastmod': now.date().isoformat()
            })
        
        # General pages sitemap
        sitemaps.append({
            'loc': f'{domain}/pages-sitemap.xml',
            'lastmod': now.date().isoformat()
        })
        
        return render(request, 'HOME/sitemap_index.xml', {'sitemaps': sitemaps}, content_type='application/xml')


class RecentNewsSitemapView(View):
    """News sitemap for articles published in the last 2 days (Google News)."""
    
    def get(self, request):
        domain = About.domain.rstrip('/')
        now = timezone.now()
        two_days_ago = now - timedelta(days=2)
        
        stories = Blog.objects.exclude(slug__isnull=True).exclude(slug='').filter(
            date_created__gte=two_days_ago
        ).select_related('author').order_by('-date_created')[:1000]
        
        urls = []
        for story in stories:
            pub_date = story.date_created
            if pub_date.tzinfo is None:
                pub_date = timezone.make_aware(pub_date)
            urls.append({
                'loc': f"{domain}{reverse('blog:story_detail', args=[story.slug])}",
                'title': story.heading,
                'publication_date': pub_date.strftime('%Y-%m-%dT%H:%M:%SZ') if pub_date.tzinfo else pub_date.strftime('%Y-%m-%dT%H:%M:%S%z'),
                'publication_name': NEWS_PUBLICATION_NAME,
                'language': NEWS_LANGUAGE,
            })
        
        return render(request, 'HOME/news_sitemap.xml', {'urls': urls}, content_type='application/xml')


class AllNewsSitemapView(View):
    """Paginated news sitemaps (1000 stories per file)."""
    
    def get(self, request, page):
        domain = About.domain.rstrip('/')
        page = int(page)
        start = (page - 1) * 1000
        end = start + 1000
        
        stories = Blog.objects.exclude(slug__isnull=True).exclude(slug='').only(
            'id', 'slug', 'heading', 'date_created', 'last_updated'
        ).order_by('-date_created')[start:end]
        
        urls = []
        for story in stories:
            pub_date = story.date_created
            if pub_date:
                if pub_date.tzinfo is None:
                    pub_date = timezone.make_aware(pub_date)
                urls.append({
                    'loc': f"{domain}{reverse('blog:story_detail', args=[story.slug])}",
                    'title': story.heading,
                    'publication_date': pub_date.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'publication_name': NEWS_PUBLICATION_NAME,
                    'language': NEWS_LANGUAGE,
                })
        
        return render(request, 'HOME/news_sitemap.xml', {'urls': urls}, content_type='application/xml')


class StoryCategoriesSitemapView(View):
    """Sitemap containing all news categories in the project."""
    
    def get(self, request):
        domain = About.domain.rstrip('/')
        today = timezone.localdate()
        
        # Get all categories that have stories
        published_categories = set(
            Blog.objects.exclude(slug__isnull=True)
            .exclude(slug="")
            .values_list("category", flat=True)
            .distinct()
        )
        
        urls = []
        for name, _ in get_category_choices():
            if name in published_categories:
                urls.append({
                    'loc': f"{domain}{reverse('home:category', args=[slugify(name)])}",
                    'lastmod': today.isoformat(),
                    'changefreq': 'daily',
                    'priority': '0.7',
                })
        
        return render(request, 'HOME/sitemap.xml', {'urls': urls}, content_type='application/xml')


class PagesSitemapView(View):
    """Sitemap for remaining URLs: static pages, portfolios, archive."""
    
    def get(self, request):
        domain = About.domain.rstrip('/')
        today = timezone.localdate()
        
        from ARCHIVE.models import ArchiveImage, ArchiveKind
        from ARCHIVE.templatetags.archive_extras import cloudinary_proxy
        
        newest_item = ArchiveImage.objects.order_by("-date_created").only("date_created").first()
        archive_lastmod = (
            newest_item.date_created.date().isoformat()
            if newest_item and newest_item.date_created
            else ""
        )
        
        # Image sitemap entries for archive
        archive_images = []
        for item in (
            ArchiveImage.objects.filter(kind=ArchiveKind.IMAGE)
            .only("url", "alt", "date_created")
            .order_by("-date_created")[:2000]
        ):
            proxied = cloudinary_proxy(item.url)
            if not proxied or not str(proxied).startswith("/"):
                continue
            archive_images.append(
                {
                    "loc": f"{domain}{proxied}",
                    "title": item.alt,
                    "caption": item.alt,
                    "lastmod": item.date_created.date().isoformat() if item.date_created else "",
                }
            )
        
        urls = [
            {"loc": f"{domain}/", "lastmod": today.isoformat(), "changefreq": "hourly", "priority": "1.0"},
            {"loc": f"{domain}{reverse('home:about')}", "lastmod": today.isoformat(), "changefreq": "monthly", "priority": "0.5"},
            {"loc": f"{domain}{reverse('editorial_team')}", "lastmod": today.isoformat(), "changefreq": "monthly", "priority": "0.5"},
            {"loc": f"{domain}{reverse('home:privacy_policy')}", "lastmod": today.isoformat(), "changefreq": "yearly", "priority": "0.3"},
            {"loc": f"{domain}{reverse('home:promote')}", "lastmod": today.isoformat(), "changefreq": "monthly", "priority": "0.5"},
            {"loc": f"{domain}{reverse('archive:gallery')}", "lastmod": archive_lastmod or today.isoformat(), "changefreq": "daily", "priority": "0.6", "images": archive_images},
            {"loc": f"{domain}/most-viewed/", "lastmod": today.isoformat(), "changefreq": "daily", "priority": "0.6"},
        ]
        
        # Staff portfolios
        profiles = (
            StaffProfile.objects.filter(auth__is_active=True)
            .filter(Q(auth__is_staff=True) | Q(auth__is_admin=True) | Q(auth__is_superuser=True))
            .exclude(slug__isnull=True)
            .exclude(slug="")
            .only("id", "slug")
            .order_by("slug")
        )
        for profile in profiles:
            urls.append(
                {
                    "loc": f"{domain}{reverse('staff:portfolio', args=[profile.slug])}",
                    "lastmod": today.isoformat(),
                    "changefreq": "weekly",
                    "priority": "0.6",
                }
            )
        
        return render(request, 'HOME/sitemap.xml', {'urls': urls}, content_type='application/xml')
