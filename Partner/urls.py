from django.urls import path, re_path

from . import views

app_name = "partner"

urlpatterns = [
    #   SEO/GEO: the advert heading is the slug and the numeric id is LAST, so
    #   renaming an advert changes the readable part while old links still find
    #   the row by id and 301 to the current heading. Kept before the id-only
    #   fallback below.
    re_path(
        r"^(?P<slug>[A-Za-z0-9_-]+)-(?P<pk>\d+)/$",
        views.AdvertLandingView.as_view(),
        name="advert_landing",
    ),
    #   Short id-only links are convenient in the panel; they redirect to the
    #   canonical heading-id URL.
    path(
        "<int:pk>/",
        views.AdvertLandingIdRedirectView.as_view(),
        name="advert_landing_id",
    ),
]
