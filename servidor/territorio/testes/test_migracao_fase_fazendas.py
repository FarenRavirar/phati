"""Extensão `unaccent` da migração `territorio/0008` (012 T4.0): ida cria a extensão, volta não toca no banco."""

from importlib import import_module
from unittest.mock import MagicMock

import pytest
from django.contrib.postgres.operations import UnaccentExtension

migracao = import_module('territorio.migrations.0008_fase_fazendas')


def test_volta_da_extensao_unaccent_nao_toca_no_banco():
    # A extensão pertence ao banco (superusuário). O reverso não pode emitir DROP EXTENSION, nem com a extensão de pé.
    esquema = MagicMock()
    esquema.connection.vendor = 'postgresql'
    migracao.ExtensaoUnaccentSemVolta().database_backwards('territorio', esquema, None, None)
    esquema.execute.assert_not_called()


def test_ida_da_extensao_unaccent_continua_criando_unaccent():
    operacao = migracao.ExtensaoUnaccentSemVolta()
    assert isinstance(operacao, UnaccentExtension)
    assert operacao.name == 'unaccent'


@pytest.mark.django_db  # register_type_handlers da ida consulta o banco de teste
def test_ida_da_extensao_unaccent_executa_create_extension_quando_ainda_nao_existe():
    # Ida quebrada (ex.: database_forwards sobrescrito com pass) não emite o CREATE: este teste falha nesse caso.
    esquema = MagicMock()
    esquema.connection.vendor = 'postgresql'
    esquema.connection.alias = 'default'  # o register_type_handlers da ida lê o alias
    esquema.quote_name.side_effect = lambda nome: nome
    esquema.connection.cursor.return_value.__enter__.return_value.fetchone.return_value = None  # extensão ausente
    migracao.ExtensaoUnaccentSemVolta().database_forwards('territorio', esquema, None, None)
    esquema.execute.assert_called_once_with('CREATE EXTENSION IF NOT EXISTS unaccent')
