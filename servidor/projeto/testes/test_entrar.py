"""Tela de login (R4, R8; A1, A5): mesma função da API, mensagem única, destino seguro, cookie."""

import pytest
from django.conf import settings
from django.test import Client

from identidade import login, senha
from projeto.testes.conftest import SENHA

FALHA = 'CPF ou senha incorretos.'


def _entrar(cliente, cpf, senha=SENHA, **extras):
    return cliente.post('/entrar', {'cpf': cpf, 'senha': senha, **extras})


def test_entrar_abre_a_sessao_e_leva_ao_destino(conta):
    resposta = _entrar(Client(), conta.cpf)
    assert (resposta.status_code, resposta['Location']) == (302, '/')


@pytest.mark.parametrize('formatar', [lambda c: c, lambda c: f'{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}'])
def test_cpf_com_e_sem_pontuacao_entra(conta, formatar):
    assert _entrar(Client(), formatar(conta.cpf)).status_code == 302


def test_cookie_de_sessao_sai_com_httponly_secure_e_samesite_lax(conta):
    cookie = _entrar(Client(), conta.cpf).cookies['sessionid']
    assert (cookie['httponly'], cookie['secure'], cookie['samesite']) == (True, True, 'Lax')


def test_tres_falhas_dao_a_mesma_resposta_byte_a_byte(conta):
    cliente = Client()
    inexistente = _entrar(cliente, '529.982.247-25')
    errada = _entrar(cliente, conta.cpf, 'senha errada qualquer')
    digito_invalido = _entrar(cliente, '123.456.789-00')
    assert FALHA in inexistente.content.decode()
    # Token CSRF, nonce e o CPF devolvido no campo mudam a cada resposta: compara o resto do corpo.
    corpos = {_sem_variaveis(r.content.decode()) for r in (inexistente, errada, digito_invalido)}
    assert len(corpos) == 1
    assert {r.status_code for r in (inexistente, errada, digito_invalido)} == {200}


def test_conta_bloqueada_da_a_mesma_mensagem(conta):
    for _ in range(settings.AUTENTICACAO_FALHAS_LIMITE):
        _entrar(Client(), conta.cpf, 'senha errada qualquer')
    resposta = _entrar(Client(), conta.cpf)
    assert FALHA in resposta.content.decode()


def test_proximo_interno_vale_e_externo_cai_em_barra(conta):
    assert _entrar(Client(), conta.cpf, proximo='/empresa/1/fazenda/2/')['Location'] == '/empresa/1/fazenda/2/'
    assert _entrar(Client(), conta.cpf, proximo='https://externo.exemplo/')['Location'] == '/'


def test_senha_temporaria_leva_a_troca(conta):
    temporaria = senha.emitir_senha_temporaria(conta.pessoa)
    assert _entrar(Client(), conta.cpf, temporaria)['Location'] == '/trocar-senha'
    # Qodo e Sourcery, PR #20: a página pedida atravessa a troca obrigatória.
    temporaria = senha.emitir_senha_temporaria(conta.pessoa)  # a anterior vale uma vez
    com_proximo = _entrar(Client(), conta.cpf, temporaria, proximo='/empresa/1/fazenda/2/')
    assert com_proximo['Location'] == '/trocar-senha?proximo=%2Fempresa%2F1%2Ffazenda%2F2%2F'


def test_avisos_de_sessao_expirada_e_de_senha_trocada():
    assert 'Sua sessão expirou.' in Client().get('/entrar?expirou=1').content.decode()
    assert 'Senha alterada.' in Client().get('/entrar?trocada=1').content.decode()
    assert 'Sua sessão expirou.' not in Client().get('/entrar').content.decode()


def test_sem_csrf_a_entrada_e_recusada(conta):
    resposta = Client(enforce_csrf_checks=True).post('/entrar', {'cpf': conta.cpf, 'senha': conta.senha})
    assert resposta.status_code == 403


def test_a_tela_chama_a_mesma_funcao_da_api(conta, monkeypatch):
    chamadas = []
    original = login.autenticar
    monkeypatch.setattr(login, 'autenticar', lambda *a, **k: chamadas.append(a) or original(*a, **k))
    _entrar(Client(), conta.cpf)
    assert len(chamadas) == 1


def _sem_variaveis(html):
    import re

    return re.sub(r' (?:value|nonce)="[^"]*"', '', html)
