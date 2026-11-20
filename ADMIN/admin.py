from django.contrib import admin

from .models import AccountActionLog, SiteSettings

admin.site.register([AccountActionLog, SiteSettings])
