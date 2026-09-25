from django.urls import path

from . import views

app_name = "archive"

urlpatterns = [
    path("", views.ArchiveGalleryView.as_view(), name="gallery"),
    path("upload/", views.ArchiveUploadView.as_view(), name="upload"),
    path("upload/modal/", views.ArchiveUploadModalView.as_view(), name="upload_modal"),
    #   Serves every Cloudinary picture in the project from our own domain
    #   -- see ARCHIVE.views.CloudinaryProxyView and the `cloudinary_proxy`
    #   template filter that points <img> tags at this route.
    path("cdn/<path:cloud_path>", views.CloudinaryProxyView.as_view(), name="cdn_proxy"),
]
