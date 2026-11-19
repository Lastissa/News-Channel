from django.urls import path, re_path

from . import views

app_name = "partner"

urlpatterns = [
    #   Tracking endpoints stay under /ads/ so the CSP report suppression for
    #   staff-authored advert pages also covers the tiny pixel/click responses.
    path(
        "view/<str:reference>/",
        views.AdvertViewTrackView.as_view(),
        name="advert_view",
    ),
    path(
        "click/<str:reference>/",
        views.AdvertClickView.as_view(),
        name="advert_click",
    ),
    #   SEO/GEO: the advert heading is the slug and the numeric id is LAST, so
    #   renaming an advert changes the readable part while old links still find
    #   the row by id and 301 to the current heading. Kept before the id-only
    #   fallback below.
    re_path(
        r"^(?P<slug>[A-Za-z0-9_-]+)-(?P<pk>\d+)/$",
        views.AdvertLandingView.as_view(),
        name="advert_landing",
    ),
    #   Extra pages of an Advance advert: /ads/<name>-<id>/about/
    re_path(
        r"^(?P<slug>[A-Za-z0-9_-]+)-(?P<pk>\d+)/(?P<path>[a-z0-9][a-z0-9/-]{0,78}[a-z0-9]|[a-z0-9])/$",
        views.AdvertPageView.as_view(),
        name="advert_page",
    ),
    #   Short id-only links are convenient in the panel; they redirect to the
    #   canonical heading-id URL.
    path(
        "<int:pk>/",
        views.AdvertLandingIdRedirectView.as_view(),
        name="advert_landing_id",
    ),
]
