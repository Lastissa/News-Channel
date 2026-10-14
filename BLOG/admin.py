from django.contrib import admin

from BLOG.models import Blog, BlogLike, Category, Comment


class BlogAdmin(admin.ModelAdmin):
    """Releases a story's uploaded banner from Cloudinary when the story is
    deleted from the Django admin too. The app's own delete view already does
    this (HOME.views.ProfilePublishedDeleteView -> _release_story_image); this
    stops the hidden _admin/ backdoor from orphaning the same asset."""

    def delete_model(self, request, obj):
        #   Deferred: HOME.views imports BLOG.models, so a module-level import
        #   here would be a cycle.
        from HOME.views import _release_story_image

        public_id = obj.image_public_id
        super().delete_model(request, obj)
        _release_story_image(public_id)

    def delete_queryset(self, request, queryset):
        from HOME.views import _release_story_image

        public_ids = set(
            queryset.exclude(image_public_id="").values_list("image_public_id", flat=True)
        )
        super().delete_queryset(request, queryset)
        for public_id in public_ids:
            _release_story_image(public_id)


admin.site.register([BlogLike, Category, Comment])
admin.site.register(Blog, BlogAdmin)
