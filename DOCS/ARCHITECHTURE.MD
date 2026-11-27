# ARCHITECHTURE.MD
Project blueprint and decisions are documented here and on every update made to this project, revision are made here , also click on [footer](#footer) for last updated date and information on last changes made

## TABLE OF CONTENT

  * [Main scope](#main-scope)
  * [Sepration of concern](#sepration-of-concern)
  * [Analytics write path](#analytics-write-path)
  * [Traffic source keys](#traffic-source-keys)
  * [Generated internal links](#generated-internal-links)

  
## MAIN SCOPE
This project serves as a community services, i realized if i cant give money back to the community i come from yet, i can at least contribute to the development of student awareness online by creating a platform that helps student aware of what is happening around them both in a convinience method.
in collaboration with an accomplice of mine who have the required attentions and me that have the skills to build this, we decided to bring this project to live with one sole purpose "**MAKE INFORATION AFFORDABLE**".

## SEPRATION OF CONCERN
`PORTFOLIO STOP WORKING IF USER ACCOUNT IS DISABLED`
All apps defined inside this project are mobile meaning they can be moved without affecting the monolithical apporach this project utilize
```micro-service
AUTHENTICATION/
```
> Managing who and what you can do, seprated as currently its session based but when scalability arise, i can easily migrate it to any other authentication type.

```micro-service
admin/
```
> Manages every access admin has to this entire project, this is only seprated for code structurability not for future migration as the admin app will always be a part of the monolith

```micro-service
staff/
```
> Similar to the admin app but this ones have limited access to writing reports, category under which report fall to, creating a bio inside the project , having their own dedicated profile where all their article can be collated and they can share it as a resume since the og metadata will carry their bio, post count, views summation, profile picture and role
look into [database-structure](#) for more info on this, *The admin is also regarded as a staff as they are staff and admin at the same time so they also can have their own profile*

```micro-service
blog/
```
>  All blogs, news, etc data will be displayed and served through this app as its core purpose is to serve user interface 

```micro-service
api-v1/
```
> This project also allow external users to create their own application off it as it can also stand as a standalone api (*NOT IN THIS MVP CURRRENT AIM AS CURRENTLY IM FOCUSING ON WEB APPLICATION ONLY*)

## USER INTERFACE STRUCTURE
The ui target and response perfectly to both mobile and desktop, with mobile first css and all templates extending the base template [structure in ui.md](UI.MD)

## ANALYTICS WRITE PATH
Page requests do not write analytics rows. They append a small event to a Redis-backed cache list under `analytics:pending:story_views:v1` or `analytics:pending:advert_events:v1`. Appends take a short lock (`analytics:append:lock`); the site health probe takes the flush lock (`analytics:flush:lock`) and writes the batch. `NoName/urls.py::health` stays public and always answers `{"message": "success", "ip": ...}`. A flush failure is logged and the failed rows stay in cache for the next probe, so the health response never changes and a row is never written twice.

`SERVICE_INTERNAL/analytics_buffer.py` owns the queues, the timestamp-preserving flush and the read helpers. `SERVICE_INTERNAL/abstract.py` still supplies the client IP and bot check. Only one schema field was added for this work: `BLOG.StoryView.source` in migration `0023_storyview_source.py` (default `direct`, indexed). No new story advert table was introduced.

Both read paths combine cache and database:
- `BLOG.views.StoryDetailView` keeps the immediate `Blog.views` counter and queues a timestamped `StoryView` in the same dedupe branch. `HOME/author_analytics.py` adds pending rows to DB rows before it counts KPIs, ranks, sources and the own-story table.
- `Partner.tracking.record_advert_event` buffers a view or click under a real `AdvertReference`. `Partner/advert_analytics.py` accepts pending rows alongside `AdvertEvent` rows, so the advertiser dashboard and the Ads desk modal show the same totals before and after the flush. A story advert with no reference is cache-only and is discarded at flush time because there is no generic event table for it.

## TRAFFIC SOURCE KEYS
`SERVICE_INTERNAL/traffic.py` is the single source of truth for source keys and labels. The Referer header is checked first, so a share that strips UTM values is still classified. `utm_source` is a fallback only when there is no usable referrer. Keys are short because `AdvertEvent.source` is a 16 character column: `google`, `google_name`, `google_abu`, `facebook`, `whatsapp`, `x_twitter`, `instagram`, `linkedin`, `bing`, `abureport`, `direct` and `other`. A Google query that contains the author's full name gets `google_name`; adding "abureport" gets `google_abu`. Anything unknown is folded into `other` in the breakdown so totals stay honest.

## GENERATED INTERNAL LINKS
`tag_internal_url()` adds `utm_source=abureport` to links this site generates and returns: author analytics story rows, profile comment links, profile most-viewed links, category recommendations and new-story emails. It leaves an existing `utm_source` alone and preserves fragments. Ordinary template story cards are not rewritten, so navigation inside the site stays a normal internal visit and is still labelled Abureport by the Referer check.

## FOOTER

