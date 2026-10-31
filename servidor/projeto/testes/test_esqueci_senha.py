"""Esqueci a senha (R6; A3): resposta neutra, igual para CPF existente e inexistente."""

import re

from django.test import Client


def _pedir(cpf):
    return Client().post('/esqueci-senha', {'cpf': cpf})


def _sem_variaveis(html):
    return re.sub(r'name="csrfmiddlewaretoken" value="[^"]+"| nonce="[^"]+"', '', html)


def test_cpf_existente_e_inexistente_dao_a_mesma_pagina(conta, mailoutbox):
    existente = _pedir(conta.cpf)
    inexistente = _pedir('529.982.247-25')
    assert existente.status_code == inexistente.status_code == 200
    assert _sem_variaveis(existente.content.decode()) == _sem_variaveis(inexistente.content.decode())
    assert 'Se o CPF estiver cadastrado' in existente.content.decode()
    assert len(mailoutbox) == 1  # só o existente recebeu o link


def test_cpf_de_digito_invalido_tambem_e_neutro(db):
    resposta = _pedir('123.456.789-00')
    assert (resposta.status_code, 'Se o CPF estiver cadastrado' in resposta.content.decode()) == (200, True)


def test_consulta_mostra_o_formulario_sem_a_mensagem():
    html = Client().get('/esqueci-senha').content.decode()
    assert 'name="cpf"' in html
    assert 'Se o CPF estiver cadastrado' not in html


def test_sem_csrf_o_pedido_e_recusado(conta, mailoutbox):
    assert Client(enforce_csrf_checks=True).post('/esqueci-senha', {'cpf': conta.cpf}).status_code == 403
    assert mailoutbox == []


def test_a_resposta_sai_antes_do_pedido_ser_gravado(conta, monkeypatch):
    # PR #20: o trabalho que difere entre CPF existente e inexistente roda na fila, depois da resposta.
    from identidade import email
    from identidade.models import PedidoRedefinicao

    fila = []
    monkeypatch.setattr(email, '_despachar', fila.append)
    assert _pedir(conta.cpf).status_code == 200
    assert not PedidoRedefinicao.objects.exists()
    fila.pop()()
    assert PedidoRedefinicao.objects.count() == 1
