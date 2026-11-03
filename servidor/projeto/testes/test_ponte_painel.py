"""Fim da ponte (R21, R24, A13): sem **Gestão ↗** no menu e /painel/ aberto só à plataforma."""

import pytest
from django.test import Client

from projeto.menu import itens_do_menu


@pytest.mark.parametrize('base', ['administrador', 'curador'])
def test_quem_convida_nao_ve_a_ponte_e_e_barrado_no_painel(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel, base):
    pessoa = fabrica_pessoa('Gestor')
    conceder_direto(pessoa, cenario.cargos_x[base], cenario.x if base == 'administrador' else cenario.f1)
    assert 'Gestão ↗' not in [item.nome for item in itens_do_menu(pessoa)]
    assert entrar_no_painel(pessoa).get('/painel/').status_code == 302


def test_plataforma_abre_o_painel_e_o_link_do_site_leva_ao_inicio(plataforma, entrar_no_painel):
    pagina = entrar_no_painel(plataforma).get('/painel/')
    assert pagina.status_code == 200
    assert 'href="/"' in pagina.content.decode()


def test_anonimo_pedindo_o_painel_vai_a_entrada_dele(db):
    resposta = Client().get('/painel/')
    assert resposta.status_code == 302
    assert resposta['Location'].startswith('/painel/login/')
