from django.db import models

class AdvertText(models.Model):
    """THIS OLD ALL ADVERT THAT IS ONLY TEXT BASED"""
    author = models.ForeignKey('AUTHENTICATION.Auth', on_delete=models.CASCADE)
    date_created = models.DateTimeField(auto_now_add=True)
    expiry_date = models.DateTimeField(null=False, blank=False)
    ad_content = models.CharField(max_length=400, default = "This is an advert with no content")
    url = models.URLField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    
    def __str__(self):
        return str(self.author) + " ---Expiry: " + str(self.expiry_date.strftime("%d of %b, %Y"))
    