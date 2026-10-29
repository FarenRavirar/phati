from django.contrib import admin
from django.urls import path

from projeto.api import api

urlpatterns = [path('api/v1/', api.urls), path('painel/', admin.site.urls)]
