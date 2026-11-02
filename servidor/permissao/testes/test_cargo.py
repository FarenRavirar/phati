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
    gerenciar_cargo(admin, cenario.x, 'Campo 2', ['ver'], cargo=cargo, versao=cargo.versao)
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
        gerenciar_cargo(admin, cenario.x, 'Roubo', ['ver'], cargo=cenario.cargos_y['usuario'], versao=1)
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

    anonima = AnonymousUser()
    with pytest.raises(PermissionDenied):
        gerenciar_cargo(anonima, cenario.x, 'A', ['ver'], base='usuario')


def test_renomear_para_nome_de_outro_cargo_da_empresa_e_recusado_sem_erro_de_banco(cenario, plataforma):
    leitor = gerenciar_cargo(plataforma, cenario.x, 'Leitor', ['ver'], base='usuario')
    with pytest.raises(ValidationError) as erro:
        gerenciar_cargo(plataforma, cenario.x, 'Usuário', ['ver'], cargo=leitor, versao=leitor.versao)
    assert erro.value.code == 'nome_duplicado'
    leitor.refresh_from_db()
    assert leitor.nome == 'Leitor'


def test_criar_cargo_com_nome_repetido_e_recusado(cenario, plataforma):
    with pytest.raises(ValidationError) as erro:
        gerenciar_cargo(plataforma, cenario.x, 'Usuário', ['ver'], base='usuario')
    assert erro.value.code == 'nome_duplicado'


def test_corrida_de_nome_repetido_vira_erro_de_regra_ao_renomear(cenario, plataforma, monkeypatch):
    leitor = gerenciar_cargo(plataforma, cenario.x, 'Leitor', ['ver'], base='usuario')
    # A pré-checagem não enxerga a corrida (outro pedido gravou o nome depois dela): aqui ela passa em branco.
    monkeypatch.setattr(Cargo.objects, 'filter', lambda *args, **kwargs: Cargo.objects.none())
    with pytest.raises(ValidationError) as erro:
        gerenciar_cargo(plataforma, cenario.x, 'Usuário', ['ver'], cargo=leitor, versao=leitor.versao)
    assert erro.value.code == 'nome_duplicado'


def test_corrida_de_nome_repetido_vira_erro_de_regra_ao_criar(cenario, plataforma, monkeypatch):
    monkeypatch.setattr(Cargo.objects, 'filter', lambda *args, **kwargs: Cargo.objects.none())
    with pytest.raises(ValidationError) as erro:
        gerenciar_cargo(plataforma, cenario.x, 'Usuário', ['ver'], base='usuario')
    assert erro.value.code == 'nome_duplicado'
    assert Cargo.objects.get_queryset().filter(empresa=cenario.x, nome='Usuário').count() == 1


def test_edicao_com_versao_velha_e_recusada_e_nao_sobrescreve(cenario, plataforma):
    cargo = gerenciar_cargo(plataforma, cenario.x, 'Campo', ['ver', 'baixar_documento'], base='usuario')
    lida_pelos_dois = cargo.versao
    gerenciar_cargo(plataforma, cenario.x, 'Campo', ['ver'], cargo=cargo, versao=lida_pelos_dois)
    with pytest.raises(ValidationError) as erro:
        gerenciar_cargo(plataforma, cenario.x, 'Campo velho', ['ver', 'baixar_documento'], cargo=cargo, versao=lida_pelos_dois)
    assert erro.value.code == 'cargo_alterado_por_outra_pessoa'
    cargo.refresh_from_db()
    assert (cargo.nome, _codigos(cargo)) == ('Campo', {'ver'})


def test_cada_edicao_soma_um_a_versao(cenario, plataforma):
    cargo = gerenciar_cargo(plataforma, cenario.x, 'Campo', ['ver'], base='usuario')
    inicial = cargo.versao
    for passo in (1, 2):
        gerenciar_cargo(plataforma, cenario.x, 'Campo', ['ver'], cargo=cargo, versao=cargo.versao)
        cargo.refresh_from_db()
        assert cargo.versao == inicial + passo


def test_edicao_sem_versao_falha_fechada(cenario, plataforma):
    cargo = gerenciar_cargo(plataforma, cenario.x, 'Campo', ['ver'], base='usuario')
    with pytest.raises(ValidationError) as erro:
        gerenciar_cargo(plataforma, cenario.x, 'Campo 2', ['ver'], cargo=cargo)
    assert erro.value.code == 'cargo_alterado_por_outra_pessoa'
    cargo.refresh_from_db()
    assert cargo.nome == 'Campo'


def test_conflito_de_versao_nao_audita_nada(cenario, plataforma):
    cargo = gerenciar_cargo(plataforma, cenario.x, 'Campo', ['ver'], base='usuario')
    antes = EventoAuditoria.objects.filter(acao='cargo_alterado').count()
    with pytest.raises(ValidationError):
        gerenciar_cargo(plataforma, cenario.x, 'Campo 2', ['ver'], cargo=cargo, versao=cargo.versao + 5)
    assert EventoAuditoria.objects.filter(acao='cargo_alterado').count() == antes


def test_empresa_arquivada_nao_aceita_cargo_novo_nem_alterado_nem_da_plataforma(cenario, fabrica_pessoa, conceder_direto, plataforma):
    from territorio.cadastro import arquivar
    from permissao.pode import permissoes_efetivas

    admin = fabrica_pessoa('Admin da X')
    conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    arquivar(plataforma, cenario.x)
    for quem in (admin, plataforma):
        with pytest.raises(PermissionDenied):
            gerenciar_cargo(quem, cenario.x, 'Tarde', ['ver'], base='usuario')
    assert not Cargo.objects.filter(nome='Tarde').exists()
    assert 'gerenciar_cargo' not in permissoes_efetivas(admin, cenario.x)
