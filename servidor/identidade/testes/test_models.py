"""A1 (R1) no banco: unicidade do CPF, cifra gravada e privilégios do papel `app` nas tabelas desta app."""

import logging

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection

from identidade.models import Pessoa

CPF = '123.456.789-09'
CPF_LIMPO = '12345678909'

pytestmark = pytest.mark.django_db


def _criar(cpf=CPF, nome='Maria da Silva'):
    return Pessoa.objects.criar(nome=nome, email='maria@exemplo.test', cpf=cpf)


def test_cria_pessoa_com_cpf_so_em_busca_e_cifra():
    pessoa = _criar()
    assert CPF_LIMPO not in pessoa.cpf_busca
    assert CPF_LIMPO not in pessoa.cpf_cifrado
    assert not pessoa.has_usable_password()


def test_consulta_pelo_cpf_em_claro_nao_acha_nada():
    _criar()
    assert Pessoa.objects.filter(cpf_cifrado=CPF_LIMPO).count() == 0
    assert Pessoa.objects.filter(cpf_busca=CPF_LIMPO).count() == 0


@pytest.mark.parametrize('repetido', [CPF, CPF_LIMPO])
def test_segundo_cadastro_do_mesmo_cpf_e_recusado_com_ou_sem_pontuacao(repetido):
    _criar()
    with pytest.raises(ValidationError) as erro:
        _criar(cpf=repetido)
    assert erro.value.code == 'cpf_duplicado'
    assert Pessoa.objects.count() == 1


def test_cpf_invalido_nao_cria_pessoa():
    with pytest.raises(ValidationError):
        _criar(cpf='111.111.111-11')
    assert Pessoa.objects.count() == 0


def test_cpf_nao_aparece_em_log(caplog):
    caplog.set_level(logging.DEBUG)
    _criar()
    with pytest.raises(ValidationError):
        _criar()
    assert CPF_LIMPO not in caplog.text
    assert CPF not in caplog.text


def test_coluna_da_senha_e_em_portugues():
    colunas = [c.name for c in connection.introspection.get_table_description(connection.cursor(), 'pessoa')]
    assert 'senha' in colunas
    assert 'password' not in colunas


@pytest.mark.parametrize('tabela', ['pessoa', 'pedido_redefinicao', 'acesso_aplicativo', 'django_session'])
def test_papel_app_opera_as_tabelas_da_identidade(tabela):
    # Login roda como `app` em produção; tabela criada antes dos privilégios padrão ficaria inacessível.
    with connection.cursor() as consulta:
        consulta.execute(
            "SELECT bool_and(has_table_privilege(%s, %s, p)) FROM unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE']) p",
            [settings.DATABASES['app']['USER'], tabela],
        )
        assert consulta.fetchone() == (True,)


def test_erro_de_outra_restricao_nao_vira_cpf_duplicado(monkeypatch):
    # Achado do Sourcery (PR #9): só a unicidade do CPF vira `cpf_duplicado`. A FK de `empresa_origem` é
    # postergada até o commit, então o erro de outra restrição é simulado na gravação.
    def falha(*_, **__):
        raise IntegrityError('outra restrição')

    monkeypatch.setattr(Pessoa, 'save', falha)
    with pytest.raises(IntegrityError):
        Pessoa.objects.criar(nome='Ana', email='ana@exemplo.test', cpf='529.982.247-25')
