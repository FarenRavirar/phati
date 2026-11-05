"""Rota de saúde (006 R10): 200 com banco, 503 sem banco, aberta, sem cache e sem vazar nada."""

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


def test_saude_so_aceita_consulta():
    assert Client().post('/saude').status_code == 405
