import re

from django.db import models
from django.db.models.functions import Lower


CATEGORY = [
    ('UNIVERSITY', 'UNIVERSITY'),
    ('POLYTECHNIC', 'POLYTECHNIC'),
    ('ORGANIZATION', 'ORGANIZATION'),
    ('JAMB', 'JAMB'),
    ('WAEC', 'WAEC'),
    ('POSTUTME', 'POSTUTME'),
    ('SCHOLARSHIP', 'SCHOLARSHIP'),
    ('TECHNOLOGY', 'TECHNOLOGY'),
    ('SECURITY', 'SECURITY'),
    ('GENERAL', 'GENERAL'),
]
class Blog(models.Model):
    image_1 = models.URLField(blank=True, null=True)
    image_info = models.CharField(max_length=100, default="The image is self explanatory.")    #   THE ABOUT PICTURE THHAT WILL SHOW SLIGHTLY BELOW THE PICTURE IN IMAGE 
    author = models.ForeignKey('AUTHENTICATION.Auth', on_delete=models.CASCADE, related_name='blogs', limit_choices_to= {'is_staff':True})
    category = models.CharField(max_length=20, choices=CATEGORY, blank=False, null=False)
    heading = models.CharField(max_length=100, blank=False, null=False)
    content = models.TextField(blank=False, null=False)
    views = models.PositiveIntegerField(default=0, db_index=True)
    likes = models.PositiveIntegerField(default=0)
    non_anonymous_viewer = models.ManyToManyField("AUTHENTICATION.Auth", related_name="non_anonymous_viewer", blank=True)   #   TRACKIG THE PEOPLE WHO VEIWED SO I CAN CREATE THEIR HISTORY
    last_updated = models.DateTimeField(auto_now=True, blank=True, null=True, help_text="CHANGES ANYTIME UPDATES IS MADE")
    date_created = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [

            models.UniqueConstraint(
                Lower("heading"),
                "category",
                "author",
                name="unique_story_heading_author_category",
            ),
        ]
    
    @property
    def word_count(self):
        text = self.content or ""
        return len(re.findall(r"\b\S+\b", text))

    from functools import cached_property
    @cached_property
    def author_name(self):
        from STAFF.models import StaffProfile

        profile = StaffProfile.objects.filter(auth=self.author).first()
        if profile and profile.full_name:
            return profile.full_name
        return self.author.email.split("@")[0].title()

    def __str__(self):
        return f"{self.author.email} {self.views} + {self.heading[:20]}"
    
class Comment(models.Model):
    """Comment / Feedback under the blog post"""
    blog = models.ForeignKey(Blog, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey('AUTHENTICATION.Auth', on_delete=models.CASCADE, related_name='comments')
    content = models.TextField(blank=False, null=False)
    likes = models.PositiveIntegerField(default=0)
    date_created = models.DateTimeField(auto_now_add=True)    #   NEEDED FOR THE COMMENT TIMESTAMP ("x days ago") SHOWN IN THE UI