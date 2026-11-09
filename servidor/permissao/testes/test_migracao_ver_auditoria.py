"""Migração `permissao/0011` (005 R1, A6): `ver_auditoria` entra no catálogo, não delegável, e vai aos cargos
`administrador` que já existiam, e a reversão a retira sem tocar nos outros cargos."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

pytestmark = pytest.mark.django_db(transaction=True)

ANTES = ('permissao', '0010_acao_monitor_google')
DEPOIS = ('permissao', '0011_ver_auditoria')


def _migrar_para(alvo):
    executor = MigrationExecutor(connection)
    executor.migrate([alvo])
    return executor.loader.project_state([alvo]).apps


def _acoes_do_cargo(apps, cargo):
    return set(apps.get_model('permissao', 'CargoPermissao').objects.filter(cargo_id=cargo.pk).values_list('permissao_id', flat=True))


def test_cargo_administrador_que_ja_existia_ganha_a_acao_e_os_outros_nao():
    try:
        antigos = _migrar_para(ANTES)
        empresa = antigos.get_model('territorio', 'Empresa').objects.create(nome='Empresa Migracao')
        cargo = antigos.get_model('permissao', 'Cargo').objects
        administrador = cargo.create(empresa=empresa, nome='Administrador', base='administrador')
        curador = cargo.create(empresa=empresa, nome='Curador', base='curador')
        personalizado = cargo.create(empresa=empresa, nome='Personalizado', base='tecnico')
        assert not antigos.get_model('permissao', 'Permissao').objects.filter(codigo='ver_auditoria').exists()

        novos = _migrar_para(DEPOIS)
        permissao = novos.get_model('permissao', 'Permissao').objects.get(codigo='ver_auditoria')
        assert permissao.delegavel is False
        assert 'ver_auditoria' in _acoes_do_cargo(novos, administrador)
        assert 'ver_auditoria' not in _acoes_do_cargo(novos, curador)
        assert 'ver_auditoria' not in _acoes_do_cargo(novos, personalizado)

        revertidos = _migrar_para(ANTES)
        assert not revertidos.get_model('permissao', 'Permissao').objects.filter(codigo='ver_auditoria').exists()
        assert not revertidos.get_model('permissao', 'CargoPermissao').objects.filter(permissao_id='ver_auditoria').exists()
        assert revertidos.get_model('permissao', 'Cargo').objects.count() == 3  # nada além da ação é apagado
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())


def test_cargo_base_criado_depois_da_migracao_tambem_a_recebe(catalogo_da_corrida, cenario):
    from permissao.models import CargoPermissao

    codigos = set(CargoPermissao.objects.filter(cargo=cenario.cargos_x['administrador']).values_list('permissao_id', flat=True))
    assert 'ver_auditoria' in codigos
    for base in ('curador', 'tecnico', 'usuario'):
        assert not CargoPermissao.objects.filter(cargo=cenario.cargos_x[base], permissao_id='ver_auditoria').exists()
