"""Migração 0003 do envio (008 T2.4): reversão tira a coluna e a CHECK; o papel app recebe o grant pela tabela."""

import pytest
from django.conf import settings
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db

APP = settings.DATABASES['app']['USER']


def _colunas(tabela):
    with connection.cursor() as consulta:
        consulta.execute('SELECT column_name FROM information_schema.columns WHERE table_name = %s', [tabela])
        return {linha[0] for linha in consulta.fetchall()}


def _existe_restricao(nome):
    with connection.cursor() as consulta:
        consulta.execute('SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = %s)', [nome])
        return consulta.fetchone()[0]


def test_reverter_a_0003_tira_a_coluna_de_hash_e_a_check():
    assert 'hash_original' in _colunas('catalogo_envio_camada')
    assert _existe_restricao('envio_camada_hash_valido')
    with transaction.atomic():
        MigrationExecutor(connection).migrate([('catalogo', '0002_metadados_versao')])
        assert 'hash_original' not in _colunas('catalogo_envio_camada')
        assert not _existe_restricao('envio_camada_hash_valido')
        transaction.set_rollback(True)
    assert 'hash_original' in _colunas('catalogo_envio_camada')


def test_coluna_de_hash_herda_o_grant_do_papel_app_pela_tabela():
    with connection.cursor() as consulta:
        consulta.execute('SELECT has_column_privilege(%s, %s, %s, %s)', [APP, 'catalogo_envio_camada', 'hash_original', 'INSERT'])
        assert consulta.fetchone()[0]
