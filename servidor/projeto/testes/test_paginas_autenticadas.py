"""Portão de sessão e molde da casca (R1, R5, R8; A5, A19)."""

import re

import pytest
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.backends.db import SessionStore
from django.http import HttpResponse
from django.test import RequestFactory
from django.utils import timezone

from identidade import sessao
from projeto.paginas_autenticadas import destino_seguro, exige_entrada, renderizar_na_casca


@exige_entrada
def _visao(requisicao):
    return HttpResponse('ok')


def _requisicao(pessoa=None, caminho='/empresa/1/fazenda/2/?aba=a', vigente=True):
    requisicao = RequestFactory().get(caminho)
    requisicao.session = SessionStore()
    requisicao.user = pessoa or AnonymousUser()
    if pessoa is not None:
        sessao.carimbar(requisicao)
        if not vigente:
            requisicao.session['ultima_atividade'] -= 31 * 60  # A5: 31 minutos de ociosidade
    return requisicao


def test_casca_leva_theme_color_igual_a_cor_primaria_do_css_e_o_favicon(db, fabrica_pessoa):
    from pathlib import Path

    import projeto

    variaveis = (Path(projeto.__file__).parent / 'static' / 'projeto' / 'tokens.css').read_text(encoding='utf-8')
    primaria = re.findall(r'--cor-primaria:\s*(#[0-9A-Fa-f]{6})', variaveis)[0]
    html = renderizar_na_casca(_requisicao(fabrica_pessoa('Pessoa'), '/'), 'inicio.html').content.decode()
    assert f'<meta name="theme-color" content="{primaria}">' in html
    assert '<link rel="icon" href="/static/projeto/favicon.svg"' in html


def test_deslogado_vai_a_entrada_com_a_pagina_pedida(db):
    resposta = _visao(_requisicao())
    assert (resposta.status_code, resposta['Location']) == (302, '/entrar?proximo=%2Fempresa%2F1%2Ffazenda%2F2%2F%3Faba%3Da')


def test_sessao_vencida_vai_a_entrada_com_o_aviso_e_perde_a_sessao(db, fabrica_pessoa):
    requisicao = _requisicao(fabrica_pessoa('Pessoa'), vigente=False)
    resposta = _visao(requisicao)
    assert resposta.status_code == 302
    assert resposta['Location'].startswith('/entrar?')
    assert 'expirou=1' in resposta['Location']
    assert 'entrada_em' not in requisicao.session  # sessão esvaziada, não só ignorada


def test_senha_temporaria_so_ve_a_troca(db, fabrica_pessoa):
    pessoa = fabrica_pessoa('Pessoa')
    pessoa.deve_trocar_senha = True
    resposta = _visao(_requisicao(pessoa))
    assert (resposta.status_code, resposta['Location']) == (302, '/trocar-senha?proximo=%2Fempresa%2F1%2Ffazenda%2F2%2F%3Faba%3Da')  # a página pedida segue junto
    assert _visao(_requisicao(pessoa, '/trocar-senha')).status_code == 200  # a própria troca não entra em laço


def test_pessoa_com_sessao_vigente_passa_e_a_pagina_nao_fica_em_cache(db, fabrica_pessoa):
    resposta = _visao(_requisicao(fabrica_pessoa('Pessoa')))
    assert resposta.status_code == 200
    assert 'no-store' in resposta['Cache-Control']


def test_sessao_vigente_renova_a_atividade(db, fabrica_pessoa):
    requisicao = _requisicao(fabrica_pessoa('Pessoa'))
    requisicao.session['ultima_atividade'] -= 60
    antes = requisicao.session['ultima_atividade']
    _visao(requisicao)
    assert antes < requisicao.session['ultima_atividade'] <= timezone.now().timestamp()


@pytest.mark.parametrize('destino', ['https://externo.exemplo/', '//externo.exemplo/', '\\\\externo.exemplo', 'javascript:alert(1)', '', None])
def test_proximo_externo_ou_vazio_cai_em_barra(destino):
    assert destino_seguro(destino) == '/'


@pytest.mark.parametrize('destino', ['/empresa/1/fazenda/2/', '/empresas/?q=a'])
def test_proximo_interno_e_aceito(destino):
    assert destino_seguro(destino) == destino


def test_casca_tem_faixa_menu_conteudo_e_escopo(cenario, fabrica_pessoa, conceder_direto):
    pessoa = fabrica_pessoa('Fulana Sintetica')
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    html = renderizar_na_casca(_requisicao(pessoa, '/empresas/'), 'casca.html', empresa=cenario.x, fazenda=cenario.f1).content.decode()
    assert '<html lang="pt-BR">' in html
    assert '<header class="faixa">' in html
    assert '<nav class="menu"' in html
    assert '<main class="conteudo">' in html
    assert '>Empresa X</a> › <a href=' in html  # faixa com o escopo atual, em links
    assert '>F1</a>' in html
    assert 'Fulana Sintetica' in html
    assert 'action="/sair"' in html
    assert 'csrfmiddlewaretoken' in html
    assert 'href="/empresas/" aria-current="page"' in html
    assert 'Início' in html
    assert 'Gestão' not in html  # Usuário não vê a ponte


def test_menu_marca_page_na_propria_pagina_e_true_na_pagina_filha(cenario, fabrica_pessoa, conceder_direto):
    pessoa = fabrica_pessoa('Fulana Sintetica')
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    propria = renderizar_na_casca(_requisicao(pessoa, '/empresas/'), 'casca.html', empresa=cenario.x).content.decode()
    filha = renderizar_na_casca(_requisicao(pessoa, f'/empresa/{cenario.x.pk}/'), 'casca.html', empresa=cenario.x).content.decode()
    assert 'href="/empresas/" aria-current="page"' in propria
    assert 'href="/empresas/" aria-current="true"' in filha
    assert 'aria-current="page"' not in filha.split('<nav class="menu"')[1]  # a trilha da faixa marca a empresa, o menu não


def test_casca_sem_escopo_deixa_a_faixa_vazia(cenario, fabrica_pessoa):
    html = renderizar_na_casca(_requisicao(fabrica_pessoa('Pessoa'), '/'), 'casca.html').content.decode()
    assert '<nav class="faixa-escopo" aria-label="Escopo atual"></nav>' in html


def test_post_sem_sessao_nao_leva_proximo_porque_o_endereco_so_aceita_post(db):
    requisicao = RequestFactory().post('/convites/1/aceitar')
    requisicao.session = SessionStore()
    requisicao.user = AnonymousUser()
    assert _visao(requisicao)['Location'] == '/entrar'


def test_post_com_senha_temporaria_vai_a_troca_sem_proximo(db, fabrica_pessoa):
    pessoa = fabrica_pessoa('Pessoa')
    pessoa.deve_trocar_senha = True
    requisicao = RequestFactory().post('/convites/1/aceitar')
    requisicao.session = SessionStore()
    requisicao.user = pessoa
    sessao.carimbar(requisicao)
    assert _visao(requisicao)['Location'] == '/trocar-senha'
