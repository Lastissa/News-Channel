from django.urls import path

from . import views

app_name = "blog"

urlpatterns = [
    #   SEO/GEO: descriptive slug instead of the bare numeric id, e.g.
    #   /blog/how-to-pass-jamb-2026-104/ instead of /blog/104/.
    path("<slug:blog_slug>/", views.StoryDetailView.as_view(), name="story_detail"),
    path("<int:blog_id>/like/", views.BlogLikeView.as_view(), name="blog_like"),
    path("bookmark-not-found/", views.BookmarkNotFoundView.as_view(), name="bookmark_not_found"),
    path("<int:blog_id>/comment/", views.CommentCreateView.as_view(), name="comment_create"),
    path("comment/<int:comment_id>/delete/", views.CommentDeleteView.as_view(), name="comment_delete"),
    path("comment/<int:comment_id>/like/", views.CommentLikeView.as_view(), name="comment_like"),
]
