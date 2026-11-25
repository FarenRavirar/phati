"""Reversão da migração do catálogo (008, revisão PR #66; consolidada na `0001_initial`). Reverter tira as políticas e os
grants do papel `app`, as chaves compostas, a leitura do tema e, por fim, as tabelas (com as colunas de metadado, as CHECKs e
o índice parcial da divisão). Cada reversão roda numa transação que é desfeita no fim, então o banco de teste volta ao
estado migrado."""

import importlib

import pytest
from django.conf import settings
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db

APP = settings.DATABASES['app']['USER']


def _app_tabela(tabela, privilegio):
    with connection.cursor() as consulta:
        consulta.execute('SELECT has_table_privilege(%s, %s, %s)', [APP, tabela, privilegio])
        return consulta.fetchone()[0]


def _app_sequencia(sequencia):
    with connection.cursor() as consulta:
        consulta.execute("SELECT has_sequence_privilege(%s, %s, 'USAGE')", [APP, sequencia])
        return consulta.fetchone()[0]


def _rls_ligado(tabela):
    with connection.cursor() as consulta:
        consulta.execute('SELECT relrowsecurity FROM pg_class WHERE relname = %s', [tabela])
        return consulta.fetchone()[0]


def _existe_restricao(nome):
    with connection.cursor() as consulta:
        consulta.execute('SELECT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = %s)', [nome])
        return consulta.fetchone()[0]


def _existe_politica(tabela, nome):
    with connection.cursor() as consulta:
        consulta.execute('SELECT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = %s AND policyname = %s)',
                         [tabela, nome])
        return consulta.fetchone()[0]


def _existe_tabela(tabela):
    with connection.cursor() as consulta:
        consulta.execute('SELECT to_regclass(%s) IS NOT NULL', [tabela])
        return consulta.fetchone()[0]


def _colunas(tabela):
    with connection.cursor() as consulta:
        consulta.execute('SELECT column_name FROM information_schema.columns WHERE table_name = %s', [tabela])
        return {linha[0] for linha in consulta.fetchall()}


def _app_coluna(tabela, coluna, privilegio):
    with connection.cursor() as consulta:
        consulta.execute('SELECT has_column_privilege(%s, %s, %s, %s)', [APP, tabela, coluna, privilegio])
        return consulta.fetchone()[0]


def _existe_indice(nome):
    with connection.cursor() as consulta:
        consulta.execute('SELECT EXISTS (SELECT 1 FROM pg_class WHERE relname = %s)', [nome])  # índice parcial não está em pg_constraint
        return consulta.fetchone()[0]


def test_reverter_as_politicas_tira_os_grants_do_papel_app_e_a_rls():
    migracao = importlib.import_module('catalogo.migrations.0001_initial')
    # Antes: o grant e a RLS existem (medido, não presumido).
    assert _app_tabela('catalogo_estudo', 'SELECT')
    assert _app_sequencia('catalogo_estudo_id_seq')
    assert _rls_ligado('catalogo_estudo')
    with transaction.atomic():
        with connection.schema_editor(atomic=False) as editor:
            migracao._desfazer_politicas(None, editor)
        assert not _app_tabela('catalogo_estudo', 'SELECT')
        assert not _app_tabela('catalogo_tema', 'INSERT')
        assert not _app_sequencia('catalogo_estudo_id_seq')
        assert not _rls_ligado('catalogo_estudo')
        transaction.set_rollback(True)
    assert _app_tabela('catalogo_estudo', 'SELECT')  # a transação desfeita devolve o grant


def test_reverter_as_chaves_tira_as_fks_compostas_do_estudo_e_a_leitura_do_tema():
    migracao = importlib.import_module('catalogo.migrations.0001_initial')
    assert _existe_restricao('estudo_tema_da_empresa')
    assert _existe_restricao('estudo_fazenda_da_empresa')
    assert _existe_politica('catalogo_tema', 'leitura_por_fazenda')
    with transaction.atomic():
        with connection.schema_editor(atomic=False) as editor:
            migracao._desfazer_politicas(None, editor)
            migracao._remover_chaves_compostas(None, editor)
        assert not _existe_restricao('estudo_tema_da_empresa')
        assert not _existe_restricao('estudo_fazenda_da_empresa')
        assert not _existe_politica('catalogo_tema', 'leitura_por_fazenda')
        transaction.set_rollback(True)
    assert _existe_restricao('estudo_tema_da_empresa')


def test_reverter_a_0001_tira_as_colunas_de_metadado_as_checks_e_o_indice_da_divisao():
    # Antes: colunas de metadado, CHECKs de origem e de hash, coluna da divisão e índice parcial existem (medido).
    assert 'origem' in _colunas('catalogo_versao_camada')
    assert 'data_publicacao' in _colunas('catalogo_versao_camada')
    assert _existe_restricao('versao_camada_origem_nao_vazia')
    assert _existe_restricao('envio_camada_hash_valido')
    assert 'coluna_no' in _colunas('catalogo_camada')
    assert _existe_indice('camada_divisao_unica_por_fazenda')
    assert _app_coluna('catalogo_camada', 'coluna_no', 'UPDATE')  # herda o grant da tabela (0001), sem grant próprio
    with transaction.atomic():
        MigrationExecutor(connection).migrate([('catalogo', None)])
        assert not _existe_tabela('catalogo_versao_camada')  # a tabela cai com as colunas, as CHECKs e o índice
        assert not _existe_restricao('versao_camada_origem_nao_vazia')
        assert not _existe_restricao('envio_camada_hash_valido')
        assert not _existe_indice('camada_divisao_unica_por_fazenda')
        assert not _existe_tabela('catalogo_camada')
        transaction.set_rollback(True)
    # A transação desfeita devolve tudo.
    assert 'origem' in _colunas('catalogo_versao_camada')
    assert _existe_restricao('envio_camada_hash_valido')
    assert _existe_indice('camada_divisao_unica_por_fazenda')


def test_colunas_de_metadado_herdam_o_grant_do_papel_app_pela_tabela():
    # O grant é por tabela (0001): coluna nova não precisa de grant próprio. Medido com has_column_privilege.
    assert _app_coluna('catalogo_versao_camada', 'origem', 'INSERT')
    assert _app_coluna('catalogo_versao_camada', 'data_publicacao', 'UPDATE')
