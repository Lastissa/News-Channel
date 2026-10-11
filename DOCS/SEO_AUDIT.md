# SEO Audit — NoName (AbuReport) Django news site

**Date:** Sun Oct 11 2026
**Scope:** Read-only audit of every project HTML template (excluding vendored packages under `.noname/Lib/site-packages/**`). No template or source file was modified; this report is the only file written.
**Method:** Every project template was read and cross-checked against `HOME/templates/base.html`, the URL config (`NoName/urls.py`, app `urls.py`) and the views that render them (`HOME/views.py`, `BLOG/views.py`, `STAFF/views.py`). Findings quote the actual file and line.

A shared `<head>` lives in `HOME/templates/base.html`. Its defaults are:
- Title: `{{ project_name }} · {{ project_cachphrase }}` (line 9)
- Description: `" - {{ project_cachphrase }}"` — note the leading dash (line 10)
- Robots: `index, follow` (line 11) — pages opt out with `{% block meta_robots %}`
- Canonical + `og:url`: `{{ site_domain }}{{ request.path }}` (lines 13–14) — no query string
- Default `og:image` = site logo (line 53); `og:site_name`, `og:locale` (lines 12, 15)
- `NewsMediaOrganization` JSON-LD, only when `social_links` is truthy (lines 57–68)

---

## Top priority findings

1. **Author portfolio JSON-LD is broken (invalid Person schema on every portfolio page).** `STAFF/templates/staff/portfolio.html:22` emits `<script type="application/ld+json">{{ person_schema_json }}</script>` **without `|safe`**. `STAFF/views.py:400` returns a JSON string, so Django autoescapes every `"` to `&quot;` and the block is not valid JSON. The sibling template gets this right: `STAFF/templates/staff/editorial_team.html:21` uses `{{ team_schema_json|safe }}`. Highest-impact, one-character fix.

2. **Canonical / `og:url` ignore the query string, collapsing pagination and filtered views.** `HOME/templates/base.html:13-14` build the canonical from `request.path` only. So `/?category=News`, `/?q=...`, and `/?page=3` all declare `<link rel="canonical" href="https://…/">`, telling Google they are duplicates of the homepage. Category and search result pages are effectively de-indexed, and homepage pagination page 2+ is treated as page 1.

3. **Authentication pages are indexable and are not blocked.** `AUTHENTICATION/templates/auth/login.html`, `register.html` and `password_reset.html` set titles/descriptions but no `meta_robots`, so they inherit `index, follow` from `base.html:11`. `robots.txt` does **not** block them — `HOME/views.py:114` has `# "Disallow: /auth/",` commented out. Thin sign-in/sign-up pages can rank and dilute the site.

4. **No default Open Graph/Twitter tags on generic pages.** `base.html` emits only `og:site_name`, `og:url`, `og:locale`, `og:image`. There is no default `og:title`, `og:description`, `og:type`, or `twitter:card`. Pages that don't define them (`privacy_policy.html`, `promote.html`, `ARCHIVE/gallery.html`, both 404 pages, auth pages) produce incomplete/no share previews.

5. **"Unverified author" replaces a real published story with a soft 404 + noindex.** In `BLOG/views.py:351`, when a story's author has no `StaffProfile`, `StoryDetailView` renders `blog/staffprofile_404.html` with **HTTP 200** (no `status=404`), and that template sets `noindex, nofollow` (`staffprofile_404.html:7`). The result: a real, linked story URL returns 200, is unindexable, and its `<title>` is just `{{blog.heading}}` with no brand (`staffprofile_404.html:5`). Either 404 it properly or render the story.

6. **Admin pages don't opt out of indexing.** `ADMIN/templates/ADMIN/staff_create.html` and `ADMIN/templates/ADMIN/staff_detail.html` define no `meta_robots` block, so they inherit `index, follow`. Both also have no meta description (they fall back to the weak base default), and `staff_detail.html:4` titles as `{{ staff_display_name }} · Staff Data` with no project name. `ADMIN/panel.html` does this correctly (`panel.html:5`, `noindex, nofollow`). Note `/control/` **is** disallowed in robots.txt, which mitigates crawl-based discovery.

7. **Multiple `<h1>` on the homepage.** `HOME/templates/HOME/home.html` can render up to three `<h1>` elements in one document: the lead headline (`:56`), the empty-state (`:121`), and the headline block (`:167`). Exactly one `<h1>` per page is the expected structure.

