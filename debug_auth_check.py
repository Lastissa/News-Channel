import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'NoName.settings')
import django
django.setup()
from django.test import Client
from AUTHENTICATION.models import Auth
from BLOG.models import Blog
from django.conf import settings

settings.ALLOWED_HOSTS = ['testserver']
settings.MAINTENANCE_MODE = 'FALSE'

u = Auth.objects.create_user(email='debug@example.com', password='secret')
print('user_created', u.pk, u.email)
print('is_authenticated_property', u.is_authenticated)

c = Client()
print('before_force_login_session', c.session.session_key)
c.force_login(u)
print('after_force_login_session', c.session.session_key)
print('session_auth_id', c.session.get('_auth_user_id'))
print('session_backend', c.session.get('_auth_user_backend'))

b = Blog.objects.create(author=u, category='GENERAL', heading='x', content='hello')
r = c.post(f'/story/{b.id}/like/', HTTP_X_REQUESTED_WITH='XMLHttpRequest')
print('status', r.status_code)
print(r.content.decode()[:500])
