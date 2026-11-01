"""Varredura das views da casca (R22; T4.5), no molde de `permissao/testes/test_varredura_rotas.py`: toda página
autenticada declara a ação que exige, e a página de terceiro nega por URL direta a quem não tem acesso. Rota pública
entra numa lista fixa, justificada aqui."""

from importlib import import_module

from django.http import HttpResponse
from django.urls import URLResolver, include, path, reverse

from projeto.paginas_autenticadas import PROPRIA_PESSOA
from projeto.urls import urlpatterns

# Sem sessão por desenho: entrar, esqueci a senha e redefinição são de quem ainda não tem credencial; sair é POST com CSRF
# e encerrar uma sessão que não existe é inofensivo.
PUBLICAS = frozenset({'entrar', 'sair', 'esqueci_senha', 'redefinir_senha'})
# A API e o painel têm portão próprio (varredura de rotas da API e admin do Django).
DE_OUTRO_PORTAO = ('api/', 'painel/')


def _rotas(padroes, prefixo=''):
    """`(nome, view, parâmetros)` de cada página, entrando nos `include()` (Greptile, PR #21)."""
    achadas = []
    for padrao in padroes:
        caminho = prefixo + str(padrao.pattern)
        if isinstance(padrao, URLResolver):
            if not caminho.startswith(DE_OUTRO_PORTAO):
                achadas += _rotas(padrao.url_patterns, caminho)
        else:
            achadas.append((padrao.name, padrao.callback, list(padrao.pattern.converters)))
    return achadas


def _autenticadas():
    return [(nome, visao, parametros) for nome, visao, parametros in _rotas(urlpatterns) if getattr(visao, 'exige_entrada', False)]


def test_a_varredura_enxerga_as_views_da_casca():
    nomes = {nome for nome, _, _ in _rotas(urlpatterns)}
    assert {'inicio', 'empresas', 'empresa', 'fazenda', 'aceitar_convite', 'recusar_convite', 'trocar_senha'} <= nomes


def test_a_varredura_entra_nas_paginas_incluidas_e_pula_so_api_e_painel():
    def solta(requisicao):
        return HttpResponse()

    padroes = [
        path('extra/', include([path('solta', solta, name='pagina_solta')])),
        path('api/v1/', include([path('qualquer', solta, name='da_api')])),
        path('painel/', include([path('qualquer', solta, name='do_painel')])),
    ]
    assert [nome for nome, _, _ in _rotas(padroes)] == ['pagina_solta']
    assert not getattr(solta, 'exige_entrada', False)  # uma página assim cai na lista de sem portão e o teste abaixo falha


def test_so_as_rotas_publicas_da_lista_ficam_sem_exigir_entrada():
    autenticadas = {nome for nome, _, _ in _autenticadas()}
    assert {nome for nome, _, _ in _rotas(urlpatterns)} - autenticadas == PUBLICAS


def test_toda_view_autenticada_declara_a_acao_que_exige():
    assert [nome for nome, visao, _ in _autenticadas() if getattr(visao, 'acao_exigida', None) is None] == []


def test_acao_declarada_existe_no_catalogo_ou_e_da_propria_pessoa():
    catalogo = {
        codigo
        for migracao in ('0001_initial', '0007_acoes_territorio')
        for codigo, _, _ in import_module(f'permissao.migrations.{migracao}').ACOES
    }
    assert {getattr(visao, 'acao_exigida') for _, visao, _ in _autenticadas()} <= catalogo | {PROPRIA_PESSOA}


def test_pagina_de_terceiro_declara_a_acao_do_catalogo_e_as_da_pessoa_declaram_a_propria():
    por_nome = {nome: visao for nome, visao, _ in _autenticadas()}
    for nome in ('empresas', 'empresa', 'fazenda'):
        assert getattr(por_nome[nome], 'acao_exigida') == 'ver'
    for nome in ('inicio', 'aceitar_convite', 'recusar_convite', 'trocar_senha'):
        assert getattr(por_nome[nome], 'acao_exigida') == PROPRIA_PESSOA


def test_pagina_de_terceiro_com_alvo_na_url_nega_a_quem_nao_tem_acesso(cliente_logado, cenario):
    # A declaração sozinha não prova a checagem (Qodo, PR #21): quem declara uma ação do catálogo e recebe 200 de
    # quem não tem concessão está declarando sem checar.
    ids = {'empresa_id': cenario.x.pk, 'fazenda_id': cenario.f1.pk, 'sub_area_id': cenario.g1.pk}
    de_terceiro = [(nome, parametros) for nome, visao, parametros in _autenticadas()
                   if getattr(visao, 'acao_exigida') != PROPRIA_PESSOA and parametros]
    assert de_terceiro
    for nome, parametros in de_terceiro:
        resposta = cliente_logado.get(reverse(nome, kwargs={parametro: ids[parametro] for parametro in parametros}))
        assert (nome, resposta.status_code) == (nome, 404)
