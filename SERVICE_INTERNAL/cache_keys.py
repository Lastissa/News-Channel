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

#   Rendered home page HTML (HOME.views.HomeView). Only the anonymous,
#   unfiltered page 1 is stored; signed-in readers and any page with a query
#   string bypass it. Every signal that owns a piece of the home page clears
#   this key too, so a new story is visible on the next request instead of
#   waiting for the safety-net TTL below.
HOME_PAGE_HTML_CACHE_KEY = "home_page_html_v1"

#   Seconds. Deliberately short: adverts and other live widgets that are not
#   covered by a model signal can never be stale for more than a minute.
HOME_PAGE_HTML_CACHE_TTL = 60

#   RSS / Atom feed items (HOME.views._FeedView). The 50 newest stories are
#   built once and shared by /rss.xml and /atom.xml. Written by HOME.views and
#   cleared by BLOG.signals the moment a story is saved or deleted, so the
#   TTL below is only a safety net (it also bounds how long a renamed author
#   can show the old name in the feed). 15 minutes: feed readers and crawlers
#   poll every 15-60 minutes, so a longer TTL gains nothing and a shorter one
#   just rebuilds 50 excerpts for no reason.
STORY_FEED_CACHE_KEY = "story_feed_items_v1"
STORY_FEED_CACHE_TTL = 15 * 60
