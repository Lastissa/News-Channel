# PREP-ADSENSE — AbuReport AdSense readiness plan

**Project:** AbuReport (NoName Django news site) · https://abureport.com.ng
**Date:** Wed Oct 14 2026
**Type:** Preparation plan (not the application itself)
**Reference:** an external readiness assessment of the public homepage against Google's AdSense eligibility and monetization guidance. That assessment is an opinion, not Google's decision; it is used here only as a starting checklist.

---

## Why this document exists

We intend to apply to Google AdSense. Before we apply, we need one place that:

1. **Records the criteria** Google actually judges (original content, privacy disclosures, transparency, usability, technical crawlability, ad-policy compliance) so nothing is missed.
2. **Separates the work into independent segments**, so each change is made, reviewed and verified on its own — never mixed into one blur of edits.
3. **Shows the current state and the owner of each open item**, so we can see at a glance what blocks the application.

The goal is not to guess whether Google will approve. The goal is to remove the fixable reasons it might reject, one segment at a time.

---

## How to use this file

- **One segment = one task = one execution.** Do the segment completely, verify it, then stop. Do not work two segments in the same execution.
- **Work top to bottom.** Segment 1 (privacy) is the highest-value concrete gap and should go first.
- **Every segment is self-contained.** It lists its own goal, why Google cares, where the work lives, the deliverable and the definition of done.
- **Update status in this file** as each segment finishes: set its status and note the exact files touched.
- **No bundling.** If a segment reveals extra work, log it as a new segment rather than hiding it inside this one.

**Status key:** ☐ pending · ◐ in progress · ☑ done · ✗ not applicable

---

## Segment map

| # | Segment | Priority | Blocks AdSense? | Status |
|---|---------|----------|-----------------|--------|
| 1 | Privacy-policy ad disclosures | P1 | Yes — clearest gap | ☑ |
| 2 | Article content audit | P2 | Yes | ◐ |
| 3 | Publication transparency pages | P3 | Yes | ☑ |
| 4 | Mobile experience & readability | P4 | Can | ☑ |
| 5 | Technical crawl & indexing | P5 | Yes | ☑ |
| 6 | Ad / traffic policy hygiene | P6 | Yes | ☑ |
| 7 | Accessibility semantics | P7 | No | ☐ |
| 8 | Story-page layout shift (logged from Segment 5) | P4 | Can | ☐ |

---

## Segment 1 — Privacy-policy ad disclosures

**Goal.** Make the privacy policy name Google and third-party advertising explicitly, so it satisfies Google's publisher requirement for data-collection disclosure.

**Why Google cares.** AdSense policy requires publishers to disclose that third parties (including Google) may use cookies, web beacons, IP addresses and similar technologies to serve and measure ads, and to tell users how to control them.

**Where.** `HOME/templates/HOME/privacy_policy.html` (rendered at `/privacy-policy/`). Confirm the route in `HOME/urls.py`.

**Single-execution task.**
1. Read the current advertising/cookies section of the policy.
2. Add, in plain language:
   - Google and other third-party vendors use cookies to serve ads based on past visits to this site and others.
   - Use of advertising cookies (e.g. the DoubleClick cookie) enables Google and its partners to serve ads to our readers.
   - IP addresses, web beacons or similar technologies may be collected.
   - Readers can opt out via Google Ads Settings and `www.aboutads.info`.
   - A link to "How Google uses information from sites or apps that use our services".
3. Match wording to services actually used (do not claim services we do not run).

**Deliverable.** Updated privacy policy text.

**Definition of done.** The page names Google advertising cookies, third-party ad serving, identifiers, an opt-out, and the Google data-use link — and the wording is true for AbuReport.

**Result (done 14 Oct 2026).** `HOME/templates/HOME/privacy_policy.html` — the "Advertising and analytics" section gained the Google/third-party disclosure (cookies, ad settings opt-out, `aboutads.info`, the Google data-use link), guarded by a single switch:

