"""Verificação do segredo de RLS (achado do Qodo, PR #15): segredo diferente do gravado nega tudo sem aviso."""

import pytest
from django.conf import settings
from django.db import connection, transaction

from permissao.checks import conferir_segredo_rls

pytestmark = pytest.mark.django_db(transaction=True)


def test_segredo_igual_ao_do_banco_nao_acusa_nada():
    assert conferir_segredo_rls(None, databases=['default']) == []


def test_segredo_diferente_do_do_banco_acusa_erro(monkeypatch):
    monkeypatch.setattr(settings, 'SEGREDO_RLS', b'x' * 32)
    erros = conferir_segredo_rls(None, databases=['default'])
    assert [erro.id for erro in erros] == ['permissao.E001']


def test_banco_sem_a_migracao_nao_acusa_erro():
    # `migrate` roda as verificações de banco antes de aplicar a 0004.
    with transaction.atomic():
        with connection.cursor() as consulta:
            consulta.execute('DROP FUNCTION app_segredo_impressao()')
        assert conferir_segredo_rls(None, databases=['default']) == []
        transaction.set_rollback(True)


def test_so_confere_os_bancos_pedidos():
    assert conferir_segredo_rls(None, databases=None) == []
