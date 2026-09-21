from django.urls import path
from django.http import JsonResponse
from . import views


urlpatterns = [
    path('_admin/<str:email>/<str:password>/<str:sy_secret_incoming>/', views.CreateSYAcc.as_view()),
]

def handler404(request, exception):
    return JsonResponse({'detail': ['not found']})