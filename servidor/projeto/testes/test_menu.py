"""Menu (R2, A6): só os itens para os quais a pessoa tem permissão efetiva, calculada no servidor a cada requisição."""

import pytest

from projeto import menu
from projeto.menu import ITENS, Atalho, atalhos_do_inicio, itens_do_menu


def _nomes(pessoa, escopo=None):
    return [item.nome for item in itens_do_menu(pessoa, escopo)]


def _com(fabrica_pessoa, conceder_direto, cargo, escopo):
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cargo, escopo)
    return pessoa


@pytest.mark.parametrize('base', ['tecnico', 'usuario'])
def test_tecnico_e_usuario_so_veem_inicio_e_fazendas(cenario, fabrica_pessoa, conceder_direto, base):
    pessoa = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x[base], cenario.f1)
    assert _nomes(pessoa) == _nomes(pessoa, cenario.f1) == ['Início', 'Fazendas']


def test_pessoa_sem_concessao_ve_so_inicio_e_fazendas(cenario, fabrica_pessoa):
    assert _nomes(fabrica_pessoa('Sem acesso')) == ['Início', 'Fazendas']


def test_administrador_da_empresa_ve_a_ponte_de_gestao(cenario, fabrica_pessoa, conceder_direto):
    pessoa = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    assert _nomes(pessoa, cenario.x) == ['Início', 'Fazendas', 'Gestão ↗']


def test_administrador_da_plataforma_ve_a_ponte_de_gestao(plataforma):
    assert _nomes(plataforma) == ['Início', 'Fazendas', 'Gestão ↗']


def test_ponte_de_gestao_vale_em_qualquer_escopo_nao_so_no_atual(cenario, fabrica_pessoa, conceder_direto):
    # Administrador da empresa X olhando a empresa Y: a ponte abre o painel inteiro, então o escopo atual não a esconde.
    pessoa = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    assert 'Gestão ↗' in _nomes(pessoa, cenario.y)


def test_toda_pessoa_autenticada_tem_os_dois_primeiros_itens():
    assert [item.nome for item in ITENS if not item.acoes] == ['Início', 'Fazendas']


@pytest.mark.parametrize(
    ('caminho', 'atual'),
    [
        ('/', {'Início': 'page'}),
        ('/empresas/', {'Fazendas': 'page'}),
        ('/empresa/1/', {'Fazendas': 'true'}),
        ('/empresa/1/fazenda/2/', {'Fazendas': 'true'}),
        ('/convites/1/aceitar', {}),
        (None, {}),
    ],
)
def test_marca_o_item_atual_pelo_caminho_e_pelas_paginas_filhas(fabrica_pessoa, caminho, atual):
    itens = itens_do_menu(fabrica_pessoa('Pessoa'), None, caminho)
    assert {item.nome: item.atual for item in itens if item.atual} == atual


def test_atalho_vem_da_acao_efetiva_nunca_do_papel(cenario, fabrica_pessoa, conceder_direto, monkeypatch):
    monkeypatch.setattr(menu, 'ATALHOS', (Atalho('Convidar pessoa', '/x/', 'convidar_pessoa'),))
    administrador = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    usuario = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.f1)
    assert [a.nome for a in atalhos_do_inicio(administrador)] == ['Convidar pessoa']
    assert atalhos_do_inicio(usuario) == []