```
{% with show_google_ads=True %}
  ...disclosure...
{% endwith %}
```

- `True` → disclosure shown (needed while AdSense runs).
- `False` → disclosure hidden; the section is exactly the regular policy again. No other file, route or setting is involved — one line, one edit.
- The policy's "Last updated" date was moved to 14 October 2026 to match the change.

---

## Segment 2 — Article content audit

**Goal.** Confirm published stories are original, accurate and genuinely useful.

**Why Google cares.** "Helpful content" / spam policies penalise mass-produced summaries. AI assistance is allowed; low-value content is not.

**Where.** A representative sample across categories, plus the newest stories. Editor handbooks already exist: `DOCS/NEWS_CONTENT_CONVENTION.MD`, `DOCS/DOC-FOR-STAFF.MD`.

**Single-execution task.**
1. Pick a fixed sample (e.g. the newest 10 stories plus 2 per major category).
2. For each, check originality (not a rewrite), accuracy (names, dates, figures, deadlines), sourcing and depth.
3. Correct or remove problematic material.

**Deliverable.** A short findings list, with the sample used and corrections made.

**Definition of done.** Every sampled story is original, verifiable and adequately sourced; problem items are fixed or removed.

**Result (audited 14 Oct 2026 against PRODUCTION — https://abureport.com.ng).**
> Correction: an earlier pass of this segment read the **local dev database** by mistake. That data is not production and is fully superseded by the production audit below.

Sample = 8 live stories fetched in full, across 8 categories (ids 66, 42, 40, 7, 63, 55, 60, 38), plus the complete `sitemap.xml` and homepage listing. About 55 stories are live (sitemap entries), 23 Sep – 13 Oct 2026, by two named authors (Opeyemi, ABU SUĀD).

**Corpus shape (production).** Word counts printed on each story page: 40 = 129, 60 ≈ 130, 63 = 150, 66 = 199, 7 = 199, then 42 = 642, 55 = 571, 38 = 595. Most of the sample sits at **130–200 words**; only some reach 550-650.

**Findings.**

1. **Short, single-source rewrites dominate.** 63 (150 words) cites only Punch; 38 cites only one history site; 40 is a rewrite of one tweet (`Source: Ash-Aar (@YesItsBash) on X`); 60 rewrites a JAMB social post. This is the "duplicated/aggregated, little added value" pattern AdSense rejections cite most.
2. **Padding / hollow sentences.** Story 66 carries: *"Although the specific challenges she encountered during her studies have not been independently documented, her accomplishment provides an opportunity to recognise the dedication involved..."* — filler a reviewer reads as low value.
3. **Self-promotional pieces are filed as news.** Story 7 (`ABUREPORT: PLATFORM FOR RELIABLE UP-TO-DATE NEWS`) is an about-us puff piece in General; story 40 is effectively a brand promotion for "Item 7". Both read as ads dressed as editorial.
4. **Sloppy links in body copy.** Story 42 has `?utm_aource=` (typo) and source links with appended `?abureport.com.ng` / `?utm_source=`; story 63's source is a bare `https://punchng.com/?abureport.com.ng`; the author social link is `https://x.om/lastissa/` (x.om typo).
5. Minor: the story page prints a public **"Word count"** and view counter; the nav has a dead `ServicesSoon` placeholder.

**Strengths.** Real Nigerian education/news topics, clear headlines, good structure where developed (55 and 42 have summary blocks and subheads), sources named on several pieces, and editorial-team + author pages exist.

**Required action (editorial — owner).** Hold every story to a consistent **~300+ word original body** (expand or merge the 130–200 word ones); require at least one explicit source line and, where possible, a second independent source; move the self-promo pieces (7, 40) out of the news feed; add the padding and typo-link checks to the editorial checklist. Nothing was changed by this audit.

**Enforcement added (14 Oct 2026 — code).** Two of the audit follow-ups are now implemented:
- **A — convention updated.** `DOCS/NEWS_CONTENT_CONVENTION.MD` gains an **Editorial quality rules** section (≈300-word target, name the source, originality, no filler, no self-promo in news) plus two writer bullets.
- **Enforcement at Add News.** `SERVICE_INTERNAL/story_validation.py` now **blocks** a body under 100 words and **warns** (author must confirm) below the 300-word target or when no source is named. The same rule is shown in the Add News formatting guide and in the author handbook.
- **B — sitemap.** `HOME/views.py` (`SitemapXmlView`) now omits configured categories that hold no stories, so Google is not asked to index empty category pages.

**Still open — the editorial clean-up itself (owner: editor, on PRODUCTION).** The code now prevents *new* short/sourceless posts, but the existing corpus is untouched. To close Segment 2:
1. **Expand or merge the short stories.** Most of the ~55 live stories sit at 130–200 words; bring each up to a real ~300-word body (add the who/what/when/where, context and a second angle).
2. **Remove the self-promo pieces from news.** Story 7 (`ABUREPORT: PLATFORM FOR RELIABLE UP-TO-DATE NEWS`) and story 40 ("Item 7" promo) — delete, unpublish, or re-file outside a news category.
3. **Fix the sloppy links.** Story 42 `?utm_aource=` typo and the `?abureport.com.ng` / `?utm_source=` suffixes; story 63 bare `https://punchng.com/?abureport.com.ng`; author social `https://x.om/lastissa/` → `x.com`.
4. **Add a second independent source** where a story leans on one only (e.g. 63, 38, 40, 60).
5. **Minor page cleanup** (may belong to Segment 5, not here): drop the public "Word count" and view counter from the story page and remove the dead `ServicesSoon` nav item.

Segment 2 can be marked ☑ once the live stories pass 1–4.

---

## Segment 3 — Publication transparency

**Goal.** Leave no doubt who runs the site and how it reports.

**Why Google cares.** Trust and transparency are part of the quality signal for a news publisher.

**Where.** `HOME/templates/HOME/about.html`; `STAFF/templates/staff/editorial_team.html`; author portfolio pages (`STAFF/templates/staff/portfolio.html`); footer/masthead (`HOME/templates/includes/`). Contact emails already surface in the footer.

**Single-execution task.**
1. Verify an About page, an Editorial Team page, and author bios are reachable and informative.
2. Add an editorial/corrections guideline if missing.
3. Confirm contact routes work.

**Deliverable.** A list of any missing page or empty bio, plus the fixes.

**Definition of done.** About, editorial team, at least one author bio and a contact path are all live and non-empty.

**Result (audited 14 Oct 2026 against PRODUCTION — https://abureport.com.ng).**

All three routes were fetched live and read in full: `/about/`, `/editorial/`, and `/portfolio/opeyemi/`.

- **About page — present and informative.** Real prose ("Easily access the major news of the day…", how we verify and link sources), plus a Contact block with three mailto routes (`support@abureport.com.ng` general, `tech@abureport.com.ng` corrections, `partner@abureport.com.ng` partnerships) and a privacy-policy link. ✅
- **Editorial team — present and informative.** Two named journalists, real counts (62 published stories), an "Author Of The Week" card and a portrait grid. ✅
- **Author bios — live and non-empty.** The editorial page renders each member's bio (ABU SUĀD and Opeyemi), and the "How we report" section states the corrections approach ("Corrections are made when errors are identified"). ✅
- **Editorial/corrections guideline — present.** "Our approach → How we report" already covers verification, sourcing and corrections; there was nothing to add. ✅
- **Contact routes — live.** The footer and the About page both expose working mailto addresses; no dead contact route found. ✅

**One gap found and fixed (code).** The author's **own portfolio page** did not show the bio at all: the `Profile` card sat inside a retired `{% if False %}` analytics block in `STAFF/templates/staff/portfolio.html`, even though `StaffProfile.bio` is still fed by the view and used for the page's meta description and Person schema. That `Profile` card was moved out of the dead block into the live layout, reusing the existing `.portfolio-card` / `.portfolio-prose` styles, so an author page now states who the author is. An empty bio renders no card. (The separate editors' "endorsement" card that sat beside it was intentionally dropped — it is not wanted on the author page.)

**Tests.** `STAFF/tests.py`: two new tests cover the bio card (shown when set, omitted when empty). The two stale asset-version assertions on these same pages (`portfolio-feed.js?v=…`, `editorial_team.css?v=…`) were switched to `static(...)` so they follow the hashed manifest names — the last two pre-existing failures in the STAFF suite. `manage.py test STAFF` → 21 tests, OK.

**Logged for another segment (not fixed here).** The author portfolio still exposes a personal email (`LASTISSA11@GMAIL.COM`) rather than an `@abureport.com.ng` address, and still links `https://x.om/lastissa/` (x.om typo); both already sit under Segment 2's link/self-promo clean-up.

---

## Segment 4 — Mobile experience & readability

**Goal.** Make the site pleasant and legible on a phone.

**Why Google cares.** Poor UX and low-contrast text undermine the quality signal and reader retention.

**Where.** `HOME/static/home/css/base.css` and per-app CSS; the theme tokens; layout-shift sources in templates.

**Single-execution task.**
1. Load home, a story, a category and search on a phone (or DevTools device mode).
2. Check text contrast, font size, image loading, layout shift and intrusive overlays.
3. Fix the confirmed issues only.

**Deliverable.** A before/after note of the fixes.

**Definition of done.** No confirmed contrast, legibility or layout-shift blocker remains on the tested pages.

**Result (audited 14 Oct 2026 against PRODUCTION — https://abureport.com.ng).** No code change was required: none of the five checks confirmed a blocker.

Tested at a 390 px phone viewport (the site's own HTML rendered in a 390px frame, so its media queries applied) and with Lighthouse (accessibility / best-practices / SEO) on home `/`, a story (`/story/fg-unveils-2026-agreements-with-ssanu-nasu-other-tertiary-staff-unions-67/`), `/category/university/` and `/search/?q=nigeria`.

- **Text contrast — pass.** Lighthouse first flagged three story-page items (read-also meta text and a headline), but those are the read-also **entrance animation caught mid-flight** (the cards fade in from `opacity: 0`): the reported foregrounds `#828e9b`/`#c4c9d0`/`#a8acb3` are exactly `--slate`/`--ink` blended with white at 76%/36% opacity. In the settled state the rendered colours are `--slate` `#5B6B7C` (5.47:1 on white) and `--ink` `#0E1B2C` — both pass AA. Home, category and search pages were clean.
- **Font size — pass.** Story body renders at 16px / 24px line-height; meta and labels sit at 10–13px (tags, timestamps, view counts, bylines), which is conventional and legible.
- **Image loading — pass.** 15 of 18 story images carry `loading="lazy"`, every image has an `alt`, and each sits in a fixed box (Lighthouse `image-aspect-ratio` / `image-size-responsive` pass).
- **Layout shift — pass.** Images use fixed CSS boxes / `aspect-ratio`; no CLS source was found.
- **Intrusive overlays — reviewed, accepted as-is.** The home page's "Continue reading" sheet auto-opens 6 seconds after load and, on a phone, covers **94%** of the viewport (369×822, a 16px strip left at the top) — the intrusive-interstitial pattern. The owner reviewed this and chose to keep the feature unchanged (12-hour cooldown), so no change was made. The separate newsletter sheet is scroll-gated (40%) and was not a concern.

No horizontal overflow was found on any tested page at 390px (document `scrollWidth` ≤ viewport). The desktop-only Lighthouse `target-size` hit on the hero carousel dots does not apply on phones: there the dots are 12px with a 30px hit area (the `::after { inset: -9px }` rule), which clears the 24px minimum.

**Logged for a new segment (not fixed here).** The Lighthouse pass also surfaced accessibility-semantics gaps outside this segment's mobile-UX scope: the continue sheet's `aria-labelledby` points at a commented-out heading (so the dialog has no accessible name); several icon-only links/buttons have no accessible name (home trending thumbnails, story author-social icons, the copy-link button); a `label-content-name-mismatch` on the bookmark/like chips; and a heading-order jump on category/search. Recorded as **Segment 7**.

---

## Segment 5 — Technical crawl & indexing

**Goal.** Prove Google can find and read every important page.

**Why Google cares.** Un-crawlable or accidentally `noindex` content is not eligible.

**Where.** `robots.txt`, sitemap, the `noindex`/canonical blocks in `HOME/templates/base.html`; Search Console.

**Single-execution task.**
1. Inspect story, category, home and privacy URLs.
2. Confirm the sitemap processes and `robots.txt` is not blocking needed paths.
3. Check for broken links, server errors and accidental `noindex`.
4. Run PageSpeed Insights on a story and the homepage.

**Deliverable.** A crawl report: URLs checked, status codes, verdicts.

**Definition of done.** Key pages return 200 and are indexable; the sitemap is accepted; no accidental block remains.

**Result (audited 14 Oct 2026 against PRODUCTION — https://abureport.com.ng).**

**Crawlable and indexable — all green.** Every key page type was fetched live and returned `200` with `<meta name="robots" content="index, follow">` and a correct self-canonical: `/`, `/story/<slug>/`, `/category/<slug>/`, `/archive/`, `/about/`, `/privacy-policy/`, `/editorial/`, `/portfolio/<slug>/`. ✅

- **No broken links or server errors.** All 52 internal links on the homepage return `200`. Unknown slugs return a real `404`. Out-of-range paging (`/category/university/?page=2`) returns `404` by design — the category fits one 25-story page and paging uses crawlable `<a href="?page=N">` links.
- **Canonical dedup works.** A story fetched with `?utm_source=facebook` canonicalises to the clean story URL, so tracking links do not split ranking. ✅
- **`robots.txt` — correct.** `200`, `text/plain`, served in 249 ms; disallows only `/_admin/`, `/control/`, `/sy/`, `/profile/`, `/load-more/` and (added 14 Oct) `/promote-ads/`, the promote page's fragment feed, and declares the sitemap. No needed path is blocked. ✅
- **`sitemap.xml` — valid, 84 URLs.** `200`, `application/xml`, well-formed: home, about, privacy, promote, archive, 11 categories, 66 stories and 2 portfolios. ✅

**Two sitemap defects found and fixed (code).**

1. **`/editorial/` was missing.** The live "who reports this and how" trust page — the E-E-A-T sibling of `/about/` and `/privacy-policy/`, both of which *are* listed — was absent from the sitemap. `HOME/views.py` (`SitemapXmlView`) now lists it; test added to `HOME/tests.py`.
2. **`/promote-your-bussiness/` was listed but returned a 17-byte `"still in progress"` stub.** A complete `HOME/promote.html` (the ₦2,000/month sponsored-banner offer) existed and `PromoteView` still had its `return render(..., "HOME/promote.html")`, but a single stray line added 7 Oct (`return HttpResponse("still in progress")`) sat in front of it as unreachable code — so the footer banner and the advert "coming soon" page both led to a blank page. The stray line is removed, the real offer page renders, and a test locks it in. *Subsequently redesigned (14 Oct):* the ₦2,000 offer copy was itself out of date, so `HOME/promote.html` is now a "still in progress" hero (`promote.jpg`, a pulsing in-progress indicator) with a direct `mailto:` to the partnership mailbox (free for the first two weeks), plus a live advert gallery loaded by GET (`PromoteAdsView` → `HOME/promote_ads.html`) that starts on a shimmer skeleton and falls back to tagged example creatives when no advert is live.

**PageSpeed Insights (mobile, Moto G Power, Slow 4G, Lighthouse 13.5).**

| Page | Perf | A11y | Best-practices | SEO | FCP | LCP | TBT | CLS | SI |
|------|------|------|----------------|-----|-----|-----|-----|-----|-----|
| Homepage | 61 | 90 | 100 | 92 | 3.3 s | 6.6 s | 60 ms | 0.057 | 15.9 s |
| Story | 65 | 92 | 100 | 100 | 1.7 s | 3.0 s | 0 ms | **1.06** | 5.4 s |

- The homepage's SEO `92` is a transient PSI-side timeout fetching `robots.txt`; the file was re-fetched directly and serves correctly in 249 ms.
- **Story-page CLS is 1.06 (target < 0.1).** The failed Lighthouse audit is *"Image elements do not have explicit width and height"* — a real Core Web Vitals defect the Segment 4 pass missed. Logged as **Segment 8**, not fixed here.

**Not changed (deliberate).** `/search/?q=…` is `index, follow` with the query kept in its canonical, and is explicitly unit-tested that way. Left as designed, but noted as a thin-content / crawl-budget risk for an owner call.

**Owner action outside this session.** Search Console: submit `sitemap.xml` and confirm the property — cannot be done from the repo.

---

## Segment 6 — Ad & traffic policy hygiene

**Goal.** Keep the account safe once live.

**Why Google cares.** Self-clicks, incentivised clicks, bought traffic and unlabelled promotions are program-integrating violations.

**Where.** Editorial/promotional processes; partner/advertising surfaces elsewhere in the site.

**Single-execution task.**
1. Confirm no self-clicks or click incentives.
2. Confirm no artificial traffic.
3. Confirm paid/promotional content is clearly labelled and does not swamp editorial.

**Deliverable.** A short compliance note.

**Definition of done.** The three points above are confirmed and documented.

**Result (audited 14 Oct 2026 — code sweep + live production).** All three checks pass.

1. **No self-clicks or click incentives.** No code path clicks an advert: the only `.click()` calls in the project target the editors' hidden image-file input and copy buttons, never an ad. No copy anywhere invites readers to click ads to support us, and no feature trades a reward (points, unlocks, extra content) for a click — search for reward/unlock/points/earn language returns only unrelated matches (SVG `points`, form `unlock`, editor terms). The ad surfaces are ordinary links to the advertiser's URL.
2. **No artificial traffic.** Nothing reloads or auto-fetches an ad-bearing page: no `<meta http-equiv="refresh">`, and no page `prefetch`/`prerender` (only the first hero/teaser **image** is preloaded and the fonts are preconnected). The only `location.reload()` calls run after a real login/logout/gate action. The hero and teaser carousels rotate slides with `setInterval` — a UI rotation that neither loads a page nor reloads an ad. The story view counter increments server-side on a real GET and explicitly ignores bot User-Agents (`SERVICE_INTERNAL/abstract.py:is_bot_request`). The only outbound automation is the IndexNow ping and the archive image proxy; neither touches our own pages. The AdSense loader is included on the **homepage template only** (`HOME/templates/HOME/home.html`), so ad impressions accrue only on genuine homepage views.
3. **Paid/promotional content is labelled and does not swamp editorial.** The hero-teaser carousel is the homepage's paid surface: it carries `aria-label="Adverts"` and every advert link carries `rel="sponsored noopener"`. The thin strip at the very top is an **announcements** bar (it was mislabelled "AD CENTER"), so it is no longer marked "Sponsored" and its links carry no sponsored rel. Google's own units are rendered and labelled by Google (AdChoices). On the live homepage the paid surface is small beside the news — a ~3-slide teaser + **2** Google Auto-ad units against **~36 story cards**, and story / category / search pages carry no Google ads at all.

**Fixed (code).** The announcement bar's house fallback — shown only when no announcement is live — pointed at a malformed `https:localhost:8000/missing/` URL with a "Bussiness"/"Clicking HERE" typo. It now reads *"Put your business in front of our readers — partner with us"* and links to the `/promote-your-bussiness/` page. Locked by a test (`HOME/tests.py`).

**Advisory (owner call, no code change).** The direct-sold hero-teaser carousel is labelled for search (`rel="sponsored"`) and for assistive tech (`aria-label="Adverts"`), but carries no **visible** "Ad"/"Sponsored" text tag on desktop. This is not an AdSense blocker — Google's own units are labelled by Google, and `rel="sponsored"` satisfies the paid-link disclosure — so it was left as-is; the advert slides already carry a small visible "AD" chip on mobile, and a matching desktop chip was added later (see the dev log).

**Stays under Segment 2 (not fixed here).** The self-promotional *editorial* stories (7 & 40) still sit in the news feed; removing/labelling them is part of the Segment 2 content clean-up, not an advertising surface.

**Tests.** `HOME` = **115 tests**, only the 5 known pre-existing failures. New: the ticker fallback + ad-surface labelling assertions.

---

## Segment 7 — Accessibility semantics (logged from Segment 4)

**Goal.** Give interactive controls and dialogs accessible names, and keep heading order sane.

**Why it matters.** Not an AdSense blocker on its own, but controls with no accessible name are unusable to screen-reader users and depress Google's quality/Lighthouse signals.

**Where (all found by the Segment 4 Lighthouse pass).**
1. `HOME/templates/HOME/partials/continue_popup.html` — the sheet's `aria-labelledby="continue-popup-title"` points at a heading that is commented out, so the dialog has no accessible name.
2. Icon-only links/buttons with no accessible name: home trending thumbnails (`.trending-media`, `tabindex="-1"`), story author-social icons, the story copy-link button (`.share-btn-copy`).
3. `label-content-name-mismatch` on the bookmark chips (`aria-label="Save story"` vs visible "Read later") and the like chip.
4. Heading-order jump on `/category/.../` and `/search/`.

**Deliverable.** The four items fixed and re-checked with Lighthouse.

**Definition of done.** Lighthouse accessibility reports no `aria-dialog-name`, `link-name`, `button-name` or `label-content-name-mismatch` failures on home and a story; heading order is sequential on category/search.

**Status.** ☐ pending — non-blocking; do after the required segments.

---

## Segment 8 — Story-page layout shift (logged from Segment 5)

**Goal.** Bring the story page's Cumulative Layout Shift under 0.1.

**Why Google cares.** CLS is a Core Web Vitals metric. At 1.06 the story page is roughly ten times over Google's "good" threshold, which depresses page-experience signals and is exactly the kind of unstable, moving layout AdSense reviewers dislike.

**Where.** `BLOG/templates/blog/story_detail.html` and its partials. The failing Lighthouse audit is *"Image elements do not have explicit width and height"*; PSI also flags "Improve image delivery (43 KiB)" and render-blocking / unused CSS.

**Single-execution task.**

1. Give every story-page image explicit `width`/`height` (or an `aspect-ratio` box) so space is reserved before it loads.
2. Re-run PSI on the same story (mobile) and confirm CLS < 0.1.

**Deliverable.** The resized images and a re-run PSI score.

**Definition of done.** Story-page mobile CLS ≤ 0.1 and the "explicit width and height" audit passes.

**Status.** ☐ pending.

---

## Status log

| Date | Segment | Change | Status |
|------|---------|--------|--------|
| 14 Oct 2026 | 1 — Privacy-policy ad disclosures | Added Google/third-party advertising disclosure behind a `show_google_ads` switch in `HOME/templates/HOME/privacy_policy.html`; bumped "Last updated" to 14 Oct 2026 | ☑ |
| 14 Oct 2026 | 2 — Article content audit | First pass accidentally read the local DB (void). Re-audited **production**: 8 stories fetched across 8 categories + sitemap. Majority are 130–200-word single-source rewrites; padding in story 66; self-promo stories 7 & 40 in the news feed; typo links. ~55 stories live. Editorial fixes listed, none actioned | ◐ |
| 14 Oct 2026 | 2 — Enforcement (A + B) | Updated `DOCS/NEWS_CONTENT_CONVENTION.MD` with editorial rules; `SERVICE_INTERNAL/story_validation.py` blocks <100-word bodies and warns <300 words / no source; Add News guide + author handbook updated; `SitemapXmlView` skips empty categories; tests refreshed for the new rule | ◐ |
| 14 Oct 2026 | 4 — Mobile experience & readability | Audited **production** at a 390px viewport + Lighthouse on home, a story, category and search. No code change: contrast passes (the Lighthouse hits were the read-also entrance animation mid-flight), story body is 16px, images are lazy + sized, no CLS source, no horizontal overflow. The 6s "Continue reading" sheet covers 94% of a phone screen but the owner reviewed it and **kept it as-is**. The desktop-only hero-dot target-size hit does not apply on phones (30px hit area). Accessibility-semantics gaps logged as Segment 7 | ☑ |
| 14 Oct 2026 | 5 — Technical crawl & indexing | Crawled **production**: every key page is `200` + `index, follow` + canonical; 52/52 homepage links live; `robots.txt` correct; `sitemap.xml` valid (84 URLs). Fixed: `/editorial/` added to the sitemap; `PromoteView`'s stray `"still in progress"` stub removed so `HOME/promote.html` renders. PSI mobile — home 61/90/100/92, story 65/92/100/100. Story CLS 1.06 logged as Segment 8 | ☑ |
| 14 Oct 2026 | Promote page (side change) | Redesigned `/promote-your-bussiness/`: out-of-date ₦2,000 offer replaced by a "still in progress" hero (`promote.jpg` + pulse), a direct `mailto:` to the partnership mailbox (free first 2 weeks), and a GET advert gallery (`PromoteAdsView` → `HOME/promote_ads.html`, shimmer skeleton → cards → tagged examples). `/promote-ads/` disallowed in `robots.txt`. Footer "Company" column now carries a **Partner with us** link just before Author handbook | ☑ |
| 14 Oct 2026 | 6 — Ad / traffic policy hygiene | Audited code + **live production**: no self-clicks or click incentives, no artificial traffic (no meta-refresh / page prefetch; carousels only rotate slides; bot-aware view counter; AdSense loader on the homepage only), and paid content is `rel="sponsored"` + `aria-label`-labelled and small beside the news (~36 stories vs 1 ticker item + ~3 teaser slides + 2 Google units). Fixed the ticker's dead house-fallback URL → `/promote-your-bussiness/`. Visible-label gap logged as an owner call. `HOME` = 115 tests, only the 5 known pre-existing failures | ☑ |
| 14 Oct 2026 | Rename + ad label (side change) | The thin top strip is an **announcements** bar, not an advert slot: renamed the `AdvertText` model → `Announcement` and `ad_content` → `content` (migration `Partner/0004`, data-preserving), the PANEL "Text awareness" section → "Announcements" (`/panel/announcements/…`), and the home `ad_center_items` / `ad-ticker` → `announcement_items` / `announcement-ticker`; dropped its `aria-label="Sponsored"` and `rel="sponsored"`. Also gave the desktop hero-teaser caption the "AD" chip the phone layout already shows, centred on the image/caption divider | ☑ |

---

## Notes / open questions

- Confirm whether `/privacy-policy/`, `/about/`, editorial team and author pages are indexed and reachable before applying.
- `/promote-your-bussiness/` is misspelled ("bussiness"); renaming it should carry a permanent redirect from the old path, so it is left for a dedicated change.
- Google publishes **no** minimum number of articles or monthly visitors; consistency and usefulness matter, not volume.
- Apply only through the official Google AdSense site.
