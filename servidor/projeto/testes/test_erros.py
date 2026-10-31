"""Páginas de erro (R16, A20): texto em português, link de volta, sem traço de pilha nem dado interno."""

from django.test import Client, RequestFactory, override_settings
from django.urls import path
from django.views.defaults import bad_request, permission_denied


def _quebra(_requisicao):
    raise RuntimeError('detalhe-interno-secreto')


urlpatterns = [path('quebra', _quebra)]
handler500 = 'projeto.paginas.erro_500'


def _confere(html, titulo):
    assert '<html lang="pt-BR">' in html
    assert f'<h1>{titulo}</h1>' in html
    assert 'href="/"' in html
    assert 'Voltar ao início' in html
    assert 'Traceback' not in html
    assert 'detalhe-interno-secreto' not in html


def test_404(db):
    resposta = Client().get('/nao-existe')
    assert resposta.status_code == 404
    _confere(resposta.content.decode(), 'Página não encontrada')


def test_400():
    resposta = bad_request(RequestFactory().get('/'), Exception())
    assert resposta.status_code == 400
    _confere(resposta.content.decode(), 'Pedido inválido')


def test_403():
    resposta = permission_denied(RequestFactory().get('/'), Exception())
    assert resposta.status_code == 403
    _confere(resposta.content.decode(), 'Acesso negado')


def test_falha_de_csrf_mostra_a_pagina_propria_e_nao_a_do_django(db):
    resposta = Client(enforce_csrf_checks=True).post('/painel/login/', {})
    html = resposta.content.decode()
    assert resposta.status_code == 403
    _confere(html, 'Formulário vencido')
    assert 'CSRF verification failed' not in html


@override_settings(ROOT_URLCONF=__name__, DEBUG=False)
def test_500_nao_mostra_pilha_nem_dado_interno():
    resposta = Client(raise_request_exception=False).get('/quebra')
    assert resposta.status_code == 500
    _confere(resposta.content.decode(), 'Erro no servidor')