8. **Weak default meta description, and pages that silently use it.** `base.html:10` renders `content=" - {{ project_cachphrase }}"` (leading `" - "`). `HOME/profile.html` and the two admin templates above omit `meta_description` and therefore ship this string.

9. **Missing `<h1>` on key pages.** `HOME/templates/HOME/profile.html`, `ADMIN/templates/ADMIN/panel.html`, and `AUTHENTICATION/templates/auth/gate.html` contain no `<h1>` at all (panel/gate use only `<h2>`/`<h3>`).

10. **Empty `alt` on meaningful images.** Content-bearing images ship `alt=""`: `STAFF/templates/staff/editorial_team.html:101` and `:115` (latest-story image and staff portrait), `STAFF/templates/staff/includes/editorial_cards.html:10` and `:54` (portrait and story thumbnail), `BLOG/templates/blog/story_detail.html:388` and `:390` (author "most viewed" thumbnails), `HOME/templates/includes/notfound_stories.html:9`, and `HOME/templates/HOME/partials/continue_rail.html:20`.

*(Secondary, still worth fixing: no `BreadcrumbList` or site-wide `WebSite`/`Organization` + `SearchAction` schema anywhere; no RSS/Atom feed; one empty/duplicate `og:image` emitted by `portfolio.html:18`; stale duplicate templates under root `templates/ARCHIVE/` that are never rendered — see the last section.)*

---

## Full inventory

Legend — **Public?**: Public / Auth-only / Staff-only / Admin-only / Fragment / N/A. **robots**: value actually emitted. **h1**: number of `<h1>` in the document. **alt**: quality of image `alt` on content images (Good / Partial / Empty / None). **JSON-LD**: schema types present.

