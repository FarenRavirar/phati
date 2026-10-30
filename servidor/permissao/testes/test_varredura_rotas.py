"""Varredura de rotas (R17, R19; T5.1): nenhuma rota da API fica sem autenticação nem sem `pode()`.

Rota pública e rota que só toca a própria sessão são listas fixas, justificadas aqui: rota nova que não entre
em nenhuma das duas precisa de `exige_permissao`, senão este teste falha.
"""

from importlib import import_module

import pytest

from projeto.api import api

# Sem sessão por desenho: quem ainda não tem credencial entra, pede ou confirma a redefinição, ou renova o token.
PUBLICAS = frozenset({'entrar', 'redefinir_senha_solicitar', 'redefinir_senha_confirmar', 'acesso_renovar'})
# Autenticadas, mas sem alvo de terceiro: encerram a sessão da própria pessoa, trocam a senha dela (R15) ou respondem
# aos convites dirigidos a ela (R24; o id do convite só alcança convite dela e a permissão de quem convidou é refeita no aceite).
DA_PROPRIA_PESSOA = frozenset({'sair', 'trocar_senha', 'convites_listar', 'convites_aceitar', 'convites_recusar'})


def _operacoes():
    esquema = api.get_openapi_schema()
    achadas = []
    for _, roteador in api._routers:
        for caminho, vista in roteador.path_operations.items():
            for operacao in vista.operations:
                for metodo in operacao.methods:
                    achadas.append((operacao, esquema['paths'][f'/api/v1/{caminho}'][metodo.lower()]))
    return achadas


def test_a_varredura_enxerga_as_rotas_da_api():
    assert len(_operacoes()) >= 10


def test_so_as_rotas_publicas_da_lista_ficam_sem_autenticacao():
    sem_seguranca = {operacao.url_name for operacao, esquema in _operacoes() if not esquema.get('security')}
    assert sem_seguranca == PUBLICAS


def test_toda_rota_nao_publica_exige_permissao_ou_e_da_propria_pessoa():
    soltas = [
        operacao.url_name
        for operacao, esquema in _operacoes()
        if esquema.get('security')
        and operacao.url_name not in DA_PROPRIA_PESSOA
        and getattr(operacao.view_func, 'acao_exigida', None) is None
    ]
    assert soltas == []


def test_rotas_da_propria_pessoa_nao_carregam_alvo_de_terceiro():
    for operacao, _ in _operacoes():
        if operacao.url_name in DA_PROPRIA_PESSOA:
            assert getattr(operacao.view_func, 'acao_exigida', None) is None
            assert '{' not in str(operacao.url_name)


def test_acao_exigida_existe_no_catalogo():
    catalogo = {codigo for codigo, _, _ in import_module('permissao.migrations.0001_initial').ACOES}
    usadas = {getattr(operacao.view_func, 'acao_exigida', None) for operacao, _ in _operacoes()} - {None}
    assert usadas <= catalogo


def test_listagem_so_em_rota_de_leitura():
    for operacao, _ in _operacoes():
        if getattr(operacao.view_func, 'listagem', False):
            assert operacao.methods == ['GET']


@pytest.mark.parametrize('prefixo', ['/docs', '/openapi.json'])
def test_documentacao_automatica_do_ninja_fica_desligada(prefixo):
    from django.test import Client

    assert Client().get(f'/api/v1{prefixo}').status_code == 404
