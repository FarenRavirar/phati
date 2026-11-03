"""Mapa de teste de layout (004 R1, R3, R21; A1, A3): flag, acesso e política de conteúdo só na resposta que leva o mapa."""

import re

import pytest
from django.test import Client, override_settings

from projeto import mapa


def _caminho(empresa, fazenda):
    return f'/empresa/{empresa.pk}/fazenda/{fazenda.pk}/'


def _politica(resposta):
    return resposta['Content-Security-Policy']


def _diretiva(politica, nome):
    return next(p for p in politica.split('; ') if p.startswith(nome + ' '))


@pytest.fixture
def pagina(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    return lambda: cliente_logado.get(_caminho(cenario.x, cenario.f1))


def test_flag_desligada_e_o_padrao_e_a_pagina_nao_traz_o_mapa(pagina):
    assert mapa.mapa_ativo() is False
    resposta = pagina()
    html = resposta.content.decode()
    assert resposta.status_code == 200
    for rastro in ('maplibre', 'projeto/mapa.js', 'data-mapa'):
        assert rastro not in html, rastro
    assert 'O mapa aparece quando a fazenda tiver camadas.' in html


def test_flag_desligada_deixa_a_politica_da_002_sem_blob_nem_worker(pagina):
    politica = _politica(pagina())
    assert 'blob:' not in politica
    assert 'worker-src' not in politica


@override_settings(MAPA_TESTE_ATIVO=True)
def test_flag_ligada_a_pagina_carrega_o_mapa_como_modulo_com_o_nonce_da_resposta(pagina):
    resposta = pagina()
    html = resposta.content.decode()
    assert resposta.status_code == 200
    nonce = re.findall(r"'nonce-([\w-]+)'", _diretiva(_politica(resposta), 'script-src'))[0]
    assert re.search(rf'<script type="module" src="/static/projeto/mapa\.js" nonce="{nonce}">', html)
    assert re.search(rf'<link rel="stylesheet" href="/static/projeto/terceiros/maplibre/maplibre-gl\.css" nonce="{nonce}">', html)
    assert 'data-mapa' in html
    assert re.search(r'<div data-mapa-aviso hidden>.*Não foi possível abrir o mapa', html, re.S)
    assert 'O mapa aparece quando a fazenda tiver camadas.' not in html


@override_settings(MAPA_TESTE_ATIVO=True)
def test_flag_ligada_a_politica_do_mapa_so_acrescenta_blob_e_worker(pagina):
    politica = _politica(pagina())
    assert _diretiva(politica, 'img-src') == "img-src 'self' data: blob:"
    assert _diretiva(politica, 'worker-src') == "worker-src 'self' blob:"
    for sem in ('unsafe-eval', 'unsafe-inline'):
        assert sem not in politica
    assert "script-src 'self' 'nonce-" in politica
    assert "object-src 'none'" in politica and "frame-ancestors 'none'" in politica


@override_settings(MAPA_TESTE_ATIVO=True)
def test_flag_ligada_as_outras_respostas_ficam_com_a_politica_da_002(cliente_logado):
    for caminho in ('/', '/empresas/', '/entrar'):
        politica = _politica(cliente_logado.get(caminho))
        assert 'blob:' not in politica, caminho
        assert 'worker-src' not in politica, caminho


@override_settings(MAPA_TESTE_ATIVO=True)
def test_flag_ligada_sem_alcance_da_o_mesmo_404_de_fazenda_inexistente(cliente_logado, cenario):
    # Controle de acesso negativo (AGENTS §Testes): a pessoa não tem concessão em X; por URL direta, 404 sem o mapa.
    sem_alcance = cliente_logado.get(_caminho(cenario.x, cenario.f1))
    inexistente = cliente_logado.get(f'/empresa/{cenario.x.pk}/fazenda/999999/')
    assert sem_alcance.status_code == inexistente.status_code == 404
    assert 'data-mapa' not in sem_alcance.content.decode()
    assert 'blob:' not in _politica(sem_alcance)


@override_settings(MAPA_TESTE_ATIVO=True)
def test_flag_ligada_deslogado_vai_para_a_entrada(cenario):
    resposta = Client().get(_caminho(cenario.x, cenario.f1))
    assert resposta.status_code == 302
    assert resposta['Location'].startswith('/entrar')
