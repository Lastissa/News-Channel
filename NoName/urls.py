
from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from HOME.views import RobotsTxtView, SitemapXmlView

handler404 = "HOME.views.handler404"
handler500 = "HOME.views.handler500"

urlpatterns = [
    path('robots.txt', RobotsTxtView.as_view()),
    path('sitemap.xml', SitemapXmlView.as_view()),
    # path("favicon.ico",RedirectView.as_view(url="/static/logo.jpg", permanent=True),),
    path('sy/', include("_.urls")),
    path('_admin/', admin.site.urls),
    path('control/', include("ADMIN.urls")),
    path('auth/', include("AUTHENTICATION.urls")),
    path('story/', include("BLOG.urls")),
    path('portfolio/', include("STAFF.urls")),
    path('', include("HOME.urls")),
]
