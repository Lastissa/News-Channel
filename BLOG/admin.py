from django.contrib import admin

from BLOG.models import Blog, Comment

admin.site.register([Blog, Comment])