from django.db import models

class AdvertText(models.Model):
    """THIS OLD ALL ADVERT THAT IS ONLY TEXT BASED"""
    author = models.ForeignKey('AUTHENTICATION.Auth', on_delete=models.CASCADE)
    date_created = models.DateTimeField(auto_now_add=True)
    expiry_date = models.DateTimeField(null=False, blank=False)
    ad_content = models.CharField(max_length=400, default = "This is an advert with no content")
    