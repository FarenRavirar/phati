"""Troca de senha (R5; A2): obrigatória e voluntária, regras vindas da exceção, sessão antiga invalida."""

import re

import pytest
from django.test import Client

from identidade import senha
from projeto.testes.conftest import SENHA


def _trocar(cliente, nova, atual=SENHA, repeticao=None):
    return cliente.post('/trocar-senha', {'senha_atual': atual, 'senha_nova': nova, 'repeticao': nova if repeticao is None else repeticao})


def test_sem_sessao_vai_a_entrada():
    assert Client().get('/trocar-senha')['Location'].startswith('/entrar?')


def test_senha_temporaria_pedindo_outra_pagina_cai_na_troca(conta):
    temporaria = senha.emitir_senha_temporaria(conta.pessoa)
    cliente = Client()
    cliente.post('/entrar', {'cpf': conta.cpf, 'senha': temporaria})
    assert cliente.get('/trocar-senha').status_code == 200
    assert 'Sua senha é temporária' in cliente.get('/trocar-senha').content.decode()


@pytest.mark.parametrize(('tamanho', 'aceita'), [(14, False), (15, True), (128, True), (129, False)])
def test_limites_da_senha_vem_da_validacao(cliente_logado, tamanho, aceita):
    nova = ('xk7' * 50)[:tamanho]
    resposta = _trocar(cliente_logado, nova)
    assert (resposta.status_code == 302) is aceita
    if not aceita:
        assert 'Senha curta demais.' in resposta.content.decode() or 'Senha longa demais.' in resposta.content.decode()


def test_senha_atual_errada_e_recusada(cliente_logado):
    resposta = _trocar(cliente_logado, 'uma frase longa e incomum', atual='errada')
    assert 'Senha atual incorreta.' in resposta.content.decode()


def test_repeticao_diferente_nao_troca(cliente_logado, conta):
    resposta = _trocar(cliente_logado, 'uma frase longa e incomum', repeticao='outra')
    assert 'As senhas não são iguais.' in resposta.content.decode()
    conta.pessoa.refresh_from_db()
    assert conta.pessoa.check_password(SENHA)


def test_troca_encerra_a_sessao_e_a_antiga_nao_vale(conta, cliente_logado):
    antigo = Client()
    antigo.cookies = cliente_logado.cookies.copy()
    resposta = _trocar(cliente_logado, 'uma frase longa e incomum')
    assert resposta['Location'] == '/entrar?trocada=1'
    assert antigo.get('/trocar-senha')['Location'].startswith('/entrar?')
    conta.pessoa.refresh_from_db()
    assert conta.pessoa.check_password('uma frase longa e incomum')


def test_a_tela_nao_repete_a_regra_de_senha():
    # As recusas vêm de `senha.validar_senha`; nenhum número da regra mora em `projeto/`.
    from pathlib import Path

    codigo = (Path(__file__).parent.parent / 'paginas_acesso.py').read_text(encoding='utf-8')
    for limite in (senha.COMPRIMENTO_MINIMO, senha.COMPRIMENTO_MAXIMO):
        assert not re.search(rf'\b{limite}\b', codigo)


def test_sem_csrf_a_troca_e_recusada(conta):
    cliente = Client(enforce_csrf_checks=True)
    assert cliente.post('/trocar-senha', {'senha_atual': conta.senha}).status_code == 403
