"""Termos de uso e Política de privacidade (004b R15, A11): públicas, texto escapado, 404 sem texto fora do local."""

import json
import os

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
def test_com_texto_responde_200_deslogado_com_termos_e_privacidade_do_google(arquivo, caminho):
    resposta = Client().get(caminho)
    html = resposta.content.decode()
    assert resposta.status_code == 200
    assert 'href="https://maps.google.com/help/terms_maps/"' in html
    assert 'href="https://policies.google.com/privacy"' in html


def test_texto_do_mantenedor_aparece_em_paragrafos_e_html_e_escapado(arquivo):
    html = Client().get('/termos').content.decode()
    assert '<p>Primeiro parágrafo.</p>' in html
    assert '<script>alert(1)</script>' not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html


def test_paginas_nao_afirmam_script_de_analise_da_cloudflare_por_conta_propria(arquivo):
    # Analytics da Cloudflare desligado (decisão do mantenedor, 2026-11-06): só o texto do arquivo pode falar de Cloudflare.
    for caminho in ('/termos', '/privacidade'):
        assert 'Cloudflare' not in Client().get(caminho).content.decode()


def test_rodape_linka_as_duas_paginas_deslogado_e_logado(arquivo, cliente_logado):
    for cliente in (Client(), cliente_logado):
        html = cliente.get('/termos').content.decode() if cliente is not cliente_logado else cliente.get('/').content.decode()
        assert 'href="/termos"' in html
        assert 'href="/privacidade"' in html


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


def _escrever(caminho, conteudo):
    caminho.write_text(json.dumps(conteudo), encoding='utf-8')
    return str(caminho)


@pytest.mark.parametrize('separador', ['\n\n', '\n \n', '\n\t\n', '\n   \n\n'])
def test_linha_so_com_espacos_separa_paragrafos(tmp_path, settings, separador):
    settings.TERMOS_ARQUIVO = _escrever(tmp_path / 't.json', {'termos': f'Primeiro.{separador}Segundo.'})
    assert termos.paragrafos('termos') == ['Primeiro.', 'Segundo.']


def test_arquivo_trocado_e_lido_de_novo_e_o_mesmo_nao_e_relido(tmp_path, settings, monkeypatch):
    caminho = tmp_path / 't.json'
    settings.TERMOS_ARQUIVO = _escrever(caminho, {'termos': 'Antes.'})
    leituras = []
    original = termos.Path.read_text
    monkeypatch.setattr(termos.Path, 'read_text', lambda self, **kw: leituras.append(1) or original(self, **kw))
    assert termos.paragrafos('termos') == ['Antes.']
    assert termos.paragrafos('termos') == ['Antes.']
    assert len(leituras) == 1  # a segunda chamada vem do cache
    _escrever(caminho, {'termos': 'Depois.'})
    novo = os.stat(caminho).st_mtime_ns + 1_000_000_000
    os.utime(caminho, ns=(novo, novo))
    assert termos.paragrafos('termos') == ['Depois.']
    assert len(leituras) == 2


@pytest.mark.parametrize(('so', 'outra'), [('termos', 'privacidade'), ('privacidade', 'termos')])
def test_com_uma_so_secao_o_rodape_linka_so_ela_e_a_outra_da_404(tmp_path, settings, so, outra):
    settings.AMBIENTE = 'producao'
    settings.TERMOS_ARQUIVO = _escrever(tmp_path / 't.json', {so: 'Texto sintético.'})
    assert [caminho for caminho, _ in termos.disponiveis(None)['termos_links']] == [f'/{so}']
    cliente = Client()
    assert cliente.get(f'/{so}').status_code == 200
    assert cliente.get(f'/{outra}').status_code == 404
