
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from HOME.views import BingIndexNowView, YandexIndexNow, FavicoView, RobotsTxtView, LlmsTxtView, RssFeedView, AtomFeedView, UnsubscribeView
from HOME.sitemap_views import (
    SitemapIndexView,
    RecentNewsSitemapView,
    AllNewsSitemapView,
    StoryCategoriesSitemapView,
    PagesSitemapView,
)
from STAFF.views import EditorialTeamView

handler404 = "HOME.views.handler404"
handler500 = "HOME.views.handler500"

urlpatterns = [
    path('robots.txt', RobotsTxtView.as_view()),
    path('favicon.ico', FavicoView.as_view()),
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
    path('sy/', include("_.urls")),
    path('_admin/', admin.site.urls),
    path('control/', include("ADMIN.urls")),
    path('editorial/', EditorialTeamView.as_view(), name="editorial_team"),
    path('auth/', include("AUTHENTICATION.urls")),
    path('story/', include("BLOG.urls")),
    path('portfolio/', include("STAFF.urls")),
    path('archive/', include("ARCHIVE.urls")),
    path('', include("HOME.urls")),
]
