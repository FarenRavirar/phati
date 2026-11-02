from django.contrib import admin
from django.urls import path

from projeto import cargos_paginas, empresas, fazenda, inicio, paginas, paginas_acesso, pessoas_paginas, territorio_paginas
from projeto.api import api

_EMPRESA = 'empresa/<int:empresa_id>/'
_FAZENDA = _EMPRESA + 'fazenda/<int:fazenda_id>/'
_SUB_AREA = _FAZENDA + 'sub-area/<int:sub_area_id>/'
# Telas de gestão do território (003 R9 a R11): renomear, arquivar e desarquivar repetem o molde nos três níveis.
TERRITORIO = [
    path(_SUB_AREA, fazenda.sub_area, name='sub_area'),
    path(_EMPRESA + 'niveis', territorio_paginas.niveis_da_empresa, name='empresa_niveis'),
    path(_EMPRESA + 'fazenda/nova', territorio_paginas.fazenda_nova, name='fazenda_nova'),
    path(_FAZENDA + 'sub-area/nova', territorio_paginas.sub_area_nova, name='sub_area_nova'),
    *(
        path(base + final, visao, name=f'{nome}_{final}')
        for nome, base in (('empresa', _EMPRESA), ('fazenda', _FAZENDA), ('sub_area', _SUB_AREA))
        for final, visao in (('editar', territorio_paginas.renomear), ('arquivar', territorio_paginas.arquivar), ('desarquivar', territorio_paginas.desarquivar))
    ),
]

# Telas de pessoas (003 R13 a R16): tudo sob a empresa, a mesma regra de escopo na URL (D063).
PESSOAS = [
    path(_EMPRESA + 'pessoas/', pessoas_paginas.pessoas, name='pessoas'),
    path(_EMPRESA + 'pessoas/convidar', pessoas_paginas.convidar, name='pessoas_convidar'),
    path(_EMPRESA + 'pessoas/convidar/sub-area/', pessoas_paginas.convidar_sub_area, name='convidar_sub_area'),
    path(_EMPRESA + 'pessoas/convidar/sub-area/<int:fazenda_id>/', pessoas_paginas.convidar_sub_area, name='convidar_sub_area_fazenda'),
    path(_EMPRESA + 'pessoas/convites', pessoas_paginas.convites_enviados, name='pessoas_convites'),
    path(_EMPRESA + 'pessoas/convites/<int:convite_id>/cancelar', pessoas_paginas.cancelar_convite, name='convite_cancelar'),
    path(_EMPRESA + 'pessoas/convites/<int:convite_id>/reenviar', pessoas_paginas.reenviar_convite, name='convite_reenviar'),
    path(_EMPRESA + 'pessoa/<int:pessoa_id>/revogar/<int:concessao_id>', pessoas_paginas.revogar, name='pessoa_revogar'),
    path(_EMPRESA + 'pessoa/<int:pessoa_id>/redefinir-senha', pessoas_paginas.redefinir_senha, name='pessoa_redefinir_senha'),
    path(_EMPRESA + 'titularidade', pessoas_paginas.titularidade, name='titularidade'),
    path(_EMPRESA + 'pessoa/<int:pessoa_id>/conceder', pessoas_paginas.conceder, name='pessoa_conceder'),
]

# Telas de cargos (003 R18): da empresa, não da fazenda.
CARGOS = [
    path(_EMPRESA + 'cargos/', cargos_paginas.cargos, name='cargos'),
    path(_EMPRESA + 'cargos/novo', cargos_paginas.cargo_novo, name='cargo_novo'),
    path(_EMPRESA + 'cargos/<int:cargo_id>/editar', cargos_paginas.cargo_editar, name='cargo_editar'),
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
               *TERRITORIO, *PESSOAS, *CARGOS]

# O padrão do Django renderiza o 500 sem a requisição, e sem ela o molde não leva o nonce da política de conteúdo.
handler500 = 'projeto.paginas.erro_500'
