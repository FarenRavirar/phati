"""Varredura das views da casca (R22; T4.5), no molde de `permissao/testes/test_varredura_rotas.py`: toda página
autenticada declara a ação que exige. Rota pública entra numa lista fixa, justificada aqui."""

from importlib import import_module

from django.urls import URLPattern, get_resolver

from projeto.paginas_autenticadas import PROPRIA_PESSOA

# Sem sessão por desenho: entrar, esqueci a senha e redefinição são de quem ainda não tem credencial; sair é POST com CSRF
# e encerrar uma sessão que não existe é inofensivo.
PUBLICAS = frozenset({'entrar', 'sair', 'esqueci_senha', 'redefinir_senha'})


def _rotas_da_casca():
    # A API e o painel são `URLResolver` (portão próprio: varredura de rotas e admin); aqui só as páginas da casca.
    return [(padrao.name, padrao.callback) for padrao in get_resolver().url_patterns if isinstance(padrao, URLPattern)]


def _autenticadas():
    return [(nome, visao) for nome, visao in _rotas_da_casca() if getattr(visao, 'exige_entrada', False)]


def test_a_varredura_enxerga_as_views_da_casca():
    nomes = {nome for nome, _ in _rotas_da_casca()}
    assert {'inicio', 'empresas', 'empresa', 'fazenda', 'aceitar_convite', 'recusar_convite', 'trocar_senha'} <= nomes


def test_so_as_rotas_publicas_da_lista_ficam_sem_exigir_entrada():
    autenticadas = {nome for nome, _ in _autenticadas()}
    assert {nome for nome, _ in _rotas_da_casca()} - autenticadas == PUBLICAS


def test_toda_view_autenticada_declara_a_acao_que_exige():
    assert [nome for nome, visao in _autenticadas() if getattr(visao, 'acao_exigida', None) is None] == []


def test_acao_declarada_existe_no_catalogo_ou_e_da_propria_pessoa():
    catalogo = {codigo for codigo, _, _ in import_module('permissao.migrations.0001_initial').ACOES}
    assert {getattr(visao, 'acao_exigida') for _, visao in _autenticadas()} <= catalogo | {PROPRIA_PESSOA}


def test_pagina_de_terceiro_declara_a_acao_do_catalogo_e_as_da_pessoa_declaram_a_propria():
    por_nome = dict(_autenticadas())
    for nome in ('empresas', 'empresa', 'fazenda'):
        assert getattr(por_nome[nome], 'acao_exigida') == 'ver'
    for nome in ('inicio', 'aceitar_convite', 'recusar_convite', 'trocar_senha'):
        assert getattr(por_nome[nome], 'acao_exigida') == PROPRIA_PESSOA
