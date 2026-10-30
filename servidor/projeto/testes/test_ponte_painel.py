"""Ponte transitória para o painel (R24, A18): o item Gestão ↗ leva a /painel/ na mesma sessão, só a quem gere."""

import pytest
from django.test import Client

from permissao.pode import pode
from projeto.menu import itens_do_menu


def _caminhos(pessoa):
    return {item.nome: item.caminho for item in itens_do_menu(pessoa)}


def test_quem_convida_ve_a_ponte_e_chega_ao_painel_sem_nova_entrada(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    admin = fabrica_pessoa('Admin')
    conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    assert pode(admin, 'convidar_pessoa', cenario.x)
    assert _caminhos(admin)['Gestão ↗'] == '/painel/'
    sessao_do_navegador = entrar_no_painel(admin)  # a sessão do painel é a mesma da casca (sessao_vigente nos dois)
    assert sessao_do_navegador.get('/painel/').status_code == 200


@pytest.mark.parametrize('base', ['tecnico', 'usuario'])
def test_quem_nao_gere_nao_ve_a_ponte_e_o_painel_o_redireciona(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel, base):
    pessoa = fabrica_pessoa('Sem gestão')
    conceder_direto(pessoa, cenario.cargos_x[base], cenario.f1)
    assert 'Gestão ↗' not in _caminhos(pessoa)
    assert entrar_no_painel(pessoa).get('/painel/').status_code == 302


def test_anonimo_pedindo_o_painel_vai_a_entrada_dele(db):
    resposta = Client().get('/painel/')
    assert resposta.status_code == 302 and resposta['Location'].startswith('/painel/login/')
