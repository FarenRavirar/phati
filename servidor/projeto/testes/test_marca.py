"""Marca AgriOn (spec 012, R5): nenhuma tela renderizada, painel, resposta de erro nem remetente mostra o nome antigo."""

import json
import re
from pathlib import Path

import pytest
from django.contrib import admin
from django.template.loader import get_template
from django.test import Client

from projeto.painel import PainelSite

RAIZ = Path(__file__).resolve().parents[2]  # servidor/


def _sem_ruido(html):
    # Nonce de CSP e token CSRF são aleatórios e podem conter o trecho procurado (E012).
    return re.sub(r'nonce="[^"]*"|name="csrfmiddlewaretoken" value="[^"]+"', '', html)


def _afirma_marca(html, caminho):
    assert 'AgriOn' in html, caminho  # a página de fato renderizou com a marca
    assert 'phati' not in html.casefold(), caminho


@pytest.mark.parametrize(('caminho', 'status'), [
    ('/entrar', 200), ('/esqueci-senha', 200), ('/painel/login/', 200), ('/rota-inexistente', 404),
])
def test_tela_renderizada_nao_mostra_o_nome_antigo(caminho, status):
    resposta = Client().get(caminho)
    assert resposta.status_code == status, caminho
    _afirma_marca(_sem_ruido(resposta.content.decode()), caminho)


def test_termos_e_privacidade_com_texto_nao_mostram_o_nome_antigo(tmp_path, settings):
    caminho = tmp_path / 'termos.json'
    caminho.write_text(json.dumps({'termos': 'Texto sintético.', 'privacidade': 'Texto sintético.'}), encoding='utf-8')
    settings.TERMOS_ARQUIVO = str(caminho)
    settings.AMBIENTE = 'producao'
    for pagina in ('/termos', '/privacidade'):
        resposta = Client().get(pagina)
        assert resposta.status_code == 200, pagina
        assert 'phati' not in _sem_ruido(resposta.content.decode()).casefold(), pagina


def test_pagina_de_erro_500_nao_mostra_o_nome_antigo():
    html = get_template('500.html').render({})
    _afirma_marca(html, '500.html')


def test_painel_de_administracao_leva_a_marca_agrion():
    assert isinstance(admin.site, PainelSite)
    assert admin.site.site_header == 'AgriOn'
    assert admin.site.site_title == 'AgriOn'
    assert 'phati' not in f'{admin.site.site_header} {admin.site.site_title} {admin.site.index_title}'.casefold()


def test_resposta_429_do_nginx_leva_a_marca_agrion():
    # A página de 429 é do nginx (`nginx/default.conf`), fora do Django: o teste lê a linha que a devolve.
    linhas = [linha for linha in (RAIZ / 'nginx' / 'default.conf').read_text(encoding='utf-8').splitlines() if 'return 429' in linha]
    # Duas respostas 429: a da API (JSON, sem marca) e a da página (HTML, com a marca). Só a página leva o nome.
    paginas = [linha for linha in linhas if '<!doctype html>' in linha]
    assert len(linhas) == 2 and len(paginas) == 1
    assert 'AgriOn' in paginas[0]
    assert all('phati' not in linha.casefold() for linha in linhas)


def test_remetente_padrao_do_compose_e_o_da_agrion():
    compose = (RAIZ / 'compose.yaml').read_text(encoding='utf-8')
    assert 'PHATI_EMAIL_REMETENTE: ${PHATI_EMAIL_REMETENTE:-agrion@localhost}' in compose
    assert 'PHATI_EMAIL_REMETENTE: ${PHATI_EMAIL_REMETENTE:-phati@localhost}' not in compose
