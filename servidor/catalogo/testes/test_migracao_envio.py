"""Colunas do envio na `0001_initial` (008 T2.4, T3.2; R11, R15): o hash do original e o identificador público saem com a
reversão, e a CHECK do hash cai junto. O papel app recebe o grant pela tabela."""

import pytest
from django.conf import settings
from django.db import IntegrityError, connection, transaction
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


def test_reverter_a_0001_tira_a_coluna_de_hash_o_publico_id_e_a_check():
    assert 'hash_original' in _colunas('catalogo_envio_camada')
    assert 'publico_id' in _colunas('catalogo_envio_camada')
    assert _existe_restricao('envio_camada_hash_valido')
    with transaction.atomic():
        MigrationExecutor(connection).migrate([('catalogo', None)])
        assert 'hash_original' not in _colunas('catalogo_envio_camada')
        assert 'publico_id' not in _colunas('catalogo_envio_camada')
        assert not _existe_restricao('envio_camada_hash_valido')
        transaction.set_rollback(True)
    assert 'hash_original' in _colunas('catalogo_envio_camada')  # a transação desfeita devolve a coluna e a CHECK


def test_coluna_de_hash_herda_o_grant_do_papel_app_pela_tabela():
    with connection.cursor() as consulta:
        consulta.execute('SELECT has_column_privilege(%s, %s, %s, %s)', [APP, 'catalogo_envio_camada', 'hash_original', 'INSERT'])
        assert consulta.fetchone()[0]


def test_check_recusa_hash_que_nao_e_sha256_em_hex_minusculo(cenario, fabrica_pessoa):
    # Caso negativo da CHECK consolidada (0001): maiúscula, tamanho errado e não hexadecimal são recusados; o válido passa.
    from catalogo.models import EnvioCamada

    pessoa = fabrica_pessoa()
    criar = lambda h: EnvioCamada.objects.create(  # noqa: E731
        criado_por=pessoa, empresa=cenario.x, fazenda=cenario.f1, arquivo_temporario='x.gpkg',
        hash_original=h, expira_em='2099-01-01T00:00:00Z',
    )
    for hash_ruim in ('A' * 64, 'a' * 63, 'g' * 64):
        with pytest.raises(IntegrityError), transaction.atomic():
            criar(hash_ruim)
    assert criar('a' * 64).publico_id is not None
