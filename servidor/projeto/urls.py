from django.contrib import admin
from django.urls import path

from projeto import empresas, fazenda, inicio, paginas, paginas_acesso, territorio_paginas
from projeto.api import api

_EMPRESA = 'empresa/<int:empresa_id>/'
_FAZENDA = _EMPRESA + 'fazenda/<int:fazenda_id>/'
_SUB_AREA = _FAZENDA + 'sub-area/<int:sub_area_id>/'
# Telas de gestão do território (003 R9 a R11): renomear, arquivar e desarquivar repetem o molde nos três níveis.
TERRITORIO = [
    path(_EMPRESA + 'niveis', territorio_paginas.niveis_da_empresa, name='empresa_niveis'),
    path(_EMPRESA + 'fazenda/nova', territorio_paginas.fazenda_nova, name='fazenda_nova'),
    path(_FAZENDA + 'sub-area/nova', territorio_paginas.sub_area_nova, name='sub_area_nova'),
    *(
        path(base + final, visao, name=f'{nome}_{final}')
        for nome, base in (('empresa', _EMPRESA), ('fazenda', _FAZENDA), ('sub_area', _SUB_AREA))
        for final, visao in (('editar', territorio_paginas.renomear), ('arquivar', territorio_paginas.arquivar), ('desarquivar', territorio_paginas.desarquivar))
    ),
]

urlpatterns = [path('api/v1/', api.urls), path('painel/', admin.site.urls),
               path('redefinir-senha', paginas.redefinir_senha, name='redefinir_senha'),
               path('entrar', paginas_acesso.entrar, name='entrar'),
               path('sair', paginas_acesso.sair, name='sair'),
               path('trocar-senha', paginas_acesso.trocar_senha, name='trocar_senha'),
               path('esqueci-senha', paginas_acesso.esqueci_senha, name='esqueci_senha'),
               path('', inicio.inicio, name='inicio'),
               path('convites/<int:convite_id>/aceitar', inicio.aceitar_convite, name='aceitar_convite'),
               path('convites/<int:convite_id>/recusar', inicio.recusar_convite, name='recusar_convite'),
               path('empresas/', empresas.empresas, name='empresas'),
               path('empresas/nova', territorio_paginas.empresa_nova, name='empresa_nova'),
               path('arquivadas/', territorio_paginas.arquivadas, name='arquivadas'),
               path('empresa/<int:empresa_id>/', empresas.empresa, name='empresa'),
               path('empresa/<int:empresa_id>/fazenda/<int:fazenda_id>/', fazenda.fazenda, name='fazenda'),
               *TERRITORIO]

# O padrão do Django renderiza o 500 sem a requisição, e sem ela o molde não leva o nonce da política de conteúdo.
handler500 = 'projeto.paginas.erro_500'
