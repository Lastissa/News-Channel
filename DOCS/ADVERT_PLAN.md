# Advertiser Platform — v1 Design Document

**Project:** abureport.com.ng — Advertiser / Promotion Module
**Version:** 1.0 (launch scope)
**Status:** Planning — no code yet
**Last updated:** 2026-09-26

---

## 1. Purpose & Scope

This document defines the **v1 advertiser platform** for abureport.com.ng.

The goal is to let small businesses and individuals pay to place a clearly-labeled ad on the news site, track basic performance, and manage their own creative — all with the minimum amount of moving parts.

**Explicitly out of scope for v1:**

- Multiple pricing tiers
- Subscription / recurring billing via Paystack Subscriptions API
- Impression-based (CPM) pricing
- Self-serve ad creative builder
- Multiple ad slots per plan
- A separate authentication system for advertisers
- Any "encrypted endkey" login mechanism

These are v2+ concerns, to be revisited once 10+ paying partners exist and real usage data is available.

---

## 2. Core Principles

1. **One user model.** An advertiser is a normal Django user with an `AdvertiserProfile` attached. No prefixed emails, no shadow accounts, no second auth system.
2. **One plan at launch.** ₦3,000 / month, one banner slot on story pages. Pricing tiers are a v2 problem.
3. **One slot per plan.** Sell *slots* (positions on page types), not "number of ads." The slot count *is* the plan.
4. **Free trial first.** Every new advertiser gets 7 days free on the same plan. No card required. When it expires, ads stop until they pay.
5. **Manual expiry.** A monthly payment extends `expires_at` by 30 days. When it lapses, ads stop showing. No cron-driven subscription logic in v1.
6. **Fixed ad placements only.** No random injection into editorial content. Ads live in known, labeled positions.
7. **Trust over revenue.** Every ad is labeled "Sponsored." Brand safety and reader trust come before filling inventory.

---

## 3. Data Model

### 3.1 `AdvertiserProfile`

Attached one-to-one to `settings.AUTH_USER_MODEL`. Exists only if the user has opted into advertising.

| Field | Type | Notes |
|---|---|---|
| `user` | `OneToOneField(User)` | The account. Also usable as a normal reader account. |
| `business_name` | `CharField(200)` | Displayed to admin, optionally on the ad itself. |
| `contact_phone` | `CharField(20)` | For support and manual follow-up. |
| `plan` | `CharField(choices)` | Only `"starter"` in v1. Kept as a field so v2 can add tiers without a migration headache. |
| `expires_at` | `DateTimeField(null=True)` | End of current paid (or trial) period. `null` = not yet activated. |
| `trial_used` | `BooleanField(default=False)` | Set True once the free trial is consumed. Prevents repeat trials. |
| `created_at` | `DateTimeField(auto_now_add)` | |
| `updated_at` | `DateTimeField(auto_now)` | |

**Derived properties (not stored):**

- `is_active` → `expires_at is not None and expires_at > now()`
- `is_on_trial` → `trial_used and expires_at > now()` and no successful payment recorded yet
- `days_remaining` → `(expires_at - now()).days`

### 3.2 `AdSlot`

The fixed placement available on the site. Seeded once via a data migration; not user-editable in v1.

| Field | Type | Notes |
|---|---|---|
| `code` | `SlugField(unique)` | e.g. `story_banner`, `home_banner`, `story_sidebar` |
| `name` | `CharField(100)` | Human label: "Story Page — Top Banner" |
| `description` | `TextField(blank)` | Shown on the promote page |
| `width` | `PositiveIntegerField` | Max creative width in px |
| `height` | `PositiveIntegerField` | Max creative height in px |
| `is_active` | `BooleanField(default=True)` | Lets you disable a slot without deleting it |

**v1 seed:**

- `story_banner` — 728×90, top of every story page
- *(Optional v1.1)* `home_banner` — 970×90, top of homepage

Start with **one slot** in v1. Add the second when there's demand.

### 3.3 `Ad`

One creative, in one slot, owned by one advertiser.

| Field | Type | Notes |
|---|---|---|
| `advertiser` | `ForeignKey(AdvertiserProfile)` | |
| `slot` | `ForeignKey(AdSlot)` | Which position this ad occupies |
| `title` | `CharField(120)` | Internal label + alt text |
| `image` | `ImageField` | Uploaded creative; validated against slot dimensions |
| `target_url` | `URLField` | Where the click goes |
| `is_active` | `BooleanField(default=True)` | Advertiser can pause without deleting |
| `created_at` | `DateTimeField(auto_now_add)` | |
| `updated_at` | `DateTimeField(auto_now)` | |

**Rules:**

- An advertiser can have **one active ad per slot** in v1.
- Multiple ads in the same slot from the same advertiser is a v2 feature (rotation).
- Uploading a new image replaces the current creative (no versioning in v1).

### 3.4 `AdImpression`

Lightweight, append-only.

| Field | Type | Notes |
|---|---|---|
| `ad` | `ForeignKey(Ad)` | |
| `timestamp` | `DateTimeField(auto_now_add, db_index=True)` | |
| `ip_hash` | `CharField(64)` | SHA-256 of IP + daily salt. Not the raw IP. |
| `user_agent_hash` | `CharField(64, blank)` | Optional, for bot filtering |

**Rules:**

- One impression per `(ad, ip_hash)` per hour — deduplicate in the view before insert.
- No PII stored. No cookies. No third-party tracking.
- Retention: 90 days, then pruned by a management command.

### 3.5 `AdClick`

Same shape as `AdImpression`, one row per click.

| Field | Type | Notes |
|---|---|---|
| `ad` | `ForeignKey(Ad)` | |
| `timestamp` | `DateTimeField(auto_now_add, db_index=True)` | |
| `ip_hash` | `CharField(64)` | |

### 3.6 `Payment`

One row per Paystack transaction.

| Field | Type | Notes |
|---|---|---|
| `advertiser` | `ForeignKey(AdvertiserProfile)` | |
| `reference` | `CharField(64, unique)` | Paystack reference |
| `amount_kobo` | `PositiveIntegerField` | Stored in kobo |
| `status` | `CharField(choices)` | `pending` / `success` / `failed` |
| `paid_at` | `DateTimeField(null=True)` | |
| `raw_response` | `JSONField` | Full Paystack verify payload, for audit |

**Rules:**

- A `success` payment extends `advertiser.expires_at` by 30 days **only if it hasn't already been applied** (check `reference` uniqueness).
- The frontend's `onSuccess` callback is **never trusted** — the server verifies with Paystack's `/transaction/verify/{reference}` endpoint before marking `success`.

### 3.7 Relationship summary
