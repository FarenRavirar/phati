"""Carga da ação `exportar_dados` dentro da migração `territorio/0008` (012 T4.3, R34): cargos-base existentes e refazer sem erro."""

from importlib import import_module
from unittest.mock import MagicMock

import pytest
from django.apps import apps
from django.contrib.postgres.operations import UnaccentExtension

from permissao.models import CargoPermissao, Permissao

pytestmark = pytest.mark.django_db

migracao = import_module('territorio.migrations.0008_fase_fazendas')


def _tem(cargo):
    return CargoPermissao.objects.filter(cargo=cargo, permissao_id='exportar_dados').exists()


def test_carga_liga_a_acao_so_aos_cargos_base_administrador_e_curador(cenario):
    CargoPermissao.objects.filter(permissao_id='exportar_dados').delete()
    migracao.carregar(apps, None)
    migracao.carregar(apps, None)  # refazer depois de desfazer não pode falhar (ignore_conflicts)
    assert Permissao.objects.get(codigo='exportar_dados').delegavel is False
    assert _tem(cenario.cargos_x['administrador']) and _tem(cenario.cargos_x['curador'])
    assert not _tem(cenario.cargos_x['tecnico']) and not _tem(cenario.cargos_x['usuario'])


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


def test_carga_nao_liga_a_acao_a_cargo_de_base_tecnico_ou_usuario_criado_depois(cenario):
    from permissao.models import Cargo

    tecnico_extra = Cargo.objects.create(empresa=cenario.x, nome='Técnico extra', base='tecnico')
    CargoPermissao.objects.filter(permissao_id='exportar_dados').delete()
    migracao.carregar(apps, None)
    assert not _tem(tecnico_extra)  # a carga filtra por base (administrador e curador), não por empresa ou nome


def test_carga_nao_liga_a_acao_a_cargo_personalizado_de_base_curador(cenario):
    # Spec 012 (Q20): base curador leva a ação só pelo cargo-base de nome 'Curador'; personalizado de mesma base não.
    from permissao.models import Cargo

    personalizado = Cargo.objects.create(empresa=cenario.x, nome='Curador de campo', base='curador')
    CargoPermissao.objects.filter(permissao_id='exportar_dados').delete()
    migracao.carregar(apps, None)
    assert _tem(cenario.cargos_x['curador'])
    assert not _tem(personalizado)
