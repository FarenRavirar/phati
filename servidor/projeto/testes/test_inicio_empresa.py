"""Seletor de escopo (R17): a rota que grava a empresa escolhida na sessão. Positivo: grava e volta ao destino interno.
Negativos: GET, sem CSRF, anônimo, empresa sem acesso, id inexistente ou hostil, destino externo."""

import re

import pytest
from django.test import Client

from projeto.escopo import CHAVE_EMPRESA
from projeto.testes.conftest import SENHA

ROTA = '/escolher-empresa'


def _chave_em(html):
    achada = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
    assert achada is not None
    return achada.group(1)


@pytest.fixture
def entrada(conta):
    """Cliente que exige CSRF e já entrou como a pessoa da conta."""
    cliente = Client(enforce_csrf_checks=True)
    chave = _chave_em(cliente.get('/entrar').content.decode())
    resposta = cliente.post('/entrar', {'cpf': conta.cpf, 'senha': SENHA, 'csrfmiddlewaretoken': chave})
    assert resposta.status_code == 302
    return cliente


def _postar(cliente, dados):
    chave = _chave_em(cliente.get('/').content.decode())
    return cliente.post(ROTA, {**dados, 'csrfmiddlewaretoken': chave})


def test_escolher_grava_a_empresa_e_volta_ao_destino_interno(entrada, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['usuario'], cenario.f1)
    resposta = _postar(entrada, {'escolhida': cenario.x.pk, 'proximo': f'/empresa/{cenario.x.pk}/'})
    assert (resposta.status_code, resposta['Location']) == (302, f'/empresa/{cenario.x.pk}/')
    assert entrada.session[CHAVE_EMPRESA] == cenario.x.pk


def test_escolhida_vale_para_pessoas_e_cargos_no_menu(entrada, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    _postar(entrada, {'escolhida': cenario.x.pk, 'proximo': '/'})
    html = entrada.get('/').content.decode()
    assert f'href="/empresa/{cenario.x.pk}/pessoas/"' in html
    assert f'href="/empresa/{cenario.x.pk}/cargos/"' in html


def test_empresa_sem_acesso_e_recusada_e_nao_grava(entrada, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['usuario'], cenario.f1)
    resposta = _postar(entrada, {'escolhida': cenario.y.pk, 'proximo': '/'})
    assert resposta.status_code == 404
    assert CHAVE_EMPRESA not in entrada.session


@pytest.mark.parametrize('valor', ['999999', 'abc', '1 OR 1=1', '9' * 30, '-1', '', '<script>'])
def test_id_inexistente_ou_hostil_e_404_e_nao_grava(entrada, conta, cenario, conceder_direto, valor):
    conceder_direto(conta.pessoa, cenario.cargos_x['usuario'], cenario.f1)
    resposta = _postar(entrada, {'escolhida': valor, 'proximo': '/'})
    assert resposta.status_code == 404
    assert CHAVE_EMPRESA not in entrada.session


@pytest.mark.parametrize('destino', ['https://exemplo.invalido/', '//exemplo.invalido/'])
def test_destino_externo_volta_para_a_raiz(entrada, conta, cenario, conceder_direto, destino):
    conceder_direto(conta.pessoa, cenario.cargos_x['usuario'], cenario.f1)
    resposta = _postar(entrada, {'escolhida': cenario.x.pk, 'proximo': destino})
    assert resposta['Location'] == '/'


# Regressão (Codex): a URL prevalece sobre a sessão (D063). Um `proximo` com escopo de outra empresa devolveria à empresa antiga,
# e a troca não teria efeito; o que não tem escopo de empresa, ou é da escolhida, segue como veio.
@pytest.mark.parametrize(('proximo', 'esperado'), [
    ('/empresa/{y}/pessoas/', '/'),
    ('/empresa/{y}/fazenda/1', '/'),
    ('/empresa/{x}/cargos/', '/empresa/{x}/cargos/'),
    ('/empresas/', '/empresas/'),
])
def test_proximo_de_outra_empresa_volta_a_raiz_e_o_resto_fica(entrada, conta, cenario, conceder_direto, proximo, esperado):
    conceder_direto(conta.pessoa, cenario.cargos_x['usuario'], cenario.f1)
    resposta = _postar(entrada, {'escolhida': cenario.x.pk, 'proximo': proximo.format(x=cenario.x.pk, y=cenario.y.pk)})
    assert resposta['Location'] == esperado.format(x=cenario.x.pk, y=cenario.y.pk)
    assert entrada.session[CHAVE_EMPRESA] == cenario.x.pk


def test_get_e_negado_com_405(entrada, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['usuario'], cenario.f1)
    assert entrada.get(f'{ROTA}?empresa_id={cenario.x.pk}').status_code == 405


def test_post_sem_csrf_e_negado(entrada, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['usuario'], cenario.f1)
    assert entrada.post(ROTA, {'escolhida': cenario.x.pk}).status_code == 403
    assert CHAVE_EMPRESA not in entrada.session


def test_anonimo_e_mandado_para_entrar(cenario):
    anonimo = Client(enforce_csrf_checks=True)
    chave = _chave_em(anonimo.get('/entrar').content.decode())  # o CSRF vem antes do portão de sessão: com token, a resposta é a do login
    resposta = anonimo.post(ROTA, {'escolhida': cenario.x.pk, 'csrfmiddlewaretoken': chave})
    assert resposta.status_code == 302
    assert resposta['Location'].startswith('/entrar')


def test_empresa_lembrada_sem_acesso_sai_da_sessao_na_proxima_pagina(entrada, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['usuario'], cenario.f1)
    sessao = entrada.session
    sessao[CHAVE_EMPRESA] = cenario.y.pk
    sessao.save()
    assert entrada.get('/').status_code == 200
    assert CHAVE_EMPRESA not in entrada.session


def test_inicio_mostra_atalho_so_da_empresa_escolhida(entrada, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    conceder_direto(conta.pessoa, cenario.cargos_y['administrador'], cenario.y)
    _postar(entrada, {'escolhida': cenario.x.pk, 'proximo': '/'})
    html = entrada.get('/').content.decode()
    assert f'/empresa/{cenario.x.pk}/pessoas/convidar' in html
    assert f'/empresa/{cenario.y.pk}/pessoas/convidar' not in html


def test_pe_mostra_o_cargo_mais_amplo_e_o_excedente_com_mais_n(entrada, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['usuario'], cenario.f1)
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    _postar(entrada, {'escolhida': cenario.x.pk, 'proximo': '/'})
    html = entrada.get('/').content.decode()
    pe = html.split('<div class="ag-sidebar-pe">')[1].split('</div>')[0]
    assert cenario.cargos_x['administrador'].nome in pe
    assert '+1' in pe  # o cargo do lugar mais estreito vira excedente
