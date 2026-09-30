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

    path("panel/", views.PanelView.as_view(), name="panel"),
    path("panel/gallery/", views.PanelStaffGalleryView.as_view(), name="panel_gallery"),
    path("panel/sessions/", views.PanelSessionsView.as_view(), name="panel_sessions"),
    path("panel/sessions/<int:account_id>/logout/", views.PanelSessionLogoutView.as_view(), name="panel_session_logout"),
    path("panel/settings/", views.PanelSiteSettingsUpdateView.as_view(), name="panel_settings"),
    path("panel/categories/", views.PanelCategoryCreateView.as_view(), name="panel_category_create"),
    path("panel/categories/<int:category_id>/delete/", views.PanelCategoryDeleteView.as_view(), name="panel_category_delete"),
    path("panel/staff-search/", views.PanelStaffSearchView.as_view(), name="panel_staff_search"),
    path("panel/mass-email/", views.PanelMassEmailView.as_view(), name="panel_mass_email"),
    path("panel/speciality/", views.PanelSpecialityView.as_view(), name="panel_speciality"),
]
