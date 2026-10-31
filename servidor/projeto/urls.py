from django.contrib import admin
from django.urls import path

from projeto import paginas, paginas_acesso
from projeto.api import api

urlpatterns = [path('api/v1/', api.urls), path('painel/', admin.site.urls),
               path('redefinir-senha', paginas.redefinir_senha, name='redefinir_senha'),
               path('entrar', paginas_acesso.entrar, name='entrar'),
               path('sair', paginas_acesso.sair, name='sair'),
               path('trocar-senha', paginas_acesso.trocar_senha, name='trocar_senha'),
               path('esqueci-senha', paginas_acesso.esqueci_senha, name='esqueci_senha')]

# O padrão do Django renderiza o 500 sem a requisição, e sem ela o molde não leva o nonce da política de conteúdo.
handler500 = 'projeto.paginas.erro_500'
