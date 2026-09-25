from django.contrib import admin

from STAFF.models import FollowRelationship, StaffProfile

admin.site.register([StaffProfile, FollowRelationship])