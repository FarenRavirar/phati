from datetime import timedelta

import pytest
from django.db import IntegrityError, ProgrammingError, connections, transaction
from django.utils import timezone

from permissao.models import Cargo, CategoriaDado, Concessao, ConcessaoCategoria, Permissao
from territorio.models import Fazenda, SubArea

pytestmark = pytest.mark.django_db

NAO_DELEGAVEIS = {'aprovar_geometria', 'tornar_revisao_vigente', 'criar_empresa'}


def test_catalogo_tem_27_acoes():
    assert Permissao.objects.count() == 27


def test_so_tres_acoes_sao_nao_delegaveis():
    assert set(Permissao.objects.filter(delegavel=False).values_list('codigo', flat=True)) == NAO_DELEGAVEIS


@pytest.mark.django_db(databases=['default', 'app'])
def test_papel_app_le_o_catalogo_mas_nao_escreve():
    with connections['app'].cursor() as consulta:
        consulta.execute('SELECT count(*) FROM permissao')
        assert consulta.fetchone() == (27,)
        for escrita in ("INSERT INTO permissao VALUES ('x', 'x', true)", 'UPDATE permissao SET delegavel = true', 'DELETE FROM permissao'):
            # savepoint: a falha aborta a transação do teste e a próxima escrita precisa rodar.
            with pytest.raises(ProgrammingError, match='permission denied'), transaction.atomic(using='app'):
                consulta.execute(escrita)


# --- T3.1: restrições de cargo, concessão e categoria (valem no banco, não só na classe) ---


def _recusa(esperada, **campos):
    with pytest.raises(IntegrityError, match=esperada), transaction.atomic():
        Concessao.objects.create(**campos)


@pytest.fixture
def partes(fabrica_pessoa):
    return {'pessoa': fabrica_pessoa('Titular'), 'concedida_por': fabrica_pessoa('Quem Concede')}


def test_concessao_valida_em_cada_escopo_e_aceita(cenario, partes):
    cargo = cenario.cargos_x['usuario']
    Concessao.objects.create(cargo=cargo, empresa=cenario.x, **partes)
    Concessao.objects.create(cargo=cargo, empresa=cenario.x, fazenda=cenario.f1, **partes)
    Concessao.objects.create(cargo=cargo, empresa=cenario.x, fazenda=cenario.f1, sub_area=cenario.t1, **partes)
    assert Concessao.objects.count() == 3


def test_sub_area_sem_fazenda_e_recusada(cenario, partes):
    _recusa('concessao_sub_area_exige_fazenda', cargo=cenario.cargos_x['usuario'], empresa=cenario.x, sub_area=cenario.g1, **partes)


def test_escopo_de_outra_empresa_e_recusado(cenario, partes):
    cargo = cenario.cargos_x['usuario']
    _recusa('concessao_fazenda_da_empresa', cargo=cenario.cargos_y['usuario'], empresa=cenario.y, fazenda=cenario.f1, **partes)
    _recusa('concessao_fazenda_da_empresa', cargo=cargo, empresa=cenario.x, fazenda=cenario.fy, **partes)


def test_sub_area_de_outra_fazenda_e_recusada(cenario, partes):
    _recusa(
        'concessao_sub_area_da_fazenda',
        cargo=cenario.cargos_x['usuario'], empresa=cenario.x, fazenda=cenario.f2, sub_area=cenario.g1, **partes,
    )  # fmt: skip


def test_cargo_de_outra_empresa_e_recusado(cenario, partes):
    _recusa('concessao_cargo_da_empresa', cargo=cenario.cargos_y['usuario'], empresa=cenario.x, **partes)


def test_periodo_invertido_e_revogacao_incompleta_sao_recusados(cenario, partes):
    cargo, agora = cenario.cargos_x['usuario'], timezone.now()
    _recusa('concessao_periodo_valido', cargo=cargo, empresa=cenario.x, inicio=agora, fim=agora - timedelta(days=1), **partes)
    _recusa('concessao_periodo_valido', cargo=cargo, empresa=cenario.x, inicio=agora, fim=agora, **partes)
    _recusa('concessao_revogacao_completa', cargo=cargo, empresa=cenario.x, revogada_em=agora, **partes)
    _recusa('concessao_revogacao_completa', cargo=cargo, empresa=cenario.x, revogada_por=partes['pessoa'], **partes)


def test_categoria_so_em_cargo_de_tecnico_ou_usuario(cenario, partes):
    solo = CategoriaDado.objects.create(empresa=cenario.x, nome='Solo')
    for base in ('tecnico', 'usuario'):
        concessao = Concessao.objects.create(cargo=cenario.cargos_x[base], empresa=cenario.x, **partes)
        ConcessaoCategoria.objects.create(concessao=concessao, categoria=solo)
    for base in ('curador', 'administrador'):
        concessao = Concessao.objects.create(cargo=cenario.cargos_x[base], empresa=cenario.x, **partes)
        with pytest.raises(IntegrityError, match='nível técnico ou usuário'), transaction.atomic():
            ConcessaoCategoria.objects.create(concessao=concessao, categoria=solo)


