"""Comando `criar_administrador_plataforma` (R20; T5.4)."""

import logging

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from identidade import login
from identidade.models import Pessoa


def _criar(cpf, saida, **extra):
    call_command('criar_administrador_plataforma', nome='Ana', email='ana@exemplo.test', cpf=cpf, stdout=saida, **extra)


def test_cria_administrador_sem_empresa_com_senha_temporaria_que_entra(db, cpf_novo):
    from io import StringIO

    cpf, saida = cpf_novo(), StringIO()
    _criar(cpf, saida)
    pessoa = Pessoa.objects.get()
    assert (pessoa.administrador_plataforma, pessoa.empresa_origem_id, pessoa.deve_trocar_senha) == (True, None, True)
    temporaria = saida.getvalue().rsplit(': ', 1)[1].strip()
    assert login.autenticar(cpf, temporaria) is not None


def test_senha_nao_vai_para_o_log_nem_para_a_auditoria(db, cpf_novo, caplog):
    from io import StringIO

    from comum.models import EventoAuditoria

    saida = StringIO()
    with caplog.at_level(logging.DEBUG):
        _criar(cpf_novo(), saida)
    temporaria = saida.getvalue().rsplit(': ', 1)[1].strip()
    assert temporaria not in caplog.text
    assert temporaria not in str(list(EventoAuditoria.objects.values_list('detalhes', flat=True)))


def test_cpf_repetido_falha_sem_criar_segunda_pessoa(db, cpf_novo):
    from io import StringIO

    cpf, saida = cpf_novo(), StringIO()
    _criar(cpf, StringIO())
    with pytest.raises(CommandError):
        _criar(cpf, saida)
    assert Pessoa.objects.count() == 1


def test_cpf_invalido_falha_sem_criar_pessoa(db):
    from io import StringIO

    saida = StringIO()
    with pytest.raises(CommandError):
        _criar('111.111.111-11', saida)
    assert Pessoa.objects.count() == 0
