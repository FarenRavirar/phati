"""`gerenciar_cargo` (R8, R10, R16; T5.5b item 1): nível, escopo, permissões delegáveis e evento `cargo_alterado`."""

from importlib import import_module

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from comum.models import EventoAuditoria
from permissao.cargo import gerenciar_cargo
from permissao.models import Cargo, Permissao


@pytest.fixture(autouse=True)
def catalogo(db):
    for codigo, descricao, delegavel in import_module('permissao.migrations.0001_initial').ACOES:
        Permissao.objects.get_or_create(codigo=codigo, defaults={'descricao': descricao, 'delegavel': delegavel})


def _com(fabrica_pessoa, conceder_direto, cargo, escopo, nome='Pessoa'):
    pessoa = fabrica_pessoa(nome)
    conceder_direto(pessoa, cargo, escopo)
    return pessoa


def _codigos(cargo):
    return set(cargo.permissoes.values_list('pk', flat=True))


def test_administrador_cria_cargo_e_o_evento_guarda_o_conjunto(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    cargo = gerenciar_cargo(admin, cenario.x, 'Campo', ['ver', 'criar_registro_campo'], base='tecnico')
    assert (cargo.empresa_id, cargo.base, _codigos(cargo)) == (cenario.x.pk, 'tecnico', {'ver', 'criar_registro_campo'})
    evento = EventoAuditoria.objects.get(acao='cargo_alterado')
    assert (evento.pessoa_id, evento.alvo_id, evento.empresa_id) == (admin.pk, cargo.pk, cenario.x.pk)
    assert evento.detalhes['permissoes'] == ['criar_registro_campo', 'ver']


def test_altera_nome_e_troca_o_conjunto_inteiro(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    cargo = gerenciar_cargo(admin, cenario.x, 'Campo', ['ver', 'baixar_documento'], base='usuario')
    gerenciar_cargo(admin, cenario.x, 'Campo 2', ['ver'], cargo=cargo)
    cargo.refresh_from_db()
    assert (cargo.nome, cargo.base, _codigos(cargo)) == ('Campo 2', 'usuario', {'ver'})
    assert EventoAuditoria.objects.filter(acao='cargo_alterado').count() == 2


@pytest.mark.parametrize('base', ['curador', 'tecnico', 'usuario'])
def test_cargo_sem_gerenciar_cargo_ou_so_com_fazenda_e_negado(cenario, fabrica_pessoa, conceder_direto, base):
    pessoa = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x[base], cenario.x)
    with pytest.raises(PermissionDenied):
        gerenciar_cargo(pessoa, cenario.x, 'Intruso', ['ver'], base='usuario')
    assert not Cargo.objects.filter(nome='Intruso').exists()
    assert not EventoAuditoria.objects.filter(acao='cargo_alterado').exists()


def test_administrador_de_x_nao_gerencia_cargo_da_empresa_y(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    with pytest.raises(PermissionDenied):
        gerenciar_cargo(admin, cenario.y, 'Invasor', ['ver'], base='usuario')
    with pytest.raises(PermissionDenied):
        gerenciar_cargo(admin, cenario.x, 'Roubo', ['ver'], cargo=cenario.cargos_y['usuario'])
    assert not Cargo.objects.filter(nome__in=['Invasor', 'Roubo']).exists()


def test_cargo_personalizado_gerencia_so_abaixo_e_so_o_que_tem(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    gestor = gerenciar_cargo(admin, cenario.x, 'Gestor', ['ver', 'gerenciar_cargo', 'baixar_documento'], base='curador')
    pessoa = _com(fabrica_pessoa, conceder_direto, gestor, cenario.x, 'Gestora')
    gerenciar_cargo(pessoa, cenario.x, 'Leitor', ['ver'], base='usuario')
    for base, codigos in (('curador', ['ver']), ('administrador', ['ver']), ('usuario', ['ver', 'revogar_acesso'])):
        with pytest.raises(PermissionDenied):
            gerenciar_cargo(pessoa, cenario.x, 'Alto', codigos, base=base)
    assert not Cargo.objects.filter(nome='Alto').exists()


def test_acao_nao_delegavel_so_o_administrador_concede(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    gestor = gerenciar_cargo(admin, cenario.x, 'Gestor', ['ver', 'gerenciar_cargo', 'aprovar_geometria'], base='curador')
    pessoa = _com(fabrica_pessoa, conceder_direto, gestor, cenario.x, 'Gestora')
    with pytest.raises(PermissionDenied):
        gerenciar_cargo(pessoa, cenario.x, 'Cartografia', ['aprovar_geometria'], base='tecnico')
    assert gerenciar_cargo(admin, cenario.x, 'Cartografia', ['aprovar_geometria'], base='tecnico').pk


@pytest.mark.parametrize(
    ('codigos', 'nome', 'base', 'codigo'),
    [
        (['criar_empresa'], 'A', 'usuario', 'permissao_invalida'),
        (['inexistente'], 'A', 'usuario', 'permissao_invalida'),
        (['ver'], '  ', 'usuario', 'nome_invalido'),
        (['ver'], 'A', 'rei', 'base_invalida'),
    ],
)
def test_entrada_invalida_nao_grava_nada(cenario, plataforma, codigos, nome, base, codigo):
    with pytest.raises(ValidationError) as erro:
        gerenciar_cargo(plataforma, cenario.x, nome, codigos, base=base)
    assert erro.value.code == codigo
    assert not EventoAuditoria.objects.filter(acao='cargo_alterado').exists()


def test_pessoa_anonima_nao_gerencia(cenario):
    from django.contrib.auth.models import AnonymousUser

    with pytest.raises(PermissionDenied):
        gerenciar_cargo(AnonymousUser(), cenario.x, 'A', ['ver'], base='usuario')
