"""Migração `permissao/0012`: marca `de_base` nos cargos existentes e carga da ação `exportar_dados` (012 T4.3, R34, Q20)."""

from importlib import import_module

import pytest
from django.apps import apps

from permissao.models import Cargo, CargoPermissao, Permissao
from territorio.models import Empresa

pytestmark = pytest.mark.django_db

migracao = import_module('permissao.migrations.0012_cargo_de_base')


def _tem(cargo):
    return CargoPermissao.objects.filter(cargo=cargo, permissao_id='exportar_dados').exists()


def _antes_da_migracao():
    # Simula o banco da versão anterior: nenhum cargo marcado. Cargos criados pelo cenário já nascem com a marca.
    Cargo.objects.update(de_base=False)


def test_marca_administrador_e_cargos_base_da_empresa(cenario):
    _antes_da_migracao()
    migracao.marcar_cargos_base(apps, None)
    marcados = Cargo.objects.filter(empresa=cenario.x, de_base=True)
    assert {c.base for c in marcados} == {'administrador', 'curador', 'tecnico', 'usuario'}
    assert marcados.count() == 4


def test_cargo_base_renomeado_continua_marcado(cenario):
    Cargo.objects.filter(pk=cenario.cargos_x['curador'].pk).update(nome='Curador renomeado')
    _antes_da_migracao()
    migracao.marcar_cargos_base(apps, None)
    assert Cargo.objects.get(pk=cenario.cargos_x['curador'].pk).de_base is True


def test_personalizado_curador_criado_depois_nao_recebe_a_marca(cenario):
    Cargo.objects.filter(pk=cenario.cargos_x['curador'].pk).update(nome='Curador renomeado')
    personalizado = Cargo.objects.create(empresa=cenario.x, nome='Curador', base='curador')
    _antes_da_migracao()
    migracao.marcar_cargos_base(apps, None)
    assert Cargo.objects.get(pk=personalizado.pk).de_base is False
    assert Cargo.objects.get(pk=cenario.cargos_x['curador'].pk).de_base is True


def test_empresa_sem_administrador_nao_recebe_marca_nem_carga(cenario):
    sem_admin = Empresa.objects.create(nome='Empresa sem administrador')
    solto = Cargo.objects.create(empresa=sem_admin, nome='Curador', base='curador', de_base=False)
    _antes_da_migracao()
    migracao.marcar_cargos_base(apps, None)
    migracao.carregar_exportar_dados(apps, None)
    assert Cargo.objects.get(pk=solto.pk).de_base is False
    assert not _tem(solto)


def test_marca_refeita_nao_falha_nem_muda_o_resultado(cenario):
    _antes_da_migracao()
    migracao.marcar_cargos_base(apps, None)
    migracao.marcar_cargos_base(apps, None)
    assert Cargo.objects.filter(empresa=cenario.x, de_base=True).count() == 4


def test_carga_liga_a_acao_so_aos_cargos_base_administrador_e_curador(cenario):
    CargoPermissao.objects.filter(permissao_id='exportar_dados').delete()
    migracao.carregar_exportar_dados(apps, None)
    migracao.carregar_exportar_dados(apps, None)  # refazer depois de desfazer não pode falhar (ignore_conflicts)
    assert Permissao.objects.get(codigo='exportar_dados').delegavel is False
    assert _tem(cenario.cargos_x['administrador'])
    assert _tem(cenario.cargos_x['curador'])
    assert not _tem(cenario.cargos_x['tecnico'])
    assert not _tem(cenario.cargos_x['usuario'])


def test_carga_nao_liga_a_acao_a_cargo_de_base_tecnico_ou_usuario_criado_depois(cenario):
    tecnico_extra = Cargo.objects.create(empresa=cenario.x, nome='Técnico extra', base='tecnico')
    CargoPermissao.objects.filter(permissao_id='exportar_dados').delete()
    migracao.carregar_exportar_dados(apps, None)
    assert not _tem(tecnico_extra)  # a carga filtra por base (administrador e curador de base), não por empresa ou nome


def test_carga_nao_liga_a_acao_a_cargo_personalizado_de_base_curador(cenario):
    # Spec 012 (Q20): base curador leva a ação só pelo cargo marcado como de base; personalizado de mesma base não.
    personalizado = Cargo.objects.create(empresa=cenario.x, nome='Curador de campo', base='curador')
    CargoPermissao.objects.filter(permissao_id='exportar_dados').delete()
    migracao.carregar_exportar_dados(apps, None)
    assert _tem(cenario.cargos_x['curador'])
    assert not _tem(personalizado)


def test_cargo_base_curador_renomeado_continua_recebendo_a_acao(cenario):
    Cargo.objects.filter(pk=cenario.cargos_x['curador'].pk).update(nome='Curador renomeado')
    CargoPermissao.objects.filter(permissao_id='exportar_dados').delete()
    migracao.carregar_exportar_dados(apps, None)
    assert _tem(cenario.cargos_x['curador'])
