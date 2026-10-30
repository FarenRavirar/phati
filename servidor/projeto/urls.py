from django.contrib import admin
from django.urls import path

from projeto import paginas
from projeto.api import api

urlpatterns = [path('api/v1/', api.urls), path('painel/', admin.site.urls),
               path('redefinir-senha', paginas.redefinir_senha, name='redefinir_senha')]

# O padrão do Django renderiza o 500 sem a requisição, e sem ela o molde não leva o nonce da política de conteúdo.
handler500 = 'projeto.paginas.erro_500'
