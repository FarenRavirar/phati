"""Seletor de fazenda (R10, R22; A8): fazendas autorizadas por empresa, nada de fora do escopo no HTML."""

import re

import pytest
from django.test import Client

from territorio.models import Empresa, Fazenda


def _sem_nonce(resposta):
    return re.sub(rb'nonce="[^"]*"', b'', resposta.content)


@pytest.fixture
def cliente_de_x(cliente_logado, conta, cenario, conceder_direto):
    """Administrador de X com 15 fazendas (F1, F2 e mais 13); Y e as fazendas dela ficam de fora."""
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    Fazenda.objects.bulk_create(Fazenda(empresa=cenario.x, nome=f'Fazenda Teste {n:02d}') for n in range(13))
    Fazenda.objects.bulk_create(Fazenda(empresa=cenario.y, nome=f'Fazenda Alheia {n}') for n in range(3))
    return cliente_logado


def test_quinze_fazendas_visiveis_e_as_tres_de_outra_empresa_ausentes_do_html(cliente_de_x):
    html = cliente_de_x.get('/empresas/').content.decode()
    assert html.count('data-fazenda') == 15
    assert len(re.findall(r'Fazenda Teste', html)) == 13
    assert len(re.findall(r'Fazenda Alheia|Empresa Y|>FY<', html)) == 0  # a busca de texto devolve 0 (A8)
    assert 'data-busca-campo' in html
    assert 'busca-fazendas.js' in html


def test_fazendas_vem_agrupadas_por_empresa(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    conceder_direto(conta.pessoa, cenario.cargos_y['administrador'], cenario.y)
    html = cliente_logado.get('/empresas/').content.decode()
    assert html.index('Empresa X') < html.index('>F1<') < html.index('>F2<') < html.index('Empresa Y') < html.index('>FY<')


def test_pessoa_sem_concessao_ve_lista_vazia_sem_nome_de_empresa(cliente_logado, cenario):
    html = cliente_logado.get('/empresas/').content.decode()
    assert 'Nenhuma fazenda disponível.' in html
    assert 'Empresa X' not in html
    assert 'busca-fazendas.js' not in html


def test_pagina_da_empresa_lista_so_as_fazendas_dela(cliente_de_x, cenario):
    html = cliente_de_x.get(f'/empresa/{cenario.x.pk}/').content.decode()
    assert html.count('data-fazenda') == 15
    assert 'Empresa X' in html
    assert 'Empresa Y' not in html


def test_acesso_so_a_uma_fazenda_mostra_so_ela(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['usuario'], cenario.f1)
    html = cliente_logado.get(f'/empresa/{cenario.x.pk}/').content.decode()
    assert html.count('data-fazenda') == 1
    assert '>F1<' in html
    assert '>F2<' not in html


def test_empresa_de_outro_escopo_e_empresa_inexistente_dao_o_mesmo_404(cliente_de_x, cenario):
    de_fora = cliente_de_x.get(f'/empresa/{cenario.y.pk}/')
    inexistente = cliente_de_x.get('/empresa/999999/')
    assert (de_fora.status_code, inexistente.status_code) == (404, 404)
    assert _sem_nonce(de_fora) == _sem_nonce(inexistente)
    assert b'Empresa Y' not in de_fora.content


def test_pessoa_sem_concessao_recebe_404_na_empresa_por_url_direta(cliente_logado, cenario):
    assert cliente_logado.get(f'/empresa/{cenario.x.pk}/').status_code == 404


def test_deslogado_vai_a_entrada_e_senha_temporaria_vai_a_troca(cliente_logado, conta, cenario):
    for caminho in ('/empresas/', f'/empresa/{cenario.x.pk}/'):
        assert Client().get(caminho)['Location'].startswith('/entrar?proximo=')
    conta.pessoa.deve_trocar_senha = True
    conta.pessoa.save(update_fields=['deve_trocar_senha'])
    assert cliente_logado.get('/empresas/')['Location'].startswith('/trocar-senha')


def test_administrador_da_plataforma_ve_todas_as_empresas(cliente_logado, conta, cenario):
    conta.pessoa.administrador_plataforma = True
    conta.pessoa.save(update_fields=['administrador_plataforma'])
    html = cliente_logado.get('/empresas/').content.decode()
    assert Empresa.objects.count() == 2
    assert 'Empresa X' in html
    assert 'Empresa Y' in html
