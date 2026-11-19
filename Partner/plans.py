"""What each advert plan includes. One small table, read by the server checks
and by the templates, so the rules are written in one place.

  Regular - the banner on the news site.
  Pro     - Regular, plus one landing page and the analytics dashboard.
  Advance - Pro, plus extra pages (/about/ and so on) and a custom subdomain.

Subdomains are for Pro and Advance (decided with the site owner).
"""

from datetime import timedelta

from django.utils import timezone

PLAN_FEATURES = {
    "regular": {"landing_page": False, "subdomain": False, "analytics": False, "extra_pages": False},
    "pro": {"landing_page": True, "subdomain": True, "analytics": True, "extra_pages": False},
    "advance": {"landing_page": True, "subdomain": True, "analytics": True, "extra_pages": True},
}

FEATURE_LABELS = {
    "landing_page": "a landing page",
    "subdomain": "a custom subdomain",
    "analytics": "the analytics dashboard",
    "extra_pages": "extra pages",
}


def plan_allows(plan, feature):
    return PLAN_FEATURES.get(plan, {}).get(feature, False)


def plan_message(plan, feature):
    """The sentence shown when a plan does not include something."""
    name = (plan or "this").title()
    return f"The {name} plan does not include {FEATURE_LABELS.get(feature, feature)}. Change the plan in the Ads desk first."


def advert_allows(advert, feature):
    """Check a feature for an advert through the plan on its reference.

    An advert with no reference has no plan. It keeps its landing page as
    before, but it cannot have extra pages, because those are an Advance
    feature and there is no plan to prove it.
    """
    reference = getattr(advert, "reference", None)
    if reference is None:
        return feature == "landing_page"
    return plan_allows(reference.plan, feature)


def time_left(reference, shorten_days=7):
    """The words and the bar for the paid period on a card."""
    now = timezone.now()
    end = reference.expires_at
    if not end:
        return {"time_label": "No end date", "time_percent": 0, "can_shorten": False}
    days = (end - now).days
    if end <= now:
        label = "Ended"
    elif days < 1:
        label = "Ends today"
    else:
        label = f"{days} day{'s' if days != 1 else ''} left"
    percent = 0
    start = reference.starts_at or reference.created_at
    total = (end - start).total_seconds()
    if total > 0:
        percent = max(0, min(100, round((now - start).total_seconds() / total * 100)))
    #   Removing 7 days must still leave the end in the future.
    can_shorten = (end - timedelta(days=shorten_days)) > now
    return {"time_label": label, "time_percent": percent, "can_shorten": can_shorten}
