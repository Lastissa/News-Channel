from django.urls import path

from . import views


app_name = "home"

urlpatterns = [
    path("", views.HomeView.as_view(), name="home"),
    path("profile/", views.ProfileView.as_view(), name="profile"),
    path("profile/add-news/", views.AddNewsView.as_view(), name="add_news"),
    path("profile/bookmarks/", views.ProfileBookmarksView.as_view(), name="profile_bookmarks"),
    path("profile/history/", views.ProfileHistoryView.as_view(), name="profile_history"),
    path("profile/comments/", views.ProfileCommentsView.as_view(), name="profile_comments"),
    path("profile/stories/", views.ProfilePublishedView.as_view(), name="profile_published"),
    path("profile/stories/<int:blog_id>/delete/", views.ProfilePublishedDeleteView.as_view(), name="profile_published_delete"),
    path("profile/settings/newsletter/", views.ProfileNewsletterToggleView.as_view(), name="profile_newsletter_toggle"),
    path("profile/settings/send-newsletter/", views.ProfileSendNewsletterToggleView.as_view(), name="profile_send_newsletter_toggle"),
    path("profile/settings/blog-notification/", views.ProfileBlogNotificationToggleView.as_view(), name="profile_blog_notification_toggle"),
    path("profile/settings/logout-all/", views.ProfileLogoutAllSessionsView.as_view(), name="profile_logout_all"),
    path("profile/settings/image/", views.ProfileImageUpdateView.as_view(), name="profile_image_update"),
    path("profile/staff/update/", views.ProfileStaffUpdateView.as_view(), name="profile_staff_update"),
    path("profile/delete/placard/", views.ProfileDeletePlacardView.as_view(), name="profile_delete_placard"),
    path("profile/delete/", views.ProfileDeleteAccountView.as_view(), name="profile_delete_account"),
    path("load-more/", views.LoadMoreView.as_view(), name="load_more"),
    path("bookmark/<int:blog_id>/", views.BookmarkView.as_view(), name="bookmark"),
    path("newsletter/", views.NewsletterSubscribeView.as_view(), name="newsletter"),
    path("privacy-policy/", views.PrivacyPolicyView.as_view(), name="privacy_policy"),
    path("promote-your-bussiness/", views.PromoteView.as_view(), name="promote"),
]

