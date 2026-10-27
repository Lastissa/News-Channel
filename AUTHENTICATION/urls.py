from django.urls import path
from django.shortcuts import redirect
from django.urls import reverse
from . import views

app_name = 'auth'


def _auth_root_null(request, *args, **kwargs):
    return redirect(reverse('auth:login'))


urlpatterns = [
    path('login/', views.LoginView.as_view(), name='login'),
    path('login/null/', _auth_root_null),
    path('register/null/', _auth_root_null),
    path('login/null', _auth_root_null),
    path('login/undefined', _auth_root_null),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('register/', views.RegisterView.as_view(), name='register'),
    path('register/null', _auth_root_null),
    path('register/undefined', _auth_root_null),
    path('gate/', views.GateView.as_view(), name='gate'),
    path('password-reset/', views.PasswordResetView.as_view(), name='password_reset'),
    path('', _auth_root_null),
    path('<path:subpath>', _auth_root_null),
]


