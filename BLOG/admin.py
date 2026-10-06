from django.contrib import admin

from BLOG.models import Blog, BlogLike, Category, Comment

admin.site.register([Blog, BlogLike, Category, Comment])