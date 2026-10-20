"""Structured data (JSON-LD) builders for the sitewide entity graph.

One source of truth for the JSON-LD every page shares, so the Organization and
WebSite nodes -- and the ``@id`` values other nodes point at -- can never drift
apart between templates. A page that needs an extra node (a ``NewsArticle``, a
``Person``, a ``BreadcrumbList``) writes its own ``<script>`` and references
``schema_organization_id`` / ``schema_website_id`` from the context.

Nothing here touches the ORM or the request: callers pass the same context dict
the context processor already builds (socials, contact e-mails, ...). The domain
comes from ``About.domain`` (the first ALLOWED_HOSTS entry), exactly like the
canonical tag, so a JSON-LD url always points at the real production host and
never at whatever tunnel/IP actually served the request.
"""
import json

from django.templatetags.static import static

#   Every unresolved social/contact setting collapses to this shared URL (see
#   SERVICE_INTERNAL.config) so a blank value raises a friendly 404 instead of
#   an empty link. It must NEVER be emitted as a sameAs profile.
PLACEHOLDER_MARKER = "/404/"


def _about():
    #   Local import: config imports this module, so importing it back at module
    #   load time would be a circular import.
    from SERVICE_INTERNAL.config import About

    return About


def domain():
    return _about().domain.rstrip("/")


def organization_id():
    return f"{domain()}/#organization"


def website_id():
    return f"{domain()}/#website"


