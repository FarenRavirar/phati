"""Menu (R2, A6): só os itens para os quais a pessoa tem permissão efetiva, calculada no servidor a cada requisição."""

import dataclasses

import pytest

from projeto import menu
from projeto.menu import ITENS, Atalho, ItemDoMenu, atalhos_do_inicio, itens_do_menu


ATALHO_POR_EMPRESA = (Atalho('Convidar pessoa', '/empresa/{empresa_id}/pessoas/convidar', 'convidar_pessoa'),)


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


def test_ninguem_ve_a_ponte_de_gestao(cenario, fabrica_pessoa, conceder_direto, plataforma):
    # R24: o item sai do menu de todos os papéis; o painel é endereço, não link.
    administrador = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    assert _nomes(administrador, cenario.x) == ['Início', 'Fazendas', 'Auditoria']  # 005 R6: o Administrador de empresa lê a auditoria
    assert _nomes(plataforma) == ['Início', 'Fazendas', 'Uso do Google', 'Auditoria']  # 004b R13: só a plataforma vê o monitor


@pytest.mark.parametrize('base', ['curador', 'tecnico', 'usuario'])
def test_auditoria_nao_aparece_a_quem_nao_e_administrador_de_empresa(cenario, fabrica_pessoa, conceder_direto, base):
    pessoa = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x[base], cenario.x)
    assert 'Auditoria' not in _nomes(pessoa)
    assert 'Auditoria' not in _nomes(pessoa, cenario.x)


def test_auditoria_nao_aparece_a_administrador_so_de_fazenda_nem_a_quem_nao_tem_acesso(cenario, fabrica_pessoa, conceder_direto):
    so_fazenda = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.f1)
    assert 'Auditoria' not in _nomes(so_fazenda)
    assert 'Auditoria' not in _nomes(fabrica_pessoa('Sem acesso'))


def test_item_auditoria_aponta_para_a_pagina(cenario, plataforma):
    item = next(item for item in itens_do_menu(plataforma) if item.nome == 'Auditoria')
    assert item.caminho == '/auditoria/'


def test_auditoria_e_item_de_dado_com_acao_e_em_empresa(cenario, plataforma):
    # Regra por dado (critério dinâmico): nada de predicado por item; o item traz a ação e o alcance dela.
    item = next(item for item in ITENS if item.nome == 'Auditoria')
    assert item.acoes == ('ver_auditoria',)
    assert item.em_empresa is True
    assert 'visivel_se' not in {campo.name for campo in dataclasses.fields(ItemDoMenu)}


def test_todo_item_com_em_empresa_tem_acao():
    # Sem ação, o item é de toda pessoa autenticada e `em_empresa` não teria o que checar: some para todos, em silêncio.
    assert all(item.acoes for item in ITENS if item.em_empresa)


@pytest.mark.parametrize('base', ['administrador', 'curador', 'tecnico', 'usuario'])
def test_so_a_plataforma_ve_o_item_do_monitor(cenario, fabrica_pessoa, conceder_direto, base):
    pessoa = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x[base], cenario.x)
    assert 'Uso do Google' not in _nomes(pessoa, cenario.x)


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


def test_atalho_por_empresa_leva_ao_caminho_da_empresa_e_so_a_quem_tem_a_acao(cenario, fabrica_pessoa, conceder_direto, plataforma, monkeypatch):
    monkeypatch.setattr(menu, 'ATALHOS', ATALHO_POR_EMPRESA)
    administrador = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    curador_da_fazenda = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.f1)
    usuario = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.f1)
    esperado = [('Convidar pessoa', f'/empresa/{cenario.x.pk}/pessoas/convidar')]
    for quem in (administrador, curador_da_fazenda):
        assert [(a.nome, a.caminho) for a in atalhos_do_inicio(quem)] == esperado
    assert atalhos_do_inicio(usuario) == []
    assert atalhos_do_inicio(plataforma) == []  # a plataforma escolhe a empresa na lista do Início


def test_atalho_por_empresa_com_duas_empresas_traz_um_link_para_cada_com_o_nome_da_empresa(cenario, fabrica_pessoa, conceder_direto, monkeypatch):
    monkeypatch.setattr(menu, 'ATALHOS', ATALHO_POR_EMPRESA)
    pessoa = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    conceder_direto(pessoa, cenario.cargos_y['administrador'], cenario.y)
    assert sorted((a.nome, a.caminho) for a in atalhos_do_inicio(pessoa)) == [
        ('Convidar pessoa · Empresa X', f'/empresa/{cenario.x.pk}/pessoas/convidar'),
        ('Convidar pessoa · Empresa Y', f'/empresa/{cenario.y.pk}/pessoas/convidar'),
    ]


def test_atalho_nao_lista_empresa_arquivada(cenario, fabrica_pessoa, conceder_direto, monkeypatch):
    monkeypatch.setattr(menu, 'ATALHOS', ATALHO_POR_EMPRESA)
    from territorio.cadastro import arquivar, efeitos_do_arquivamento

    pessoa = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    arquivar(pessoa, cenario.x, efeitos_do_arquivamento(cenario.x))
    assert atalhos_do_inicio(pessoa) == []