| Template | Public? | Title | Meta description | robots | h1 | images alt | JSON-LD | Notes |
|---|---|---|---|---|---|---|---|---|
| `HOME/templates/base.html` | N/A (layout) | Default | Weak default (`" - …"`) | index, follow | — | n/a | NewsMediaOrganization (conditional) | Canonical/og:url omit query (`:13-14`); no default og:title/type/twitter |
| `HOME/templates/HOME/home.html` | Public | Yes (filter-aware) | Yes (good) | index, follow | 3 | Partial | None | Multiple `<h1>` (`:56,121,167`); `\|\|` typo in title/desc (`:9,21`); canonical collapses filters/pages |
| `HOME/templates/HOME/404.html` | Public (error) | Yes | Yes | index, follow (served 404) | 1 | None | None | Served with `status=404` (`HOME/views.py:80`), so noindex is implicit; could add noindex for clarity |
| `HOME/templates/HOME/privacy_policy.html` | Public | Yes | Yes (good) | index, follow | 1 | None | None | Strong, unique content; good candidate for breadcrumb schema |
| `HOME/templates/HOME/promote.html` | Public | Yes | Yes (good) | index, follow | 1 | None | None | Unique content; no OG/Twitter beyond base defaults |
| `HOME/templates/HOME/unsubscribe.html` | Public | Yes | Yes | noindex, nofollow | 4 (conditional) | None | None | `:77-86` four `<h1>` but only one renders per state — acceptable |
| `HOME/templates/HOME/profile.html` | Auth-only | Yes | **Default (weak)** | noindex, nofollow | 0 | Good (`:24`) | None | No `<h1>`; relies on base meta description |
| `HOME/templates/HOME/add_news.html` | Staff-only | Yes | Yes (short) | noindex, nofollow | 1 | Good | None | Editor UI |
| `HOME/templates/HOME/edit_news.html` | Staff-only | Yes | Yes (short) | noindex, nofollow | 1 | Good | None | Editor UI |
| `HOME/templates/HOME/author_handbook.html` | Staff-only | Yes | Yes (good) | noindex, nofollow | 1 | Good | None | Long-form help page, deliberately noindex |
| `HOME/templates/HOME/partials/_story_card.html` | Fragment | — | — | — | — | Good (`:6`) | None | Correct `alt` with fallback |
| `HOME/templates/HOME/partials/story_cards.html` | Fragment | — | — | — | — | — | None | Orchestrates card/rails |
| `HOME/templates/HOME/partials/continue_rail.html` | Fragment | — | — | — | — | Empty (`:20`) | None | "Continue reading" image `alt=""`; link not aria-hidden here |
| `HOME/templates/HOME/partials/trending_rail.html` | Fragment | — | — | — | — | — (JS-filled) | None | Rows injected by `most-viewed.js`; `hidden` until fetch |
| `HOME/templates/HOME/partials/profile_*.html` (11 files) | Fragment | — | — | — | — | — | None | Profile sub-lists; rendered inside noindex profile page |
| `HOME/templates/includes/navbar.html` | Fragment | — | — | — | — | Good (`:8`) | None | Logo has width/height |
| `HOME/templates/includes/footer.html` | Fragment | — | — | — | — | Good (`:6,101,102`) | None | Logo has width/height |
| `HOME/templates/includes/notfound_stories.html` | Fragment | — | — | — | — | Empty (`:9`) | None | Thumbnail wrapped in `aria-hidden` link; alt could still describe |
| `HOME/templates/includes/floating_social.html` | Fragment | — | — | — | — | None | None | Social dock |
| `HOME/templates/includes/newsletter_popup.html` | Fragment | — | — | — | — | None | None | Modal |
| `HOME/templates/includes/splash.html` / `splash_head.html` | Fragment | — | — | — | — | — | None | Boot splash |
| `BLOG/templates/blog/story_detail.html` | Public | Yes | `{{excerp}}` (no fallback) | index, follow | 1 | Partial | **NewsArticle (good)** | Hero lacks width/height (`:169`); empty alts (`:388,390`); `#` author links when no portfolio (`:95,101,237`); title uses `\|` not `·` |
| `BLOG/templates/blog/story_404.html` | Public (error) | Yes | Yes | index, follow (served 404) | 1 | Good | None | Rendered with `status=404` (`BLOG/views.py:316`), noindex implicit |
| `BLOG/templates/blog/staffprofile_404.html` | Public (error) | Heading only | Yes | noindex, nofollow | 1 | None | None | **Served HTTP 200** (`BLOG/views.py:351`) → soft 404; title lacks brand |
| `STAFF/templates/staff/portfolio.html` | Public | Yes | Yes | index, follow | 1 | Good | **Person (broken)** | `{{ person_schema_json }}` missing `\|safe` (`:22`); duplicate/empty `og:image` (`:18`) |
| `STAFF/templates/staff/editorial_team.html` | Public | Yes | Yes | index, follow | 1 | Empty (`:101,115`) | Organization+Person (good, `\|safe`) | Reference for correct schema rendering |
| `STAFF/templates/staff/includes/editorial_cards.html` | Fragment | — | — | — | — | Empty (`:10,54`) | None | Portraits/thumbnails `alt=""` |
| `STAFF/templates/staff/partials/portfolio_feed_items.html` | Fragment | — | — | — | — | Good | None | Author avatar + story image described |
| `STAFF/templates/staff/partials/portfolio_extras.html` / `social_icon.html` | Fragment | — | — | — | — | — | None | Feed markup / icon sprite |
| `AUTHENTICATION/templates/auth/login.html` | Public | Yes | Yes | **index, follow** | 1 | Good (`:10`) | None | Should be noindex; `/auth/` not in robots.txt |
| `AUTHENTICATION/templates/auth/register.html` | Public | Yes | Yes | **index, follow** | 1 | Good (`:11`) | None | Should be noindex |
| `AUTHENTICATION/templates/auth/password_reset.html` | Public | Yes | Yes | **index, follow** | 4 (states) | Good (`:10`) | None | Should be noindex |
| `AUTHENTICATION/templates/auth/gate.html` | Public (iframe) | Yes | **Missing** | noindex, nofollow (`:6`) | 0 | None | None | Standalone `<head>`; no `<h1>`; tabbed sign-in/sign-up |
| `AUTHENTICATION/templates/auth/endpoint_rate_limit.html` | Public (error) | Yes | Yes | noindex, nofollow | 1 | None | None | Good |
| `AUTHENTICATION/templates/csrf_fail.html` | Public (error) | Yes | Yes (base default? no — no block) | noindex, nofollow | 1 | None | None | No `meta_description` block → uses base default; noindex is what matters |
| `AUTHENTICATION/templates/yandex_1093315bd8192b90.html` | N/A (verify) | — | — | — | — | — | None | Search-engine verification file |
| `ADMIN/templates/ADMIN/panel.html` | Admin-only | Yes | **Default (weak)** | noindex, nofollow (`:5`) | 0 | Empty (`:79,192`) | None | No `<h1>`; correctly noindexed |
| `ADMIN/templates/ADMIN/staff_create.html` | Admin-only | Yes | **Default (weak)** | **index, follow** | 1 | None | None | Should be noindex; `/control/` is robots-disallowed |
| `ADMIN/templates/ADMIN/staff_detail.html` | Admin-only | Yes (no brand) | **Default (weak)** | **index, follow** | 1 | None | None | Should be noindex; title lacks project name |
| `ARCHIVE/templates/ARCHIVE/gallery.html` | Public | Yes | Yes | index, follow | 1 | Good | None | Correct template (resolved by app dirs) |
| `ARCHIVE/templates/ARCHIVE/partials/gallery_grid.html` | Fragment | — | — | — | — | Good (`:34`) | None | Uses real `alt` + width/height |
| `ARCHIVE/templates/ARCHIVE/partials/manage_row.html` / `manage_list.html` / `manage_modal.html` / `manage_rows_page.html` / `upload_modal.html` | Fragment | — | — | — | — | Mixed (`manage_row:6` good, `upload_modal:29` is preview) | None | Modal/management fragments |
| `templates/ARCHIVE/gallery.html` + `templates/ARCHIVE/partials/{gallery_grid,manage_row,upload_modal}.html` | N/A (dead) | Yes | Yes | — | 1 | — | None | **Stale duplicates** — `TEMPLATES.DIRS=[]` + `APP_DIRS=True`, so only `ARCHIVE/templates/…` resolves |

