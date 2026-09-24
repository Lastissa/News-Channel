
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from HOME.views import BingIndexNowView, YandexIndexNow, FavicoView, RobotsTxtView, SitemapXmlView, UnsubscribeView

handler404 = "HOME.views.handler404"
handler500 = "HOME.views.handler500"

urlpatterns = [
    path('robots.txt', RobotsTxtView.as_view()),
    path('favicon.ico', FavicoView.as_view()),
    path('sitemap.xml', SitemapXmlView.as_view()),
    path('yandex_1093315bd8192b90.html', YandexIndexNow.as_view()),
    path('28499029458943a79b9877afdefa8212.txt', BingIndexNowView.as_view()),
    path('unsubscribe/', UnsubscribeView.as_view()),
    path('sy/', include("_.urls")),
    path('_admin/', admin.site.urls),
    path('control/', include("ADMIN.urls")),
    path('auth/', include("AUTHENTICATION.urls")),
    path('story/', include("BLOG.urls")),
    path('portfolio/', include("STAFF.urls")),
    path('', include("HOME.urls")),
]