def test_categoria_de_outra_empresa_e_recusada(cenario, partes):
    alheia = CategoriaDado.objects.create(empresa=cenario.y, nome='Alheia')
    concessao = Concessao.objects.create(cargo=cenario.cargos_x['tecnico'], empresa=cenario.x, **partes)
    with pytest.raises(IntegrityError, match='categoria de outra empresa'), transaction.atomic():
        ConcessaoCategoria.objects.create(concessao=concessao, categoria=alheia)


def test_trocar_a_categoria_de_lugar_tambem_e_validado(cenario, partes):
    solo = CategoriaDado.objects.create(empresa=cenario.x, nome='Solo')
    alheia = CategoriaDado.objects.create(empresa=cenario.y, nome='Alheia')
    concessao = Concessao.objects.create(cargo=cenario.cargos_x['tecnico'], empresa=cenario.x, **partes)
    ligacao = ConcessaoCategoria.objects.create(concessao=concessao, categoria=solo)
    with pytest.raises(IntegrityError, match='categoria de outra empresa'), transaction.atomic():
        ConcessaoCategoria.objects.filter(pk=ligacao.pk).update(categoria=alheia)


def test_base_e_empresa_do_cargo_nao_mudam(cenario):
    cargo = cenario.cargos_x['usuario']
    with pytest.raises(IntegrityError, match='base e empresa'), transaction.atomic():
        Cargo.objects.filter(pk=cargo.pk).update(base='curador')
    with pytest.raises(IntegrityError, match='base e empresa'), transaction.atomic():
        Cargo.objects.filter(pk=cargo.pk).update(empresa=cenario.y)
    assert Cargo.objects.filter(pk=cargo.pk).update(nome='Usuário renomeado') == 1


def test_base_invalida_e_nome_repetido_na_empresa_sao_recusados(cenario):
    with pytest.raises(IntegrityError, match='cargo_base_valida'), transaction.atomic():
        Cargo.objects.create(empresa=cenario.x, nome='Estranho', base='gerente')
    with pytest.raises(IntegrityError, match='cargo_nome_unico_por_empresa'), transaction.atomic():
        Cargo.objects.create(empresa=cenario.x, nome='Curador', base='curador')


def test_concessao_so_muda_o_fim_e_a_revogacao(cenario, partes):
    concessao = Concessao.objects.create(cargo=cenario.cargos_x['usuario'], empresa=cenario.x, fazenda=cenario.f1, **partes)
    trocas = [
        {'cargo': cenario.cargos_x['tecnico']},
        {'fazenda': cenario.f2},
        {'sub_area': cenario.g1},
        {'pessoa': partes['concedida_por']},
        {'concedida_por': partes['pessoa']},
        {'inicio': timezone.now() - timedelta(days=9)},
    ]
    for troca in trocas:
        with pytest.raises(IntegrityError, match='só o fim e a revogação'), transaction.atomic():
            Concessao.objects.filter(pk=concessao.pk).update(**troca)
    agora = timezone.now()
    assert Concessao.objects.filter(pk=concessao.pk).update(fim=agora + timedelta(days=30)) == 1
    assert Concessao.objects.filter(pk=concessao.pk).update(revogada_em=agora, revogada_por=partes['concedida_por']) == 1


def test_sub_area_e_fazenda_com_concessao_nao_mudam_de_dono(cenario, partes):
    Concessao.objects.create(
        cargo=cenario.cargos_x['usuario'], empresa=cenario.x, fazenda=cenario.f1, sub_area=cenario.g1, **partes
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        SubArea.objects.filter(pk=cenario.g1.pk).update(fazenda=cenario.f2)
    with pytest.raises(IntegrityError), transaction.atomic():
        Fazenda.objects.filter(pk=cenario.f1.pk).update(empresa=cenario.y)


@pytest.mark.django_db(databases=['default', 'app'])
def test_papel_app_acessa_as_tabelas_novas(db):
    # O papel `app` é outra conexão e não enxerga a transação do teste: a prova é a ausência de `permission denied`.
    with connections['app'].cursor() as consulta:
        for tabela in ('cargo', 'cargo_permissao', 'categoria_dado', 'concessao', 'concessao_categoria'):
            consulta.execute(f'SELECT count(*) FROM {tabela}')
            assert consulta.fetchone() is not None
            consulta.execute(f'UPDATE {tabela} SET id = id WHERE false')
            consulta.execute(f'DELETE FROM {tabela} WHERE false')
