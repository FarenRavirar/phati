from django.urls import path

from projeto.api import api

urlpatterns = [path('api/v1/', api.urls)]
