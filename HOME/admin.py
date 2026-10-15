from django.contrib import admin
from .models import Bookmark, ReadingHistory, CategorySubscription

admin.site.register([Bookmark, ReadingHistory, CategorySubscription])
