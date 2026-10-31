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


@pytest.fixture
def convite_pendente(cenario, conta, fabrica_pessoa, conceder_direto):
    """Convite da `conta` para o cargo Usuário na fazenda F1 de X, feito por um Administrador de X."""
    from permissao import convite
    from permissao.models import Convite

    admin = fabrica_pessoa('Admin de X')
    conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    convite.convidar_por_cpf(admin, 'Fulana', 'fulana@exemplo.test', conta.cpf, cenario.cargos_x['usuario'], cenario.f1)
    return Convite.objects.get(pessoa=conta.pessoa)
