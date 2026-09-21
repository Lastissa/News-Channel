from django.db import models
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager

from SERVICE_INTERNAL.abstract import info_logger

import logging

logger = logging.getLogger(__name__)

class AuthManager(BaseUserManager):
    def _blueprint(self, email, password=None, **extra_fields):
        if not email:raise ValueError('Users must have an email is req')
        user = self.model(email=email.upper(), **extra_fields)
        user.save(using=self._db)
        if password:
            user.set_password(password)
            user.save(update_fields=['password'])
            info_logger(logger=logger, msg=f"ACCOUNT CREATION: user ({email.upper()}) created account with password set")
        else:
            user.set_unusable_password()
            user.save(update_fields=['password'])
            info_logger(logger=logger, msg=f"ACCOUNT CREATION: user ({email.upper()}) created account with NO password set")
        return user
    
    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_active', True)
        return self._blueprint(email=email, password=password, **extra_fields)

    def create_staff(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        return self._blueprint(email=email, password=password, **extra_fields)

    def create_admin(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_admin', True)
        return self.create_staff(email=email, password=password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_superuser', True)
        return self.create_admin(email=email, password=password, **extra_fields)
    
    


class Auth(AbstractBaseUser):
    email = models.EmailField(unique=True, null=False, blank=False)
    date_joined = models.DateTimeField(auto_now_add=True)
    is_staff = models.BooleanField(default = False)
    is_superuser = models.BooleanField(default = False)
    is_admin = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    receive_email_login_alert = models.BooleanField(default=True)#  login alert sent every time user login
    send_newsletter = models.BooleanField(default=False)    #   permission to send news alert
    profile_img = models.URLField(blank=True, null=True)    #   profile picture for each and every users
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = []
     
    objects = AuthManager()

    def has_perm(self, perm, obj=None):
        return True

    def has_module_perms(self, app_label):
        return True

    def has_module_perm(self, app_label):
        return self.has_module_perms(app_label)

    def __str__(self):
        staff_type = "Member"
        if self.is_staff: staff_type = "Staff"
        if self.is_admin: staff_type = "Admin"
        if self.is_superuser: staff_type = "S-Admin"
        
        return f"{self.email}: staff type : {staff_type}"


class PasswordResetKey(models.Model):
    """One live password reset link per account.

    The reset link carries the account email plus a key and a sign. Both must
    still exist in this table for the password change to be accepted, and the
    row is deleted the moment the password is updated, so a link can never be
    used twice and a forged key/sign pair finds nothing to match.
    """

    user = models.OneToOneField(Auth, on_delete=models.CASCADE, related_name="password_reset_key")
    key = models.CharField(max_length=6)     #   6 DIGIT NUMERIC HALF OF THE LINK
    sign = models.CharField(max_length=10)   #   10 CHARACTER ALPHANUMERIC HALF OF THE LINK
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"PasswordResetKey: {self.user.email} ({self.created_at})"
    