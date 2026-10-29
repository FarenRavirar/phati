import pytest

from identidade.models import Pessoa

CPF = '123.456.789-09'
CPF_LIMPO = '12345678909'
SENHA = 'cavalo azul sobe o morro'  # com espaços: R3 aceita


@pytest.fixture
def pessoa(db):
    """Pessoa com senha definitiva (sem temporária), nome 'Maria da Silva'."""
    nova = Pessoa.objects.criar(nome='Maria da Silva', email='maria@exemplo.test', cpf=CPF)
    nova.set_password(SENHA)
    nova.save()
    return nova
