"""Sair (R7; A4): só POST, com CSRF, encerra a sessão e volta ao login."""

from django.test import Client


def test_consulta_nao_encerra_a_sessao(cliente_logado):
    assert cliente_logado.get('/sair').status_code == 405
    assert '_auth_user_id' in cliente_logado.session


def test_post_sem_csrf_e_recusado(conta):
    cliente = Client(enforce_csrf_checks=True)
    cliente.post('/entrar', {'cpf': conta.cpf, 'senha': conta.senha})  # recusado por falta de token, sem sessão
    assert cliente.post('/sair').status_code == 403


def test_post_com_csrf_encerra_e_volta_a_entrada(conta):
    cliente = Client(enforce_csrf_checks=True)
    chave_csrf = _chave_csrf(cliente)
    cliente.post('/entrar', {'cpf': conta.cpf, 'senha': conta.senha, 'csrfmiddlewaretoken': chave_csrf})
    assert '_auth_user_id' in cliente.session
    resposta = cliente.post('/sair', {'csrfmiddlewaretoken': _chave_csrf(cliente)})
    assert (resposta.status_code, resposta['Location']) == (302, '/entrar')
    assert '_auth_user_id' not in cliente.session


def _chave_csrf(cliente):
    import re

    html = cliente.get('/entrar').content.decode()
    achado = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
    assert achado is not None
    return achado.group(1)
