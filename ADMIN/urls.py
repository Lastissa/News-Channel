from django.urls import path

from . import views


app_name = "control"

urlpatterns = [
    path("staff/", views.StaffDirectoryView.as_view(), name="staff_directory"),
    path("staff/new/", views.StaffCreateView.as_view(), name="staff_create"),
    path("staff/<int:staff_id>/", views.StaffDetailView.as_view(), name="staff_detail"),
    path("staff/<int:staff_id>/published/", views.StaffPublishedView.as_view(), name="staff_published"),
    path("staff/<int:staff_id>/tribute/", views.StaffTributeUpdateView.as_view(), name="staff_tribute"),
    path("staff/<int:staff_id>/speciality/", views.StaffSpecialityUpdateView.as_view(), name="staff_speciality"),
    path("staff/<int:staff_id>/role/", views.StaffRoleUpdateView.as_view(), name="staff_role"),
    path("staff/<int:staff_id>/gender/", views.StaffGenderUpdateView.as_view(), name="staff_gender"),
    path("staff/<int:staff_id>/status/", views.StaffBanToggleView.as_view(), name="staff_status"),
    path("me/role/", views.OwnRoleUpdateView.as_view(), name="own_role"),
]
