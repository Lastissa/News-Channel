from django.contrib import admin

from STAFF.models import AuthorFollow, FollowRelationship, StaffProfile, StoryDraft

admin.site.register([StaffProfile, FollowRelationship, AuthorFollow, StoryDraft])