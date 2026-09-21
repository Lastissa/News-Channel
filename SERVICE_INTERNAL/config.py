"""
PROJECT CUSTOM CONFIGURATION FILE
"""
from django.conf import settings

class About:
    project_name = "AbuReports"
    project_cachphrase = "Reliable Source, Trusted hands."
    version = "1.0.0"
    
    #   SOCIALS     -   public / group / hanNDLES
    facebook = ""
    whatsapp = "https://wa.link/ebvff1/"
    tweeter = "https://x.com/ABUSUAD01/"
    contact_email = "hello@abureports.ng"
    domain = getattr(settings, "DOMAIN_NAME") or "http://localhost:8000"

    #   CONTACTS - personal / one to one /consultancy
    email = "marketing@gmail.com"
    whatsapp_dm = "https://wa.me.09112"
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
    if request and request.COOKIES.get("abureports-theme") in {"dark", "light"}:
        theme = request.COOKIES.get("abureports-theme")

    return {
        "project_name": About.project_name,
        "version": About.version,
        'project_cachphrase': About.project_cachphrase,
        'facebook': About.facebook,
        'whatsapp': About.whatsapp,
        'tweeter': About.tweeter,
        'contact_email': About.contact_email,
        'domain': About.domain,
        'nav_categories': CATEGORY,
        'partnership_email': About.email,
        'whatsapp_dm': About.whatsapp_dm,
        'mobile': About.mobile,
        'theme_preference': theme,
    }