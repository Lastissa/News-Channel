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
| 3 | Publication transparency pages | P3 | Yes | ☐ |
| 4 | Mobile experience & readability | P4 | Can | ☐ |
| 5 | Technical crawl & indexing | P5 | Yes | ☐ |
| 6 | Ad / traffic policy hygiene | P6 | Yes | ☐ |

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

---

## Status log

| Date | Segment | Change | Status |
|------|---------|--------|--------|
| 14 Oct 2026 | 1 — Privacy-policy ad disclosures | Added Google/third-party advertising disclosure behind a `show_google_ads` switch in `HOME/templates/HOME/privacy_policy.html`; bumped "Last updated" to 14 Oct 2026 | ☑ |
| 14 Oct 2026 | 2 — Article content audit | First pass accidentally read the local DB (void). Re-audited **production**: 8 stories fetched across 8 categories + sitemap. Majority are 130–200-word single-source rewrites; padding in story 66; self-promo stories 7 & 40 in the news feed; typo links. ~55 stories live. Editorial fixes listed, none actioned | ◐ |
| 14 Oct 2026 | 2 — Enforcement (A + B) | Updated `DOCS/NEWS_CONTENT_CONVENTION.MD` with editorial rules; `SERVICE_INTERNAL/story_validation.py` blocks <100-word bodies and warns <300 words / no source; Add News guide + author handbook updated; `SitemapXmlView` skips empty categories; tests refreshed for the new rule | ◐ |

---

## Notes / open questions

- Confirm whether `/privacy-policy/`, `/about/`, editorial team and author pages are indexed and reachable before applying.
- Google publishes **no** minimum number of articles or monthly visitors; consistency and usefulness matter, not volume.
- Apply only through the official Google AdSense site.
