from django.contrib import admin
from .models import Bookmark, ReadingHistory

admin.site.register([Bookmark, ReadingHistory])