def _clean_external_url(value):
    """A real external profile URL, or "" -- drops blanks, the shared 404
    fallback and anything that is not http(s)."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if not value.startswith("http") or PLACEHOLDER_MARKER in value:
        return ""
    return value


def _real_email(value):
    """A real contact address, or "" -- drops blanks, the shared 404 fallback
    and anything that is actually a URL."""
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if "@" not in value or value.startswith("http") or PLACEHOLDER_MARKER in value:
        return ""
    return value


def _absolute(path):
    """Turn a site-relative path into an absolute URL on the canonical domain."""
    if isinstance(path, str) and path.startswith("http"):
        return path
    return f"{domain()}{path}"


def _logo_url():
    try:
        logo = static("logo.jpg")
    except Exception:
        try:
            logo = static("images/logo.png")
        except Exception:
            try:
                logo = static("img/logo.png")
            except Exception:
                logo = "/static/logo.jpg"
    return logo if logo.startswith("http") else f"{domain()}{logo}"


def same_as_profiles(context):
    """The brand's verified profiles, in a stable order, for ``sameAs``.

    An admin SiteSettings value wins; when that platform is blank the About
    default for the same platform is used instead, so an unconfigured social
    still resolves to something real. Anything that is still blank or the shared
    placeholder is skipped rather than emitted as a dangling link.
    """
    about = _about()
    candidates = [
        context.get("tweeter") or about.tweeter,
        context.get("facebook") or about.facebook,
        context.get("whatsapp") or about.whatsapp,
        about.instagram,
        about.linkedin,
    ]
    profiles = []
    for url in candidates:
        clean = _clean_external_url(url)
        if clean and clean not in profiles:
            profiles.append(clean)
    return profiles


def organization_node(context):
    """The publisher entity: a NewsMediaOrganization, the node other nodes
    point at through ``organization_id()``."""
    about = _about()
    base = domain()
    logo_url = _logo_url()
    logo = {"@type": "ImageObject", "url": logo_url}
    try:
        from django.contrib.staticfiles import finders
        for name in ("logo.jpg", "images/logo.png", "img/logo.png", "logo.png"):
            path = finders.find(name)
            if path:
                try:
                    from PIL import Image
                    with Image.open(path) as im:
                        logo["width"] = im.width
                        logo["height"] = im.height
                except Exception:
                    pass
                break
    except Exception:
        pass
    node = {
        "@type": "NewsMediaOrganization",
        "@id": organization_id(),
        "name": about.project_name,
        "url": f"{base}/",
        "logo": logo,
        "description": (
            f"{about.project_name} is a Nigerian news platform reporting verified, "
            "up-to-date news across many genres, with a strong focus on Nigeria and Africa."
        ),
        "inLanguage": "en-NG",
        #   E-E-A-T: point at the pages that say who reports and how.
        "publishingPrinciples": f"{base}/about/",
        "masthead": f"{base}/editorial/",
        "areaServed": {"@type": "Country", "name": "Nigeria"},
    }

    profiles = same_as_profiles(context)
    if profiles:
        node["sameAs"] = profiles

    support_email = _real_email(context.get("support_email"))
    if support_email:
        node["email"] = support_email

    contacts = []
    for contact_type, key in (
        ("customer support", "support_email"),
        ("technical support", "tech_expert_email"),
        ("advertising", "partnership_email"),
    ):
        email = _real_email(context.get(key))
        if email:
            contacts.append(
                {
                    "@type": "ContactPoint",
                    "contactType": contact_type,
                    "email": email,
                    "areaServed": "NG",
                    "availableLanguage": ["en"],
                }
            )
    if contacts:
        node["contactPoint"] = contacts
    return node


def website_node(context):
    """The site itself, with the SearchAction that powers the sitelinks
    search box and tells answer engines how the site is searched."""
    about = _about()
    base = domain()
    return {
        "@type": "WebSite",
        "@id": website_id(),
        "url": f"{base}/",
        "name": about.project_name,
        "description": context.get("project_cachphrase") or about.project_cachphrase,
        "publisher": {"@id": organization_id()},
        "inLanguage": "en-NG",
        "potentialAction": {
            "@type": "SearchAction",
            "target": {
                "@type": "EntryPoint",
                "urlTemplate": f"{base}/search/?q={{search_term_string}}",
            },
            "query-input": "required name=search_term_string",
        },
    }


def site_graph(context):
    return {
        "@context": "https://schema.org",
        "@graph": [organization_node(context), website_node(context)],
    }


def breadcrumb_list(items, context=None):
    """A BreadcrumbList from ``(name, url)`` pairs. A pair with an empty url is
    the current page (its ListItem carries no ``item``), which is what the
    ``{% breadcrumb_schema %}`` tag produces for a trailing bare name."""
    base = domain()
    elements = []
    for position, (name, url) in enumerate(items, start=1):
        element = {"@type": "ListItem", "position": position, "name": name}
        if url:
            element["item"] = _absolute(url)
        elements.append(element)

    node = {"@type": "BreadcrumbList", "itemListElement": elements}
    request = (context or {}).get("request")
    if request is not None and request.path:
        node["@id"] = f"{base}{request.path}#breadcrumb"
    return node


def person_id(slug):
    """The stable ``@id`` of one author entity, keyed on the portfolio URL.

    Both the author's portfolio page and every story they wrote point at this
    exact value, so search engines and answer engines resolve the byline on a
    story and the portfolio page to a SINGLE Person instead of two unrelated
    nodes. An author with no portfolio slug has no stable id and is left
    anonymous rather than given an invented one."""
    return f"{domain()}/portfolio/{slug}/#person"


def person_node(
    *,
    name,
    slug="",
    url="",
    image="",
    description="",
    job_title="",
    same_as=(),
    knows_about=(),
    email="",
    hire_date="",
):
    """The author as a schema.org ``Person`` -- the one definition every page
    that mentions them reuses.

    ``slug`` (the portfolio slug) makes the entity stable: when it is set the
    node carries ``person_id(slug)`` and a URL, so a story's ``author`` and the
    portfolio's ``mainEntity`` are literally the same node. Without a slug the
    node is still valid but anonymous. ``worksFor`` ties the person to the
    shared publisher entity (E-E-A-T). Only real, non-placeholder profile links
    survive as ``sameAs``.
    """
    node = {"@type": "Person", "name": name}
    if slug:
        node["@id"] = person_id(slug)
        node["url"] = url or f"{domain()}/portfolio/{slug}/"
    elif url:
        node["url"] = url

    if image:
        node["image"] = image
    if description:
        node["description"] = description
    if job_title:
        node["jobTitle"] = job_title

    profiles = []
    for value in same_as or ():
        clean = _clean_external_url(value)
        if clean and clean not in profiles:
            profiles.append(clean)
    if profiles:
        node["sameAs"] = profiles

    beats = [str(beat).strip() for beat in (knows_about or ()) if str(beat).strip()]
    if beats:
        node["knowsAbout"] = beats

    if email:
        node["email"] = email
    if hire_date:
        node["hireDate"] = hire_date

    node["worksFor"] = {"@id": organization_id()}
    return node


def profile_page_node(*, url, name, person, description=""):
    """A ``ProfilePage`` whose ``mainEntity`` is the author's ``person`` node,
    the shape Google expects for an author/portfolio page."""
    node = {
        "@type": "ProfilePage",
        "@id": f"{url}#profilepage",
        "url": url,
        "name": name,
        "mainEntity": person,
    }
    if description:
        node["description"] = description
    return node


def news_article_node(
    *,
    headline,
    url,
    description,
    author,
    image="",
    date_published="",
    date_modified="",
    section="",
    word_count=0,
):
    """A ``NewsArticle`` for one story, with the shared publisher/WebSite
    entities referenced by ``@id`` and ``author`` given as a full ``person_node``
    so the byline resolves to the author's stable entity."""
    node = {
        "@type": "NewsArticle",
        "@id": f"{url}#article",
        "headline": headline,
        "description": description,
        "url": url,
        "datePublished": date_published,
        "dateModified": date_modified or date_published,
        "inLanguage": "en-NG",
        "author": author,
        "publisher": {"@id": organization_id()},
        "isPartOf": {"@id": website_id()},
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
    }
    if section:
        node["articleSection"] = section
    if image:
        node["image"] = {"@type": "ImageObject", "url": image}
    if word_count:
        node["wordCount"] = word_count
    return node


def dumps(node):
    """Encode a node for a <script type="application/ld+json"> block. ``<`` is
    escaped so user text (a headline, a bio) can never close the script tag
    early."""
    return json.dumps(node, ensure_ascii=False).replace("<", "\\u003c")


def site_graph_json(context):
    return dumps(site_graph(context))
