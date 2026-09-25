"""
PROJECT CUSTOM CONFIGURATION FILE
"""
from django.conf import settings

class About:
    project_name = "AbuReport"
    project_cachphrase = "Reliable Source, Trusted News."
    version = "1.0.0"

    #   CANONICAL DOMAIN FOR SEO / SOCIAL PREVIEWS / STRUCTURED DATA / EMAIL LINKS.
    #   Pulled from the first entry in ALLOWED_HOSTS  instead of
    #   the literal request host, so a canonical tag, share preview, sitemap entry
    #   or JSON-LD url always points at the real .com.ng domain and never at
    #   whatever host/IP/tunnel actually served the request.
    domain = (
        f"{'http' if settings.DEBUG else 'https'}://{settings.ALLOWED_HOSTS[0]}"
        if settings.ALLOWED_HOSTS else ""
    )
    
    #   SOCIALS     -   public / group / hanNDLES
    facebook = "https://web.facebook.com/profile.php?id=61584712490692"
    instagram = ""
    linkedin = ""
    whatsapp = "https://www.whatsapp.com/channel/0029Vb6h94AHVvTUfxoSvS2p"
    tweeter = "https://x.com/ABUSUAD01/"
    contact_email = "@shaefalaap.resend.app"

    #   CONTACTS - personal / one to one /consultancy
    email = "marketing@gmail.com"
    whatsapp_dm = "https://wa.me.09031394284"
    mobile = "+234xxxxxxxxxxxx"
    
    
class StaffConfig:
    """Single source of truth for staff-facing choice lists.

    Templates never hard code these. Views pull them from here and drop them
    into context, so editing STAFF.models.STAFF_ROLE updates every dropdown
    across the whole project at once.
    """

    #   ROLES THAT CAN NEVER BE HANDED OUT FROM THE ADMIN PANEL
    PROTECTED_ROLES = {"FOUNDER"}

    @staticmethod
    def role_choices(include_protected=False):
        from STAFF.models import STAFF_ROLE

        if include_protected:
            return list(STAFF_ROLE)
        return [(value, label) for value, label in STAFF_ROLE if value not in StaffConfig.PROTECTED_ROLES]

    @staticmethod
    def gender_choices():
        from STAFF.models import GENDER_CHOICES

        return list(GENDER_CHOICES)

    @staticmethod
    def role_label(value):
        for role_value, role_label in StaffConfig.role_choices(include_protected=True):
            if role_value == value:
                return role_label
        return value or "Staff"


def custom_context_processors(request):
    from BLOG.models import CATEGORY

    theme = "light"
    if request and request.COOKIES.get("abureport-theme") in {"dark", "light"}:
        theme = request.COOKIES.get("abureport-theme")

    #   SEO: every social link that actually has a value, used for the sitewide
    #   JSON-LD "sameAs" list so an empty handle never renders as a blank entry.
    social_links = [
        url for url in (About.facebook, About.tweeter, About.whatsapp, About.instagram, About.linkedin)
        if url
    ]
    twitter_username = About.tweeter.rstrip("/").split("/")[-1] if About.tweeter else ""

    return {
        "project_name": About.project_name,
        "version": About.version,
        'project_cachphrase': About.project_cachphrase,
        'site_domain': About.domain,
        'facebook': About.facebook,
        'instagram': About.instagram,
        'linkedin': About.linkedin,
        'whatsapp': About.whatsapp,
        'tweeter': About.tweeter,
        'twitter_username': twitter_username,
        'social_links': social_links,
        'contact_email': About.contact_email,
        'nav_categories': CATEGORY,
        'partnership_email': About.email,
        'whatsapp_dm': About.whatsapp_dm,
        'mobile': About.mobile,
        'theme_preference': theme,
    }