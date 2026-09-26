from django.urls import path

from . import views

app_name = "archive"

urlpatterns = [
    path("", views.ArchiveGalleryView.as_view(), name="gallery"),
    path("upload/", views.ArchiveUploadView.as_view(), name="upload"),
    path("upload/modal/", views.ArchiveUploadModalView.as_view(), name="upload_modal"),
    #   "Edit Added Images" htmx popup: list of *this* user's own uploads,
    #   plus inline edit/delete on each row -- see ARCHIVE.views.
    path("manage/", views.ArchiveManageModalView.as_view(), name="manage_modal"),
    path("manage/list/", views.ArchiveManageListView.as_view(), name="manage_list"),
    path("manage/<int:pk>/edit/", views.ArchiveItemEditView.as_view(), name="item_edit"),
    path("manage/<int:pk>/delete/", views.ArchiveItemDeleteView.as_view(), name="item_delete"),
    #   Serves every Cloudinary asset in the project (pictures and plain
    #   files alike, any resource_type) from our own domain -- see
    #   ARCHIVE.views.CloudinaryProxyView and the `cloudinary_proxy`
    #   template filter that points <img>/download links at this route.
    path("cdn/<path:cloud_path>", views.CloudinaryProxyView.as_view(), name="cdn_proxy"),
]
