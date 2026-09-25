from django.urls import path

from . import views


app_name = "staff"

urlpatterns = [
    #   SEO/GEO: descriptive slug instead of the bare numeric id, e.g.
    #   /portfolio/jane-doe/ instead of /portfolio/12/.
    path("<slug:author_slug>/", views.PortfolioView.as_view(), name="portfolio"),
    path("<int:author_id>/follow/", views.AuthorFollowToggleView.as_view(), name="author_follow"),
]
