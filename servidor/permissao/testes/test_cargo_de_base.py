"""Marca `de_base` do cargo (012, Q20): criada pelo cargo-base, única por empresa e base, nunca marcada pelo cargo personalizado."""

import pytest
from django.db import IntegrityError, transaction

from permissao.cargo import gerenciar_cargo
from permissao.cargos_base import criar_cargos_base
from permissao.models import Cargo
from territorio.models import Empresa

pytestmark = pytest.mark.django_db


def test_criar_cargos_base_marca_os_quatro_cargos_base():
    empresa = Empresa.objects.create(nome='Empresa nova de base')
    criar_cargos_base(empresa)
    assert set(Cargo.objects.filter(empresa=empresa, de_base=True).values_list('base', flat=True)) == {'administrador', 'curador', 'tecnico', 'usuario'}
    assert Cargo.objects.filter(empresa=empresa, de_base=True).count() == 4


def test_segundo_administrador_marcado_na_mesma_empresa_e_recusado(cenario):
    with pytest.raises(IntegrityError), transaction.atomic():
        Cargo.objects.create(empresa=cenario.x, nome='Administrador dois', base='administrador', de_base=True)


def test_segundo_administrador_sem_marca_passa(cenario):
    Cargo.objects.create(empresa=cenario.x, nome='Administrador dois', base='administrador')
    assert Cargo.objects.filter(empresa=cenario.x, base='administrador').count() == 2


def test_marca_de_base_em_empresas_diferentes_passa(cenario):
    outra = Empresa.objects.create(nome='Outra empresa de base')
    Cargo.objects.create(empresa=outra, nome='Administrador de outra', base='administrador', de_base=True)
    assert Cargo.objects.filter(base='administrador', de_base=True).count() >= 2


def test_gerenciar_cargo_cria_personalizado_sem_marca(cenario, fabrica_pessoa, conceder_direto):
    # Feliz: o Administrador cria um cargo personalizado de base curador; a marca de base fica de fora.
    adm = fabrica_pessoa('Adm marca')
    conceder_direto(adm, cenario.cargos_x['administrador'], cenario.x)
    cargo = gerenciar_cargo(adm, cenario.x, 'Curador de campo', ['ver'], base='curador')
    assert Cargo.objects.get(pk=cargo.pk).de_base is False