---

## Per-template details

### HOME app

**`HOME/templates/base.html`** (shared layout)
- Default title `{{ project_name }} · {{ project_cachphrase }}` (`:9`) and description `" - {{ project_cachphrase }}"` (`:10`, leading dash) are weak fallbacks.
- Canonical and `og:url` drop the query string (`:13-14`), collapsing pagination/filter URLs.
- Robots default `index, follow` (`:11`).
- No default `og:title`, `og:description`, `og:type`, or `twitter:card`.
- `og:image` block is nested inside `extra_head` (`:50-56`); templates that override `extra_head` without `{{ block.super }}` lose the default image. All current overriders call `block.super`.
- `NewsMediaOrganization` JSON-LD only when `social_links` is truthy (`:57-68`); has `name`/`url`/`logo` but no `sameAs` and no logo dimensions.

**`home.html`**
- Title block is filter-aware but has a double-pipe typo: `Latest On {{ active_category|title }} |  | {{project_name}}` (`:9`) and `… | | {{project_name}}` in the description (`:21`).
- Up to three `<h1>` (`:56`, `:121`, `:167`).
- Trending rail is fetched client-side and `hidden` until JS resolves; image adverts are CSS `background-image` (no `<img>`/alt). `_story_card.html` images have proper `alt`.

**`404.html`** — `handler404` renders it with `status=404` (`HOME/views.py:80`), so it is not indexed despite the default robots value. No `<img>` besides the `notfound_stories` include.

**`privacy_policy.html` / `promote.html`** — Good unique titles, descriptions and `<h1>`; solid candidates for `BreadcrumbList`/`WebPage` schema.

**`unsubscribe.html` / `profile.html` / `add_news.html` / `edit_news.html` / `author_handbook.html`** — All correctly `noindex, nofollow`. `profile.html` has no `<h1>` and no meta description (inherits the weak default). `unsubscribe.html` has four `<h1>` but only one renders per state.

### BLOG app

**`story_detail.html`**
- Meta description is `{{excerp}}` with no fallback (`:5`) — if the excerpt is empty the tag is empty.
- Strong `NewsArticle` JSON-LD (`:31-54`) with headline, dates, author (linked to portfolio when available), publisher and `mainEntityOfPage`.
- Hero image has `alt="{{ blog.heading }}"` but **no `width`/`height`** (`:169`) → avoidable CLS.
- Author "most viewed" thumbnails use `alt=""` (`:388`, `:390`).
- Author links fall back to `href="#"` when there is no portfolio URL (`:95`, `:101`, `:237`), creating dead in-page links.
- Title separator is ` | ` while the rest of the site uses `·` (`:4`).

**`story_404.html`** — Served with `status=404` (`BLOG/views.py:303`, `:316`); no `meta_robots` block, but the 404 status handles de-indexing. Could add `noindex` for belt-and-braces.

**`staffprofile_404.html`** — Rendered with HTTP 200 when a story's author lacks a `StaffProfile` (`BLOG/views.py:346-351`): a soft 404. Combined with `noindex, nofollow` (`:7`) the story becomes invisible to search. Title is only `{{blog.heading}}` (`:5`). The `extra_head` OG block only renders when `not author_profile` (`:12`), which is always true on this path.

