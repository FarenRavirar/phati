"""Política de conteúdo (R14, A12): nonce em script, sem `unsafe-inline`, em toda página HTML."""

import re

from django.test import Client, override_settings
from django.urls import path


def _quebra(_requisicao):
    raise RuntimeError('falha de teste')


urlpatterns = [path('quebra', _quebra)]
handler500 = 'projeto.paginas.erro_500'


def _politica(resposta):
    return resposta['Content-Security-Policy']


def _diretiva(politica, nome):
    return next(p for p in politica.split('; ') if p.startswith(nome + ' '))


def _confere(resposta):
    politica = _politica(resposta)
    assert re.search(r"script-src 'self' 'nonce-[\w-]+'", politica), politica
    assert "object-src 'none'" in politica and "frame-ancestors 'none'" in politica
    assert 'unsafe-inline' not in politica and 'unsafe-eval' not in politica
    return re.findall(r"'nonce-([\w-]+)'", _diretiva(politica, 'script-src'))[0]


def test_pagina_de_redefinicao_leva_nonce_no_cabecalho_e_no_script():
    resposta = Client().get('/redefinir-senha')
    nonce = _confere(resposta)
    assert f'<script nonce="{nonce}">' in resposta.content.decode()


def test_o_nonce_muda_a_cada_resposta():
    primeiro, segundo = (_confere(Client().get('/redefinir-senha')) for _ in range(2))
    assert primeiro != segundo


def test_pagina_404_leva_nonce(db):
    resposta = Client().get('/nao-existe')
    assert resposta.status_code == 404
    _confere(resposta)


def test_falha_de_csrf_leva_nonce(db):
    resposta = Client(enforce_csrf_checks=True).post('/painel/login/', {})
    assert resposta.status_code == 403
    _confere(resposta)


@override_settings(ROOT_URLCONF=__name__)
def test_pagina_500_leva_nonce():
    resposta = Client(raise_request_exception=False).get('/quebra')
    assert resposta.status_code == 500
    _confere(resposta)


def test_painel_do_django_continua_com_politica_e_sem_unsafe_inline(entrar_no_painel, plataforma):
    resposta = entrar_no_painel(plataforma).get('/painel/')
    assert resposta.status_code == 200
    _confere(resposta)
