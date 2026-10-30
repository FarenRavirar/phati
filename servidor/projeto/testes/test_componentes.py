"""Componentes base e travas de estilo (R13, R15; A12, A19): cada componente renderiza e o CSS segue os tokens."""

import re
from pathlib import Path

import pytest
from django.template.loader import render_to_string

RAIZ = Path(__file__).resolve().parent.parent
TEMPLATES = RAIZ / 'templates'
ESTATICOS = RAIZ / 'static' / 'projeto'


def _renderizar(modelo, **contexto):
    return render_to_string(modelo, contexto)


def test_botao():
    html = _renderizar('componentes/botao.html', texto='Salvar', tipo='submit')
    assert '<button class="botao" type="submit">Salvar</button>' in html
    assert 'botao-secundario' in _renderizar('componentes/botao.html', texto='x', secundario=True)
    assert ' disabled' in _renderizar('componentes/botao.html', texto='x', desabilitado=True)


def test_campo_liga_rotulo_e_erro_ao_controle():
    html = _renderizar('componentes/campo.html', id='cpf', nome='cpf', rotulo='CPF', erro='CPF ou senha incorretos.')
    assert '<label class="campo-rotulo" for="cpf">CPF</label>' in html
    assert 'aria-invalid="true"' in html and 'aria-describedby="cpf-descricao"' in html
    assert 'id="cpf-descricao"' in html and 'CPF ou senha incorretos.' in html
    sem_erro = _renderizar('componentes/campo.html', id='cpf', nome='cpf', rotulo='CPF')
    assert 'aria-invalid' not in sem_erro and 'aria-describedby' not in sem_erro


@pytest.mark.parametrize('tipo', ['erro', 'aviso', 'info', 'sucesso'])
def test_aviso_tem_cor_icone_e_texto(tipo):
    html = _renderizar('componentes/aviso.html', tipo=tipo, texto='Texto do aviso')
    assert f'aviso-{tipo}' in html and '<svg' in html and 'aria-hidden="true"' in html and 'Texto do aviso' in html


def test_aviso_de_erro_e_anunciado_na_hora():
    assert 'role="alert"' in _renderizar('componentes/aviso.html', tipo='erro', texto='x')
    assert 'role="alert"' not in _renderizar('componentes/aviso.html', tipo='info', texto='x')


def test_vazio_e_cabecalho_e_tabela():
    assert 'Sem camadas ainda.' in _renderizar('componentes/vazio.html', texto='Sem camadas ainda.')
    assert '<h1>Fazendas</h1>' in _renderizar('componentes/cabecalho_pagina.html', titulo='Fazendas')
    html = _renderizar('componentes/tabela.html', legenda='Fazendas', colunas=['Nome'], linhas=[['F1'], ['F2']])
    assert 'class="tabela-rolavel"' in html and '<th scope="col">Nome</th>' in html and '<td>F2</td>' in html


def test_lista_de_convites_tem_aceitar_e_recusar_com_csrf_e_data_brasileira():
    from datetime import datetime, timezone

    convites = [{'id': 7, 'empresa_nome': 'Empresa X', 'cargo_nome': 'Técnico', 'expira_em': datetime(2026, 11, 5, 15, tzinfo=timezone.utc)}]
    html = render_to_string('componentes/lista_convites.html', {'convites': convites}, request=_requisicao())
    assert 'action="/convites/7/aceitar"' in html and 'action="/convites/7/recusar"' in html
    assert html.count('csrfmiddlewaretoken') == 2
    assert '05/11/2026' in html  # A21: dd/mm/aaaa no fuso local


def _requisicao():
    from django.test import RequestFactory

    return RequestFactory().get('/')


def test_cor_so_existe_no_arquivo_de_variaveis():
    achados = [
        arquivo.name
        for arquivo in [*ESTATICOS.glob('*.css'), *TEMPLATES.rglob('*.html')]
        if arquivo.name != 'tokens.css' and re.search(r'#[0-9A-Fa-f]{6}\b|\brgba?\(|\bhsla?\(', arquivo.read_text(encoding='utf-8'))
    ]
    assert achados == []


def test_template_nao_tem_script_inline_nem_estilo_inline():
    # `redefinir_senha.html` leva o script inline com nonce até a Fase 3 da 002 movê-lo para `redefinir-senha.js` (T3.4).
    transitorios = {'redefinir_senha.html'}
    for arquivo in TEMPLATES.rglob('*.html'):
        texto = arquivo.read_text(encoding='utf-8')
        if arquivo.name not in transitorios:
            assert not re.search(r'<script\b(?![^>]*\bsrc=)', texto), arquivo.name
        assert not re.search(r'<style\b|\sstyle=', texto), arquivo.name


def test_todo_script_e_link_de_estilo_dos_moldes_leva_nonce():
    for molde in ('casca.html', 'publica.html'):
        texto = (TEMPLATES / molde).read_text(encoding='utf-8')
        for etiqueta in re.findall(r'<(?:script|link)\b[^>]*>', texto):
            assert '{% csp_nonce_attr %}' in etiqueta, (molde, etiqueta)


def test_outline_none_so_com_substituto():
    for arquivo in ESTATICOS.glob('*.css'):
        texto = arquivo.read_text(encoding='utf-8')
        if re.search(r'outline:\s*(none|0)\b', texto):
            assert ':focus-visible' in texto, arquivo.name
    assert ':focus-visible' in (ESTATICOS / 'base.css').read_text(encoding='utf-8')
