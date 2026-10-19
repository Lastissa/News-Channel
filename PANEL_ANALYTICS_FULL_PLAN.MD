# Panel analytics — the simple plan

**Status:** Member lytics is under way. Built: the three sidebar buttons, the two
placeholder pages, the Quick overview card, the "new users today" badge, and the
panel **Users** card removed (the Members table is now the only directory).
Still to do: the clickable week bars + placard, and Custom days on trends.
**Date:** 17 Oct 2026.

---

## 1. What we build

Three pages, all under the control panel:

| Page | Job | Now |
| --- | --- | --- |
| **Member lytics** | accounts and reading | build first |
| **Staff lytics** | story production and authors | placeholder page |
| **Partner lytics** | adverts and announcements | placeholder page |

## 2. Sidebar

- Keep the solid button at the foot of the panel aside, but make it **three stacked
  buttons**: Member lytics, Staff lytics, Partner lytics.
- Remove the panel **Users** card — DONE. The card, its nav link, its lazy-load JS,
  its CSS (row/status/skeleton rules) and its `panel_user_directory` view + URL are
  all gone. The Members table on Member lytics is now the only member directory.

## 3. URLs and endpoints

| Page / block | URL | control: name |
| --- | --- | --- |
| Member lytics page | `/control/panel/analytics/` | `analytics` (existing name kept) |
| Staff lytics page | `/control/panel/analytics/staff/` | `staff_lytics` (new) |
| Partner lytics page | `/control/panel/analytics/partner/` | `partner_lytics` (new) |
| Quick overview | `/control/panel/analytics/overview/` | `member_overview` (new) |
| New-users badge | `/control/panel/analytics/new-today/` | `member_new_today` (new) |
| One week's stories | `/control/panel/analytics/week/` | `member_week_stories` (new) |

Existing and unchanged: `analytics_stories`, `analytics_trends`, `analytics_members`.
Every new view is admin-only, GET-only, read-only.

## 4. Member lytics page, top to bottom

### 4.1 Quick overview — BUILT
One wide card, first on the page:
- a headline for **new users**: the **change since last week** and **last 30 days**
  (the "today" figure lives in the badge below, not here);
- two metric tiles: **Active readers** and **Stories published**, each with
  today / this week / last 30 days.

It loads its own htmx GET (`member_overview`). The page shell ships only a skeleton,
no numbers. "Last 30 days" is a rolling window, not a calendar month.

### 4.2 "n new users today" badge — BUILT
A pill in the top bar, next to the page title, with its own htmx GET
(`member_new_today`) so it can refresh without touching any other number.

### 4.3 Stories per week (existing card, new behaviour)
- Keep the card, the `1m / 3m / 6m / 1y` select and the bar chart.
- Make each bar clickable and keyboard-focusable. Tapping one opens a centred **placard**
  listing that week's stories: title (link), author, posted date, updated date.
- The author name is a **button that shows a toast** for now — there is no author page yet.

### 4.4 Trends (existing chart, small additions)
- Add `Custom…` to the Range select: a **days** box, 1 to 365. `10` means 10 days.
- Only visual change: on phones, space the points out more and drop the dots when there
  are many points, because 30 dots across a phone is the "too close" you flagged.

### 4.5 Members (existing, untouched)
The filterable member table. It just becomes the only member directory.

## 5. Rules that apply everywhere

- **The page shell shows no numbers.** Every block fetches its own HTML fragment.
- **One loader per block:** a skeleton when the shape is known, three dots for the badge.
- **Failure:** 8 second timeout, then a short message plus a **Retry**, never a forever
  spinner. A new request aborts the old one so a slow answer cannot land late.
- **Motion:** only 160–420 ms fades and skeleton shimmer. No count-up numbers, no gradients.
- **Week = Sunday to Saturday**, from one constant (`WEEK_START_WEEKDAY = 6`) in
  `ADMIN/analytics.py`. Analytics currently uses Monday and STAFF uses Sunday; this makes
  them agree. No JavaScript computes a week today, so nothing there needs changing yet.

## 6. Data

Available today, no schema change: new users (`Auth.date_joined`), active readers
(`StoryView`), stories published (`Blog.date_created`), views (`StoryView`), likes
(`BlogLike`), comments (`Comment`), follows (`AuthorFollow`).

Not available: **newsletter sign-ups per day** — `send_newsletter` is a plain on/off flag
with no date. One optional nullable column (`Auth.newsletter_opted_at`) fixes it later; your
migration to run, not mine.

Heads-up: the dev database has almost no view history (1 `StoryView` row), so the views
trend will look flat. That is the data, not a bug.

## 7. Files to touch

| Area | Files |
| --- | --- |
| Python | `ADMIN/analytics.py`, `ADMIN/views.py`, `ADMIN/urls.py`, `STAFF/views.py` (line 416 only) |
| Templates | `panel.html`, `analytics.html`, plus new `analytics_overview.html`, `analytics_new_today.html`, `analytics_week_stories.html`, and two placeholder pages |
| JS | `analytics.js` (clickable bars, placard, custom days), `panel.js` (remove the dead users block) |
| CSS | `analytics.css`, `panel.css` |
| Tests | `ADMIN/tests.py` |

## 8. Tests

- Non-admin gets 403 on every new endpoint.
- Overview figures equal the right `date_joined` windows (today / week / last month).
- Week endpoint: bad or future date returns 400; a Wednesday date snaps to its Sunday.
- Custom `days` and `months` match the numbers the named ranges already give.
- The shell still ships no numbers.
- Week start: ADMIN and STAFF return the same day for the same input.

## 9. Decisions (settled)

1. **Third overview tile** — **Stories published** (works today, no migration). Newsletter
   sign-ups can become a fourth tile later, once a newsletter date column exists.
2. **"Since last week"** — this week so far (Sunday→now) against **all** of last week
   (Sunday→Saturday). It can look weak early in the week; that is accepted.
3. **Badge placement** — top bar, next to the page title.

Other settled defaults:

- Keep the existing `analytics` URL name.
- Week = Sunday–Saturday from one constant `WEEK_START_WEEKDAY = 6`; `analytics.py` now uses
  it for the week-start helper and the stories/trends week buckets, so ADMIN and STAFF agree.
- "Active readers" = distinct accounts that opened a story (`ReadingHistory.read_at`), which
  matches the Members table's own activity filter. (Earlier note said `StoryView`; changed so
  the two agree.)
- Headline delta shows a sign **and** a colour (`+8`, `−3`, `0`) rather than colour only.
- Overview refreshes on page load only.
- Week placard rows: title (link), author, posted, updated — no views/likes line.
- Author-name button toast: `Author analytics is not built yet. It will live in Staff lytics.`
- `StoryView` write stays exactly as it is for now.
