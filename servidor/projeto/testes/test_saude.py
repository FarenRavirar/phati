"""Rota de saúde (006 R10): 200 com banco, 503 sem banco, aberta, sem cache e sem vazar nada."""

import pytest
from django.db import OperationalError
from django.test import Client


def test_saude_responde_200_com_o_banco_no_ar(db):
    resposta = Client().get('/saude')
    assert resposta.status_code == 200
    assert resposta.json() == {'estado': 'ok'}
    assert 'no-store' in resposta['Cache-Control']


def test_saude_responde_503_sem_vazar_detalhe_quando_o_banco_cai(monkeypatch):
    class BancoFora:
        def cursor(self):
            raise OperationalError('connection to server at "banco" failed: password authentication failed for user "app"')

    monkeypatch.setattr('projeto.saude.connection', BancoFora())
    resposta = Client().get('/saude')
    assert resposta.status_code == 503
    assert resposta.json() == {'estado': 'indisponivel'}
    assert b'password' not in resposta.content
    assert b'banco' not in resposta.content


def test_saude_responde_503_quando_o_banco_cai_na_consulta_e_nao_ao_abrir_o_cursor(monkeypatch):
    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def execute(self, _sql):
            raise OperationalError('server closed the connection unexpectedly')

    class BancoFora:
        def cursor(self):
            return Cursor()

    monkeypatch.setattr('projeto.saude.connection', BancoFora())
    resposta = Client().get('/saude')
    assert resposta.status_code == 503
    assert resposta.json() == {'estado': 'indisponivel'}


def test_saude_so_aceita_consulta():
    assert Client().post('/saude').status_code == 405


# Host fora de ALLOWED_HOSTS recebe 400 em toda rota (spec 011 R8): o CommonMiddleware é quem chama get_host().
@pytest.mark.parametrize('caminho', ['/saude', '/entrar'])
def test_host_fora_de_allowed_hosts_recebe_400(settings, caminho):
    settings.ALLOWED_HOSTS = ['phati.exemplo.test']
    assert Client(HTTP_HOST='estranho.exemplo.test').get(caminho).status_code == 400


@pytest.mark.parametrize('caminho', ['/saude', '/entrar'])
def test_host_permitido_recebe_200_nas_mesmas_rotas(db, settings, caminho):
    settings.ALLOWED_HOSTS = ['phati.exemplo.test']
    assert Client(HTTP_HOST='phati.exemplo.test').get(caminho).status_code == 200


def test_append_slash_desligado_mantem_404_sem_redirecionar(db, settings):
    settings.ALLOWED_HOSTS = ['phati.exemplo.test']
    assert settings.APPEND_SLASH is False
    assert Client(HTTP_HOST='phati.exemplo.test').get('/rota-que-nao-existe').status_code == 404
