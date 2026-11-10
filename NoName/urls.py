
import logging

from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path
from django.views.generic import RedirectView

from HOME.views import BingIndexNowView, YandexIndexNow, FavicoView, ManifestView, RobotsTxtView, LlmsTxtView, RssFeedView, AtomFeedView, UnsubscribeView
from SERVICE_INTERNAL.abstract import get_client_ip, info_logger
from _.views import CSPReportView

from HOME.sitemap_views import (
    SitemapIndexView,
    RecentNewsSitemapView,
    AllNewsSitemapView,
    StoryCategoriesSitemapView,
    PagesSitemapView,
)
from STAFF.views import EditorialTeamView

#   DJANGO ADMIN (/_admin/) IS OPEN TO SUPERUSERS ONLY. By default Django lets
#   every account with is_staff in, and every journalist is is_staff, so the
#   door check is replaced here. Everyone else is sent back to the admin login.
admin.site.has_permission = lambda request: bool(request.user.is_active and request.user.is_superuser)

handler404 = "HOME.views.handler404"
handler500 = "HOME.views.handler500"


def health(request):
    try:
        ip = get_client_ip(request) or ""
    except Exception:
        ip = request.META.get("REMOTE_ADDR", "") or ""
    payload = {"message": "success", "ip": ip}
    get = dict(request.GET) or {}
    post = dict(request.body) or {}
    form_post = dict(request.POST) or {}
    info_logger(msg =f"HEALTH: get=%{get} post={post} form_post={form_post} ip=%{ip}")
    return JsonResponse(payload, status=200)

urlpatterns = [
    path("health", health),
    path("health/", health),
    path("ads.txt", RedirectView.as_view(url="/static/ads.txt")),
    path('robots.txt', RobotsTxtView.as_view()),
    path('favicon.ico', FavicoView.as_view()),
    path('site.webmanifest', ManifestView.as_view()),
    path('sitemap.xml', SitemapIndexView.as_view()),
    path('sitemap.xml/', SitemapIndexView.as_view()),
    path('sitemap_index.xml', SitemapIndexView.as_view()),
    path('recent-news-sitemap.xml', RecentNewsSitemapView.as_view()),
    path('recent-news-sitemap.xml/', RecentNewsSitemapView.as_view()),
    path('recent-news.sitemap.xml', RecentNewsSitemapView.as_view()),
    path('all-news-sitemap-<int:page>.xml', AllNewsSitemapView.as_view()),
    path('all-news-sitemap-<int:page>.xml/', AllNewsSitemapView.as_view()),
    path('story-categories-sitemap.xml', StoryCategoriesSitemapView.as_view()),
    path('story-categories-sitemaps.xml', StoryCategoriesSitemapView.as_view()),
    path('story-categories-sitemap.xml/', StoryCategoriesSitemapView.as_view()),
    path('pages-sitemap.xml', PagesSitemapView.as_view()),
    path('pages-sitemap.xml/', PagesSitemapView.as_view()),
    path('general-sitemap.xml', PagesSitemapView.as_view()),  # alternative name for remaining URLs
    path('llms.txt', LlmsTxtView.as_view()),
    path('rss.xml', RssFeedView.as_view()),
    path('atom.xml', AtomFeedView.as_view()),
    path('yandex_1093315bd8192b90.html', YandexIndexNow.as_view()),
    path('28499029458943a79b9877afdefa8212.txt', BingIndexNowView.as_view()),
    path('unsubscribe/', UnsubscribeView.as_view()),
    path('csp-report/', CSPReportView.as_view(), name='csp_report'),
    path('sy/', include("_.urls")),
    path('_admin/', admin.site.urls),
    path('control/', include("ADMIN.urls")),
    path('editorial/', EditorialTeamView.as_view(), name="editorial_team"),
    path('auth/', include("AUTHENTICATION.urls")),
    path('story/', include("BLOG.urls")),
    path('portfolio/', include("STAFF.urls")),
    path('archive/', include("ARCHIVE.urls")),
    #   Off-grid advert landing pages: /ads/<heading-slug>-<id>/. Kept above
    #   the HOME catch-all and next to the other fixed top-level sections.
    path('ads/', include("Partner.urls")),
    
    path('', include("HOME.urls")),
]
