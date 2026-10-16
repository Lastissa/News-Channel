"""Cache keys shared by more than one app, so a reader and an invalidator can
never drift apart.

This exists because of a real bug: HOME.views.HomeView read the key
"home_page_blogs" while every invalidation signal cleared
"home_page_blogs_v2", so the home page and its "Load more" could disagree and
go stale after a publish. Import the constant below instead of typing the
literal string anywhere.
"""

#   Home page story cache. Written by HOME.views (the small, bounded featured
#   set) and cleared by the Blog / StaffProfile / SiteSettings post_save and
#   post_delete signals (see BLOG.signals, STAFF.signals, ADMIN.signals).
HOME_BLOGS_CACHE_KEY = "home_page_blogs_v2"

#   Seconds. A TTL is a safety net only: the signals above clear the key the
#   moment content changes, so the cache is normally invalidated long before
#   this expires.
HOME_BLOGS_CACHE_TTL = 60*60 # I CHANGED THE TTL TO 1 HOUR 
