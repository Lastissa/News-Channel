from django.contrib import admin

from Partner.models import AdvertImage, AdvertText
admin.site.register([AdvertText, AdvertImage])
