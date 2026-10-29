import pytest

from permissao.models import Cargo

pytestmark = pytest.mark.django_db

# Expectativas escritas à mão a partir de plan.md §Catálogo de ações e cargos-base (nunca lidas de `COMPOSICAO`).
USUARIO = {'ver', 'baixar_pacote_offline'}
TECNICO = USUARIO | {'baixar_documento', 'criar_registro_campo', 'propor_alteracao_atributo', 'revisar_trabalho_de_outro'}
CURADOR = TECNICO | {
    'validar_registro', 'validar_atributo', 'conferir_revisao_enviada', 'aprovar_atributo',
    'subir_documento', 'definir_validade_documento', 'convidar_pessoa', 'revogar_acesso',
}  # fmt: skip


def _acoes(cargo):
    return set(cargo.permissoes.values_list('pk', flat=True))


def test_os_quatro_cargos_base_nascem_com_a_empresa(cenario):
    assert set(cenario.cargos_x) == {'administrador', 'curador', 'tecnico', 'usuario'}
    assert {c.nome for c in Cargo.objects.filter(empresa=cenario.x)} == {'Administrador', 'Curador', 'Técnico', 'Usuário'}
    for base, cargo in cenario.cargos_x.items():
        assert cargo.base == base
        assert cargo.empresa == cenario.x


def test_composicao_de_cada_cargo_base_confere_com_o_plano(cenario):
    cargos = cenario.cargos_x
    assert _acoes(cargos['usuario']) == USUARIO
    assert _acoes(cargos['tecnico']) == TECNICO
    assert _acoes(cargos['curador']) == CURADOR
    assert len(CURADOR) == 14


def test_administrador_leva_todo_o_catalogo_menos_criar_empresa(cenario):
    acoes = _acoes(cenario.cargos_x['administrador'])
    assert len(acoes) == 26
    assert 'criar_empresa' not in acoes
    assert {'tornar_revisao_vigente', 'aprovar_geometria', 'gerenciar_cargo'} <= acoes


def test_cada_empresa_tem_cargos_proprios(cenario):
    assert {c.pk for c in cenario.cargos_x.values()}.isdisjoint({c.pk for c in cenario.cargos_y.values()})
    assert Cargo.objects.count() == 8
