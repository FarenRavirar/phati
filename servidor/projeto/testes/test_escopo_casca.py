"""Empresa escolhida e alcance (R17, D063): as funções de `projeto/escopo.py` que a casca, o menu e o seletor usam.
Negativos: empresa sem acesso lembrada é descartada da sessão; sem concessão, o seletor fica vazio."""

from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory

from projeto.escopo import CHAVE_EMPRESA, alcance_na_empresa, cargos_na_empresa, empresa_lembrada, seletor_da_pessoa


def _requisicao(pessoa):
    requisicao = RequestFactory().get('/')
    requisicao.session = SessionStore()
    requisicao.user = pessoa
    return requisicao


def test_alcance_da_empresa_inteira_vale_para_fazenda_so_sem_o_modo_inteira(cenario, fabrica_pessoa, conceder_direto):
    admin_fazenda = fabrica_pessoa('Admin de fazenda')
    conceder_direto(admin_fazenda, cenario.cargos_x['administrador'], cenario.f1)
    assert alcance_na_empresa(admin_fazenda, cenario.x, ('convidar_pessoa',)) is True
    assert alcance_na_empresa(admin_fazenda, cenario.x, ('gerenciar_cargo',), inteira=True) is False  # negativo: cargo é da empresa inteira


def test_alcance_negado_a_quem_nao_tem_a_acao_ou_a_empresa(cenario, fabrica_pessoa, conceder_direto):
    usuario = fabrica_pessoa('Usuário')
    conceder_direto(usuario, cenario.cargos_x['usuario'], cenario.f1)
    admin_x = fabrica_pessoa('Admin de X')
    conceder_direto(admin_x, cenario.cargos_x['administrador'], cenario.x)
    assert alcance_na_empresa(usuario, cenario.x, ('convidar_pessoa',)) is False
    assert alcance_na_empresa(admin_x, cenario.y, ('convidar_pessoa',)) is False


def test_plataforma_tem_alcance_em_qualquer_empresa(cenario, plataforma):
    assert alcance_na_empresa(plataforma, cenario.y, ('gerenciar_cargo',), inteira=True) is True


def test_lembrada_sem_escolha_e_so_com_uma_empresa_alcancada(cenario, fabrica_pessoa, conceder_direto, db):
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    achada = empresa_lembrada(_requisicao(pessoa))
    assert achada is not None
    assert achada.pk == cenario.x.pk


def test_lembrada_sem_escolha_e_com_duas_empresas_fica_vazia(cenario, fabrica_pessoa, conceder_direto, db):
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    conceder_direto(pessoa, cenario.cargos_y['usuario'], cenario.fy)
    assert empresa_lembrada(_requisicao(pessoa)) is None


def test_lembrada_valida_e_devolvida(cenario, fabrica_pessoa, conceder_direto, db):
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    conceder_direto(pessoa, cenario.cargos_y['usuario'], cenario.fy)
    requisicao = _requisicao(pessoa)
    requisicao.session[CHAVE_EMPRESA] = cenario.x.pk
    achada = empresa_lembrada(requisicao)
    assert achada is not None
    assert achada.pk == cenario.x.pk


def test_lembrada_sem_acesso_e_descartada_da_sessao(cenario, fabrica_pessoa, conceder_direto, db):
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    conceder_direto(pessoa, cenario.cargos_y['usuario'], cenario.fy)
    requisicao = _requisicao(pessoa)
    requisicao.session[CHAVE_EMPRESA] = cenario.y.pk
    requisicao.session[CHAVE_EMPRESA] = 0  # id que nunca existiu: também sai, sem consultar nada de fora
    assert empresa_lembrada(requisicao) is None
    assert CHAVE_EMPRESA not in requisicao.session


def test_lembrada_de_empresa_que_a_pessoa_nao_alcanca_e_descartada(cenario, fabrica_pessoa, conceder_direto, db):
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    requisicao = _requisicao(pessoa)
    requisicao.session[CHAVE_EMPRESA] = cenario.y.pk
    # Só X é alcançada: sem a chave válida, a padrão é X e a chave de Y sai da sessão.
    achada = empresa_lembrada(requisicao)
    assert achada is not None
    assert achada.pk == cenario.x.pk
    assert CHAVE_EMPRESA not in requisicao.session


def test_seletor_lista_so_o_que_a_pessoa_alcanca(cenario, fabrica_pessoa, conceder_direto, db):
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    seletor = seletor_da_pessoa(pessoa)
    assert [e.pk for e in seletor['empresas']] == [cenario.x.pk]
    assert [(e.pk, f.pk) for e, f in seletor['fazendas']] == [(cenario.x.pk, cenario.f1.pk)]
    assert seletor['arquivadas'] is False


def test_seletor_de_quem_nao_tem_concessao_fica_vazio(fabrica_pessoa, db):
    seletor = seletor_da_pessoa(fabrica_pessoa('Sem acesso'))
    assert (seletor['empresas'], seletor['fazendas']) == ([], [])


def test_cargos_na_empresa_mostram_o_cargo_da_empresa_escolhida(cenario, fabrica_pessoa, conceder_direto, db):
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.x)
    assert cargos_na_empresa(pessoa, cenario.x) == [cenario.cargos_x['administrador'].nome]


def test_cargos_do_lugar_mais_amplo_ao_mais_estreito(cenario, fabrica_pessoa, conceder_direto, db):
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.x)
    assert cargos_na_empresa(pessoa, cenario.x) == [cenario.cargos_x['administrador'].nome, cenario.cargos_x['usuario'].nome]


def test_cargos_negativos_sem_empresa_ou_de_outra_empresa(cenario, fabrica_pessoa, conceder_direto, db):
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.x)
    assert cargos_na_empresa(pessoa, None) == []
    assert cargos_na_empresa(pessoa, cenario.y) == []
