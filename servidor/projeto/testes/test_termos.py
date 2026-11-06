"""Termos de uso e Política de privacidade (004b R15, A11): públicas, texto escapado, 404 sem texto fora do local."""

import json

import pytest
from django.test import Client

from projeto import termos

TEXTO = {'termos': 'Primeiro parágrafo.\n\nSegundo <script>alert(1)</script>.', 'privacidade': 'Política sintética.'}


@pytest.fixture
def arquivo(tmp_path, settings):
    caminho = tmp_path / 'termos.json'
    caminho.write_text(json.dumps(TEXTO), encoding='utf-8')
    settings.TERMOS_ARQUIVO = str(caminho)
    return caminho


@pytest.mark.parametrize('caminho', ['/termos', '/privacidade'])
def test_com_texto_responde_200_deslogado_com_aviso_do_google(arquivo, caminho):
    resposta = Client().get(caminho)
    html = resposta.content.decode()
    assert resposta.status_code == 200
    assert 'https://cloud.google.com/maps-platform/terms' in html


def test_texto_do_mantenedor_aparece_em_paragrafos_e_html_e_escapado(arquivo):
    html = Client().get('/termos').content.decode()
    assert '<p>Primeiro parágrafo.</p>' in html
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html


def test_privacidade_diz_do_script_de_analise_da_cloudflare(arquivo):
    assert 'Cloudflare' in Client().get('/privacidade').content.decode()
    assert 'Cloudflare' not in Client().get('/termos').content.decode()


def test_rodape_linka_as_duas_paginas_deslogado_e_logado(arquivo, cliente_logado):
    for cliente in (Client(), cliente_logado):
        html = cliente.get('/termos').content.decode() if cliente is not cliente_logado else cliente.get('/').content.decode()
        assert 'href="/termos"' in html and 'href="/privacidade"' in html


@pytest.mark.parametrize('ambiente', ['producao', 'homologacao', 'teste'])
def test_sem_texto_fora_do_local_da_404_e_o_rodape_nao_linka(settings, ambiente):
    settings.AMBIENTE = ambiente
    settings.TERMOS_ARQUIVO = ''
    cliente = Client()
    assert cliente.get('/termos').status_code == 404
    assert cliente.get('/privacidade').status_code == 404
    assert 'href="/termos"' not in cliente.get('/entrar').content.decode()


def test_sem_texto_no_local_mostra_o_aviso_de_texto_ausente(settings):
    settings.AMBIENTE = 'local'
    settings.TERMOS_ARQUIVO = ''
    resposta = Client().get('/termos')
    assert resposta.status_code == 200
    assert termos.SEM_TEXTO in resposta.content.decode()


@pytest.mark.parametrize('conteudo', ['não é json', '[]', '{"termos": "  ", "privacidade": 3}'])
def test_arquivo_invalido_ou_vazio_equivale_a_sem_texto(tmp_path, settings, conteudo):
    caminho = tmp_path / 'ruim.json'
    caminho.write_text(conteudo, encoding='utf-8')
    settings.TERMOS_ARQUIVO = str(caminho)
    settings.AMBIENTE = 'producao'
    assert Client().get('/termos').status_code == 404
    assert Client().get('/privacidade').status_code == 404


def test_arquivo_inexistente_equivale_a_sem_texto(tmp_path, settings):
    settings.TERMOS_ARQUIVO = str(tmp_path / 'nao-existe.json')
    settings.AMBIENTE = 'producao'
    assert Client().get('/termos').status_code == 404


def test_so_get(arquivo):
    assert Client().post('/termos').status_code == 405
