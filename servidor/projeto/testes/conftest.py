from types import SimpleNamespace

import pytest
from django.test import Client

SENHA = 'cavalo azul sobe o morro'  # com espaços: R3 aceita


@pytest.fixture
def conta(fabrica_pessoa, cpf_novo):
    """Pessoa com senha definitiva e o CPF em texto, para a tela de login."""
    from identidade.models import Pessoa

    cpf = cpf_novo()
    pessoa = Pessoa.objects.criar(nome='Fulana Sintetica', email='fulana@exemplo.test', cpf=cpf)
    pessoa.set_password(SENHA)
    pessoa.save()
    return SimpleNamespace(pessoa=pessoa, cpf=cpf, senha=SENHA)


@pytest.fixture
def cliente_logado(conta):
    cliente = Client()
    resposta = cliente.post('/entrar', {'cpf': conta.cpf, 'senha': conta.senha})
    assert resposta.status_code == 302
    return cliente
