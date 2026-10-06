from django.contrib import admin

from STAFF.models import AuthorFollow, FollowRelationship, StaffProfile

admin.site.register([StaffProfile, FollowRelationship, AuthorFollow])