### STAFF app

**`portfolio.html`**
- `{{ person_schema_json }}` lacks `|safe` (`:22`) → invalid JSON-LD (fix: `|safe`).
- `og:image` handling emits an unconditional `<meta property="og:image" content="">` (`:18`) in addition to the base default, so a page can carry an empty/duplicate `og:image`.
- Otherwise strong: unique title/description, single `<h1>`, descriptive alts, `profile`-type OG.

**`editorial_team.html`**
- Correct `{{ team_schema_json|safe }}` (`:21`) — the working reference for `portfolio.html`.
- Content images use `alt=""` (`:101`, `:115`).
- Unique title/description and single `<h1>`.

**`includes/editorial_cards.html`** — Portraits and thumbnails `alt=""` (`:10`, `:54`); has `width`/`height`.

**`partials/portfolio_feed_items.html`** — Good descriptive alts.

### AUTHENTICATION app

- `login.html`, `register.html`, `password_reset.html`: unique titles/descriptions, one `<h1>`, logo alt, but **no `noindex`** and not blocked by robots.txt.
- `gate.html`: standalone document, `noindex, nofollow` (`:6`), but no `meta_description` and no `<h1>`.
- `endpoint_rate_limit.html` and `csrf_fail.html`: correctly `noindex, nofollow` with `<h1>` (csrf_fail has no `meta_description` block and uses the base default).
- `yandex_1093315bd8192b90.html` is an engine verification file, not a page.

### ADMIN app

- `panel.html`: `noindex, nofollow` (`:5`); no `<h1>` (uses `<h2>`/`<h3>`); no meta description.
- `staff_create.html`, `staff_detail.html`: no `meta_robots` override → `index, follow`; no meta description; `staff_detail.html` title lacks the project name. They live under `/control/`, which robots.txt disallows, limiting crawl-based discovery.

### ARCHIVE app

- `ARCHIVE/templates/ARCHIVE/gallery.html` is the live template (resolved via `APP_DIRS`); unique title/description, `<h1>`, and grid images use real `alt` plus `width`/`height` (`partials/gallery_grid.html:34`).
- The viewer `<img … alt="">` (`gallery.html:115`) is a modal preview — acceptable.
- Root-level `templates/ARCHIVE/*` are stale duplicates that are never rendered (settings use `TEMPLATES.DIRS = []`); they risk future edits being made on the dead copy.

---

## Opportunities

- **`robots.txt` — present and working.** `HOME/views.py:101-121` serves `/robots.txt`, disallowing `/_admin/`, `/control/`, `/sy/`, `/profile/`, `/load-more/`, and pointing to `Sitemap: {domain}/sitemap.xml`. Note `/auth/` is commented out (`:114`), so auth pages remain crawlable.
- **`sitemap.xml` — present and working.** `HOME/views.py:124-175` builds a hand-rolled sitemap: home, privacy, promote, archive gallery, up to 2,000 stories (`lastmod` from `last_updated`/`date_created`), and every active staff portfolio. Template: `HOME/templates/HOME/sitemap.xml`. Improvements: add `lastmod` to the static entries, and consider splitting large story sets into a sitemap index.
- **Add `BreadcrumbList` JSON-LD.** None exists anywhere. Story pages could carry `Home > Category > Story`; portfolios `Home > Editorial team > Author`.
- **Add site-wide `WebSite` + `SearchAction` and `Organization` with `sameAs`.** `base.html:57-68` only renders a minimal `NewsMediaOrganization` and only when `social_links` is set; there is no `sameAs`, `contactPoint`, or logo dimensions.
- **Add an RSS/Atom feed** for the news sections and link it via `<link rel="alternate" type="application/rss+xml">`; none exists.
- **Fix the canonical strategy** so filtered/paginated URLs either self-canonicalize (if they are meant to rank) or are `noindex` (if not) — currently they all point at `/`.
- **Add `noindex` to auth and admin pages** and enable the `Disallow: /auth/` line in `RobotsTxtView` if auth pages are not meant to rank.
- **Delete the dead root `templates/ARCHIVE/*` duplicates** to prevent future edits on unreachable files.
- **Consider `image`/`thumbnailUrl` and `width`/`height`** on the `NewsArticle` and `Person` schemas, and add `width`/`height` to `story_detail.html:169`.
