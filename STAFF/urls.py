from django.urls import path

from . import views


app_name = "staff"

urlpatterns = [
    path("<int:author_id>/", views.PortfolioView.as_view(), name="portfolio"),
    path("<int:author_id>/follow/", views.AuthorFollowToggleView.as_view(), name="author_follow"),
]
