from django.contrib import admin

from .models import Auth, PasswordResetKey, UserSession

admin.site.register([Auth, PasswordResetKey, UserSession])