# DATABASE
Every structure to how the database will be desinged will be listed here and for security reasons, details will not be added, just an hint on how the structure is.

## MAIN AUTHENTICATION TABLE
> For validating who is who

| Name | Purpose |
|---|---|
| `email` | Stores the user's unique email address and identifies the account. |
| `password` | for security |
| `date_joined` | Records when the account was created. |
| `is_staff` | Determines whether the user has staff access. |
| `is_superuser` | Determines whether the user has superuser privileges. |
| `is_admin` | Identifies whether the user has administrative privileges. |
| `is_active` | Determines whether the account is currently active and allowed to authenticate. |
| `receive_email_login_alert` | Determines whether the user receives email alerts when a login occurs. |
| `send_newsletter` | Determines whether the user has opted to receive newsletters. |
| `profile_img` | for recognition and identification. Optional |

## PASSWORD RESET KEY TABLE

> One live password reset link per account. The reset link is stateless (email + key + sign), so before any password update the trio must still match a row here; the row is deleted the moment the password changes, making every link single use.

| Name | Purpose |
|---|---|
| `user` | The account the link belongs to. One row per account. |
| `key` | The 6 digit numeric half of the reset link. |
| `sign` | The 10 character alphanumeric half of the reset link. |
| `created_at` | Records when the link was generated. |

## BLOG/NEWS TABLE

> Houses every post / journalis content posted by staffs /admins

| Name | Purpose |
|---|---|
| `author` | Identifies the staff/admin account that created the post. |
| `image_1` | Stores the URL of the primary image associated with the post. The overview |
| `category` | The name of the category the post sits under (see the category table below). Stored as plain text on purpose, not a foreign key, so a post keeps its category when that category is removed. |
| `heading` | Stores the title or heading of the post. |
| `content` | Stores the main content of the post. |
| `views` | Tracks the number of times the post has been viewed. |
| `date_created` | Records when the post was created. |

## BLOG CATEGORY TABLE

> The news categories shown in the navbar menu and the story editor. Managed by admins and superusers from the PANEL page (News categories card), never edited in code.

| Name | Purpose |
|---|---|
| `name` | The category. Saved in capitals, unique whatever the case, 20 characters max, letters / numbers / single spaces / hyphens only. It is both the value stored on a post and the label readers see. |

Rules to keep:
- Read categories ONLY through `BLOG.models.get_category_choices()`. It serves one cache entry (`BLOG.Category::choices::v1`) that never expires and is rebuilt after every committed add / change / remove (`BLOG/signals.py`), so there is no per request query. Never query the table to build a menu or a validation set, and never reuse that cache key.
- Change what is stored under that key only together with a version bump (`v1` to `v2`), because Redis keeps a value with no TTL across deploys.
- A category cannot be renamed from PANEL (posts carry its text, a rename would orphan them or hit the unique post constraint). Remove and add instead.
- Removing a category only retires it: existing posts stay published and editable, they just stop appearing in the menu and the story editor. The last remaining category cannot be removed.
- `QuerySet.update()` and `bulk_create()` skip the signals and leave the cache stale. Use `save()` / `delete()`, or call `refresh_category_cache()` afterwards.
- Never register `Category` in the Django admin site: `Auth.has_perm` always returns True, so every staff account could then edit it, bypassing the admin / superuser only rule.
- Redis is required for this to stay correct with more than one server process. The local fallback (LocMemCache) is per process, so an update made in one worker would never reach the others.

## COMMENT TABLE

> Houses comments / feedback made under blog posts

| Name | Purpose |
|---|---|
| `author` | Identifies the user who made the comment. |
| `blog` | Identifies the blog post that the comment belongs to. |
| `content` | Stores the comment / feedback content. |