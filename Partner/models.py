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
    

class AdvertImage(models.Model):
    """AN IMAGE ADVERT SHOWN IN THE HERO SIDE CAROUSEL ON THE HOME PAGE
    (HOME.views._teaser_items). Managed from PANEL ("Image adverts"). Mobile
    shows the picture only, desktop also shows heading + body under it.
    `url` is where a click on the picture goes, empty means not clickable.
    `image_public_id` is the Cloudinary asset, kept so an edit overwrites it
    in place and a delete removes it."""
    author = models.ForeignKey('AUTHENTICATION.Auth', on_delete=models.CASCADE)
    date_created = models.DateTimeField(auto_now_add=True)
    expiry_date = models.DateTimeField(null=False, blank=False)
    heading = models.CharField(max_length=90, blank=True, default="")
    body = models.CharField(max_length=200, blank=True, default="")
    image_url = models.URLField(max_length=500)
    image_public_id = models.CharField(max_length=255, blank=True, default="")
    url = models.URLField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return (self.heading or "Image advert") + " ---Expiry: " + str(self.expiry_date.strftime("%d of %b, %Y"))
