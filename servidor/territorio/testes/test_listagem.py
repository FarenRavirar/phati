"""A7 (R7, R14): a listagem de fazendas devolve só as autorizadas."""

from datetime import datetime, timedelta, timezone as fuso_horario
from uuid import uuid4
from importlib import import_module

import pytest
from django.contrib.gis.geos import GEOSGeometry
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from catalogo.models import Camada, Estudo, Feicao, Tema, VersaoCamada
from permissao.models import Cargo, CargoPermissao, Permissao
from territorio.cadastro import arquivar, criar_fazenda
from django.core.exceptions import PermissionDenied

from territorio.listagem import (
    empresas_autorizadas, empresas_com_nova_fazenda, exportar_fazendas, fazendas_autorizadas, listar_fazendas, pode_exportar_fazendas,
    sub_areas_da_fazenda,
)
from territorio.models import Empresa, Fazenda, NivelDivisao, SubArea

pytestmark = pytest.mark.django_db


def _nomes(pessoa):
    return [f.nome for f in fazendas_autorizadas(pessoa)]


def test_administrador_cria_15_fazendas_uma_a_uma_e_o_usuario_lista_so_as_autorizadas(cenario, fabrica_pessoa, conceder_direto):
    admin = fabrica_pessoa('Admin da X')
    conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    for numero in range(15):
        criar_fazenda(admin, cenario.x, f'Nova {numero:02d}')
    assert Fazenda.objects.filter(empresa=cenario.x).count() == 17  # 15 novas + F1 + F2 do cenário
    usuario = fabrica_pessoa('Usuario Um')
    conceder_direto(usuario, cenario.cargos_x['usuario'], cenario.f1)
    assert _nomes(usuario) == ['F1']
    assert len(_nomes(admin)) == 17


def test_administrador_de_outra_empresa_lista_zero_das_fazendas_da_primeira(cenario, fabrica_pessoa, conceder_direto):
    admin_y = fabrica_pessoa('Admin da Y')
    conceder_direto(admin_y, cenario.cargos_y['administrador'], cenario.y)
    assert _nomes(admin_y) == ['FY']


def test_concessao_de_empresa_lista_todas_as_fazendas_dela(cenario, fabrica_pessoa, conceder_direto):
    usuario = fabrica_pessoa('Usuario Empresa')
    conceder_direto(usuario, cenario.cargos_x['usuario'], cenario.x)
    assert _nomes(usuario) == ['F1', 'F2']


def test_concessao_de_sub_area_lista_a_fazenda_que_a_contem(cenario, fabrica_pessoa, conceder_direto):
    usuario = fabrica_pessoa('Usuario Sub Area')
    conceder_direto(usuario, cenario.cargos_x['usuario'], cenario.t1)
    assert _nomes(usuario) == ['F1']


def test_duas_concessoes_em_empresas_diferentes_listam_as_duas(cenario, fabrica_pessoa, conceder_direto):
    externo = fabrica_pessoa('Colaborador Externo')
    conceder_direto(externo, cenario.cargos_x['usuario'], cenario.f2)
    conceder_direto(externo, cenario.cargos_y['usuario'], cenario.y)
    assert _nomes(externo) == ['F2', 'FY']


def test_sem_concessao_lista_zero(cenario, fabrica_pessoa):
    assert _nomes(fabrica_pessoa('Sem Nada')) == []


def test_cargo_sem_ver_lista_zero(cenario, fabrica_pessoa, conceder_direto):
    cego = Cargo.objects.create(empresa=cenario.x, nome='Sem ver', base='tecnico')
    CargoPermissao.objects.create(cargo=cego, permissao_id='criar_registro_campo')
    pessoa = fabrica_pessoa('Sem Ver')
    conceder_direto(pessoa, cego, cenario.x)
    assert _nomes(pessoa) == []


def test_concessao_revogada_ou_vencida_lista_zero(cenario, fabrica_pessoa, conceder_direto):
    agora = timezone.now()
    vencida, revogada = fabrica_pessoa('Vencida'), fabrica_pessoa('Revogada')
    conceder_direto(vencida, cenario.cargos_x['usuario'], cenario.f1, inicio=agora - timedelta(days=2), fim=agora - timedelta(days=1))
    conceder_direto(revogada, cenario.cargos_x['usuario'], cenario.f1, revogada_em=agora, revogada_por=vencida)
    assert _nomes(vencida) == []
    assert _nomes(revogada) == []


def test_plataforma_lista_todas_as_fazendas_de_todas_as_empresas(cenario, plataforma):
    assert _nomes(plataforma) == ['F1', 'F2', 'FY']


def test_fazenda_de_empresa_sem_concessao_nao_aparece(cenario, fabrica_pessoa, conceder_direto):
    vazia = Empresa.objects.create(nome='Vazia')
    usuario = fabrica_pessoa('Usuario Um')
    conceder_direto(usuario, cenario.cargos_x['usuario'], cenario.f1)
    Fazenda.objects.create(empresa=vazia, nome='Da Vazia')
    assert _nomes(usuario) == ['F1']


def _empresas(pessoa):
    return [e.nome for e in empresas_autorizadas(pessoa)]


def _sub_areas(pessoa, fazenda):
    return [s.nome for s in sub_areas_da_fazenda(pessoa, fazenda)]


def test_plataforma_lista_todas_as_empresas(cenario, plataforma):
    assert _empresas(plataforma) == ['Empresa X', 'Empresa Y']


def test_administrador_da_empresa_x_lista_so_a_x(cenario, fabrica_pessoa, conceder_direto):
    admin = fabrica_pessoa('Admin da X')
    conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    assert _empresas(admin) == ['Empresa X']


def test_concessao_de_fazenda_ou_sub_area_lista_a_empresa_que_a_contem(cenario, fabrica_pessoa, conceder_direto):
    na_fazenda, na_sub_area = fabrica_pessoa('Na Fazenda'), fabrica_pessoa('Na Sub Area')
    conceder_direto(na_fazenda, cenario.cargos_x['usuario'], cenario.f2)
    conceder_direto(na_sub_area, cenario.cargos_y['usuario'], cenario.fy)
    assert _empresas(na_fazenda) == ['Empresa X']
    assert _empresas(na_sub_area) == ['Empresa Y']


def test_pessoa_sem_concessao_lista_zero_empresas(cenario, fabrica_pessoa):
    assert _empresas(fabrica_pessoa('Sem Nada')) == []


@pytest.fixture
def catalogo(db):
    """Teste transacional esvazia o catálogo carregado pela migração; recria antes do `cenario` (mesmo molde de test_api)."""
    for codigo, descricao, delegavel in (*import_module('permissao.migrations.0001_initial').ACOES, *import_module('territorio.migrations.0008_fase_fazendas').ACOES):
        Permissao.objects.get_or_create(codigo=codigo, defaults={'descricao': descricao, 'delegavel': delegavel})


@pytest.fixture
def pessoas_do_papel_app(cenario, fabrica_pessoa, conceder_direto):
    """Cria os dados como dono: com `como_app` ativo a escrita já passaria pela RLS."""
    na_g1 = fabrica_pessoa('Na G1')
    conceder_direto(na_g1, cenario.cargos_x['usuario'], cenario.g1)
    return fabrica_pessoa('Sem Nada'), na_g1


@pytest.mark.django_db(transaction=True, databases=['default', 'app'])
def test_sob_o_papel_app_sem_contexto_zero_linhas_e_com_concessao_so_o_escopo(catalogo, cenario, pessoas_do_papel_app, como_app):
    # `como_app` troca a conexão `default` pelo papel `app`: a RLS vale, e as listagens abrem `com_permissao`.
    sem_nada, na_g1 = pessoas_do_papel_app
    assert list(Empresa.objects.all()) == []
    assert list(SubArea.objects.all()) == []
    assert _empresas(sem_nada) == []
    assert _sub_areas(sem_nada, cenario.f1) == []
    assert _empresas(na_g1) == ['Empresa X']
    assert _sub_areas(na_g1, cenario.f1) == ['G1', 'T1']


def test_concessao_de_empresa_ou_fazenda_lista_todas_as_sub_areas_da_fazenda(cenario, fabrica_pessoa, conceder_direto):
    da_empresa, da_fazenda = fabrica_pessoa('Da Empresa'), fabrica_pessoa('Da Fazenda')
    conceder_direto(da_empresa, cenario.cargos_x['usuario'], cenario.x)
    conceder_direto(da_fazenda, cenario.cargos_x['usuario'], cenario.f1)
    assert _sub_areas(da_empresa, cenario.f1) == ['G1', 'G2', 'T1']
    assert _sub_areas(da_fazenda, cenario.f1) == ['G1', 'G2', 'T1']


def test_concessao_de_sub_area_lista_ela_e_as_descendentes_e_nao_as_irmas(cenario, fabrica_pessoa, conceder_direto):
    pessoa = fabrica_pessoa('Na G1')
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.g1)
    assert _sub_areas(pessoa, cenario.f1) == ['G1', 'T1']


def test_sub_areas_de_fazenda_de_outra_empresa_voltam_vazias(cenario, fabrica_pessoa, conceder_direto):
    admin_y = fabrica_pessoa('Admin da Y')
    conceder_direto(admin_y, cenario.cargos_y['administrador'], cenario.y)
    assert _sub_areas(admin_y, cenario.f1) == []
    assert _sub_areas(fabrica_pessoa('Sem Nada'), cenario.f1) == []


def test_plataforma_lista_as_sub_areas_de_qualquer_fazenda(cenario, plataforma):
    assert _sub_areas(plataforma, cenario.f1) == ['G1', 'G2', 'T1']


def test_filtro_por_pk_devolve_so_o_pedido_e_nunca_o_nao_autorizado(cenario, fabrica_pessoa, conceder_direto, plataforma):
    # PR #19: a URL de escopo pede uma linha, não a lista inteira; o filtro não amplia o acesso.
    admin = fabrica_pessoa('Admin X')
    conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    assert [e.pk for e in empresas_autorizadas(admin, pk=cenario.x.pk)] == [cenario.x.pk]
    assert empresas_autorizadas(admin, pk=cenario.y.pk) == []
    assert [f.pk for f in fazendas_autorizadas(admin, pk=cenario.f1.pk)] == [cenario.f1.pk]
    assert fazendas_autorizadas(admin, pk=cenario.fy.pk) == []
    assert [f.pk for f in fazendas_autorizadas(plataforma, pk=cenario.fy.pk)] == [cenario.fy.pk]
    assert fazendas_autorizadas(plataforma, pk=999_999) == []


def test_empresa_id_filtra_na_consulta_e_nao_abre_empresa_sem_acesso(cenario, fabrica_pessoa, conceder_direto, plataforma):
    admin = fabrica_pessoa('Admin da X')
    conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    assert {f.empresa_id for f in fazendas_autorizadas(plataforma)} == {cenario.x.pk, cenario.y.pk}
    assert [f.pk for f in fazendas_autorizadas(plataforma, empresa_id=cenario.y.pk)] == [cenario.fy.pk]
    assert {f.empresa_id for f in fazendas_autorizadas(admin, empresa_id=cenario.x.pk)} == {cenario.x.pk}
    assert fazendas_autorizadas(admin, empresa_id=cenario.y.pk) == []  # o filtro não amplia o acesso


# --- 003 R11: listas de trabalho não trazem arquivado; a seção "Arquivadas" pede só os arquivados ---


def test_arquivada_sai_das_listas_de_trabalho_e_entra_so_na_lista_de_arquivadas(cenario, plataforma):
    from territorio.cadastro import arquivar

    arquivar(plataforma, cenario.f1)
    assert [f.nome for f in fazendas_autorizadas(plataforma, empresa_id=cenario.x.pk)] == ['F2']
    assert [f.nome for f in fazendas_autorizadas(plataforma, arquivadas=True)] == ['F1']
    assert {f.nome for f in fazendas_autorizadas(plataforma, arquivadas=None, empresa_id=cenario.x.pk)} == {'F1', 'F2'}
    fazenda = Fazenda.objects.get(pk=cenario.f1.pk)
    assert sub_areas_da_fazenda(plataforma, fazenda) == []
    assert {s.nome for s in sub_areas_da_fazenda(plataforma, fazenda, arquivadas=True)} == {'G1', 'T1', 'G2'}


def test_empresa_arquivada_sai_da_lista_de_empresas(cenario, plataforma):
    from territorio.cadastro import arquivar

    arquivar(plataforma, cenario.x)
    assert [e.nome for e in empresas_autorizadas(plataforma)] == ['Empresa Y']
    assert [e.nome for e in empresas_autorizadas(plataforma, arquivadas=True)] == ['Empresa X']
    assert len(empresas_autorizadas(plataforma, arquivadas=None)) == 2


def test_quem_nao_tinha_acesso_nao_ve_a_arquivada_de_outra_empresa(cenario, plataforma, fabrica_pessoa, conceder_direto):
    from territorio.cadastro import arquivar

    arquivar(plataforma, cenario.f1)
    admin_y = fabrica_pessoa('Admin da Y')
    conceder_direto(admin_y, cenario.cargos_y['administrador'], cenario.y)
    assert fazendas_autorizadas(admin_y, arquivadas=True) == []
    assert fazendas_autorizadas(admin_y, arquivadas=None, pk=cenario.f1.pk) == []


def test_busca_sem_acento_acha_nome_com_acento_nos_dois_lados(cenario, plataforma):
    from territorio.models import Fazenda

    Fazenda.objects.filter(pk=cenario.f1.pk).update(nome='São Jorge')
    assert list(Fazenda.objects.filter(nome__unaccent__icontains='sao jorge').values_list('nome', flat=True)) == ['São Jorge']
    assert list(Fazenda.objects.filter(nome__unaccent__icontains='SÃO').values_list('nome', flat=True)) == ['São Jorge']
    assert not Fazenda.objects.filter(nome__unaccent__icontains='nao existe').exists()


# --- spec 012 T4.2: serviço da listagem paginada (R20) ---

DATA_ANTIGA = datetime(2020, 1, 1, tzinfo=fuso_horario.utc)
DATA_VERSAO = datetime(2026, 1, 10, tzinfo=fuso_horario.utc)


def _nomes_da_pagina(pagina):
    return [linha.fazenda.nome for linha in pagina.linhas]


def _por_nome(pagina):
    return {linha.fazenda.nome: linha for linha in pagina.linhas}


def _versao(enviou, fazenda, criada_em, sub_area=None):
    """Versão de camada sintética; `sub_area` põe uma feição nela (a versão passa a ser da sub-área)."""
    tema = Tema.objects.create(empresa=fazenda.empresa, nome=f'Tema {fazenda.nome}')
    estudo = Estudo.objects.create(empresa=fazenda.empresa, fazenda=fazenda, tema=tema, nome=f'Estudo {fazenda.nome}')
    camada = Camada.objects.create(estudo=estudo, empresa=fazenda.empresa, fazenda=fazenda, nome=f'Camada {fazenda.nome}')
    versao = VersaoCamada.objects.create(
        camada=camada, empresa=fazenda.empresa, fazenda=fazenda, numero=1, sistema_original='EPSG:4674',
        origem='Levantamento sintetico', hash_original='a' * 64, caminho_original='x.bin', enviada_por=enviou,
    )
    VersaoCamada.objects.filter(pk=versao.pk).update(criada_em=criada_em)
    if sub_area is not None:
        geometria = GEOSGeometry('POLYGON((-48.40 -10.80,-48.30 -10.80,-48.30 -10.60,-48.40 -10.60,-48.40 -10.80))', srid=4674)
        Feicao.objects.create(versao=versao, empresa=fazenda.empresa, fazenda=fazenda, geometria=geometria, sub_area=sub_area, valores={})
    return versao


def test_listagem_feliz_traz_linhas_talhoes_e_contagens(cenario, plataforma):
    pagina = listar_fazendas(plataforma)
    assert _nomes_da_pagina(pagina) == ['F1', 'F2', 'FY']
    # Talhão = sub-área ativa de nível 2: só o T1 de F1 (G1 e G2 são de nível 1).
    assert [linha.talhoes for linha in pagina.linhas] == [1, 0, 0]
    assert (pagina.total_filtrado, pagina.total) == (3, 3)
    assert pagina.rotulo_talhoes == 'Talhões'
    assert pagina.pagina.number == 1


def test_area_sem_vigencia_e_none_nunca_zero(cenario, plataforma):
    assert {linha.area for linha in listar_fazendas(plataforma).linhas} == {None}


def test_atualizado_e_a_data_mais_recente_entre_criacao_e_versao(cenario, plataforma, fabrica_pessoa):
    Fazenda.objects.filter(pk=cenario.f1.pk).update(criada_em=DATA_ANTIGA)
    _versao(fabrica_pessoa('Enviou'), cenario.f1, DATA_VERSAO)
    linhas = _por_nome(listar_fazendas(plataforma))
    assert linhas['F1'].atualizado == DATA_VERSAO
    assert linhas['F2'].atualizado == Fazenda.objects.get(pk=cenario.f2.pk).criada_em  # sem versão: a criação


def test_busca_sem_acento_e_caixa_por_nome_ou_municipio(cenario, plataforma):
    Fazenda.objects.filter(pk=cenario.f2.pk).update(municipio='São Félix')
    assert _nomes_da_pagina(listar_fazendas(plataforma, busca='sao felix')) == ['F2']
    assert _nomes_da_pagina(listar_fazendas(plataforma, busca='SÃO FÉLIX')) == ['F2']
    assert _nomes_da_pagina(listar_fazendas(plataforma, busca='  f1  ')) == ['F1']
    pagina = listar_fazendas(plataforma, busca='f1')
    assert (pagina.total_filtrado, pagina.total) == (1, 3)


@pytest.mark.parametrize(
    ('busca', 'esperado'),
    [
        ('%', []),  # coringa do LIKE não vira "todas"
        ('_', []),
        ("'", []),
        ('"', []),
        ("x' OR '1'='1", []),
        ('\\', []),
        ('a' * 5000, []),  # cortada em 100 caracteres, sem resultado
        ('\x00', ['F1', 'F2', 'FY']),  # NUL é retirado (o PostgreSQL recusa): vira busca vazia
        ('   ', ['F1', 'F2', 'FY']),
    ],
)
def test_busca_hostil_nao_quebra_nem_vira_coringa(cenario, plataforma, busca, esperado):
    assert _nomes_da_pagina(listar_fazendas(plataforma, busca=busca)) == esperado


def test_busca_com_nul_no_meio_acha_o_nome_sem_o_nul(cenario, plataforma):
    assert _nomes_da_pagina(listar_fazendas(plataforma, busca='F\x001')) == ['F1']


def test_busca_que_nao_e_texto_vira_busca_vazia(cenario, plataforma):
    assert _nomes_da_pagina(listar_fazendas(plataforma, busca=['F1'])) == ['F1', 'F2', 'FY']


def test_filtro_de_situacao_e_valor_invalido_cai_em_todas(cenario, plataforma):
    arquivar(plataforma, cenario.f2)
    assert _nomes_da_pagina(listar_fazendas(plataforma, situacao='ativas')) == ['F1', 'FY']
    assert _nomes_da_pagina(listar_fazendas(plataforma, situacao='arquivadas')) == ['F2']
    pagina_todas = listar_fazendas(plataforma, situacao='todas')
    assert _nomes_da_pagina(pagina_todas) == ['F1', 'F2', 'FY']
    assert (pagina_todas.total_filtrado, pagina_todas.total) == (3, 3)
    for invalida in ('xyz', '', None, ['ativas']):
        assert _nomes_da_pagina(listar_fazendas(plataforma, situacao=invalida)) == ['F1', 'F2', 'FY']


def _muitas_fazendas(cenario, quantidade):
    for numero in range(quantidade):
        Fazenda.objects.create(empresa=cenario.x, nome=f'Extra {numero:02d}')


def test_paginacao_de_25_por_pagina_com_contagem_filtrada_e_sem_filtro(cenario, plataforma):
    _muitas_fazendas(cenario, 25)  # 28 no total
    primeira = listar_fazendas(plataforma, pagina=1)
    assert len(primeira.linhas) == 25
    assert (primeira.total_filtrado, primeira.total) == (28, 28)
    assert primeira.pagina.has_next()
    segunda = listar_fazendas(plataforma, pagina='2')
    assert len(segunda.linhas) == 3
    assert not segunda.pagina.has_next()


@pytest.mark.parametrize(
    ('pagina_pedida', 'pagina_servida'),
    [
        ('abc', 1),  # texto: primeira página
        ('', 1),
        (None, 1),
        ('1.5', 1),
        ('999', 2),  # além do fim: última página
        ('0', 2),  # medido: Paginator.get_page manda 0 e negativa para a última, não para a primeira
        ('-1', 2),
    ],
)
def test_pagina_invalida_cai_em_pagina_servivel(cenario, plataforma, pagina_pedida, pagina_servida):
    _muitas_fazendas(cenario, 25)  # 28 fazendas: duas páginas
    assert listar_fazendas(plataforma, pagina=pagina_pedida).pagina.number == pagina_servida


def test_fazenda_de_outra_empresa_nunca_aparece_nem_buscando_o_nome(cenario, fabrica_pessoa, conceder_direto):
    admin_x = fabrica_pessoa('Admin da X')
    conceder_direto(admin_x, cenario.cargos_x['administrador'], cenario.x)
    assert _nomes_da_pagina(listar_fazendas(admin_x)) == ['F1', 'F2']
    pagina = listar_fazendas(admin_x, busca='FY')
    assert pagina.linhas == [] and (pagina.total_filtrado, pagina.total) == (0, 2)
    assert listar_fazendas(admin_x, busca='Empresa Y').linhas == []
    assert listar_fazendas(admin_x, empresa_id=cenario.y.pk).linhas == []


def test_empresa_id_limita_a_pagina_da_empresa_e_rotula_o_talhao(cenario, plataforma):
    pagina = listar_fazendas(plataforma, empresa_id=cenario.x.pk)
    assert _nomes_da_pagina(pagina) == ['F1', 'F2']
    assert (pagina.total_filtrado, pagina.total) == (2, 2)
    assert pagina.rotulo_talhoes == 'Nível 2'  # empresa sem nome configurado: o padrão de `nome_do_nivel`
    NivelDivisao.objects.create(empresa=cenario.x, nivel=2, nome='Talhão')
    assert listar_fazendas(plataforma, empresa_id=cenario.x.pk).rotulo_talhoes == 'Talhão'


def test_alcance_de_sub_area_so_conta_os_talhoes_alcancados(cenario, plataforma, fabrica_pessoa, conceder_direto):
    t2 = SubArea.objects.create(empresa=cenario.x, fazenda=cenario.f1, pai=cenario.g2, nivel=2, nome='T2')
    t2.refresh_from_db()
    na_g1 = fabrica_pessoa('Na G1')
    conceder_direto(na_g1, cenario.cargos_x['usuario'], cenario.g1)
    pagina = listar_fazendas(na_g1)
    assert _nomes_da_pagina(pagina) == ['F1']  # F2 não tem sub-área alcançada
    assert [linha.talhoes for linha in pagina.linhas] == [1]  # T1 sob G1; T2 sob G2 fica fora
    assert [linha.talhoes for linha in listar_fazendas(plataforma).linhas] == [2, 0, 0]


def test_talhao_arquivado_fica_fora_da_contagem(cenario, plataforma):
    arquivar(plataforma, cenario.t1)
    assert _por_nome(listar_fazendas(plataforma))['F1'].talhoes == 0


def test_atualizado_ignora_versao_que_a_pessoa_nao_alcanca(cenario, plataforma, fabrica_pessoa, conceder_direto):
    Fazenda.objects.filter(pk=cenario.f1.pk).update(criada_em=DATA_ANTIGA)
    enviou = fabrica_pessoa('Enviou')
    _versao(enviou, cenario.f1, DATA_VERSAO, sub_area=cenario.t1)  # feição no T1
    na_g2 = fabrica_pessoa('Na G2')
    conceder_direto(na_g2, cenario.cargos_x['usuario'], cenario.g2)  # G2 não contém o T1
    assert _por_nome(listar_fazendas(na_g2))['F1'].atualizado == DATA_ANTIGA
    assert _por_nome(listar_fazendas(plataforma))['F1'].atualizado == DATA_VERSAO


def test_sem_consulta_por_linha_o_numero_de_consultas_nao_cresce(cenario, plataforma, fabrica_pessoa):
    listar_fazendas(plataforma)  # aquece o cache de memória de permissão
    with CaptureQueriesContext(connection) as pequena:
        listar_fazendas(plataforma)
    enviou = fabrica_pessoa('Enviou')
    for numero in range(20):
        fazenda = Fazenda.objects.create(empresa=cenario.x, nome=f'Lote {numero:02d}')
        grupo = SubArea.objects.create(empresa=cenario.x, fazenda=fazenda, nivel=1, nome='G')
        talhao = SubArea.objects.create(empresa=cenario.x, fazenda=fazenda, pai=grupo, nivel=2, nome='T')
        _versao(enviou, fazenda, DATA_VERSAO, sub_area=talhao)
    with CaptureQueriesContext(connection) as grande:
        pagina = listar_fazendas(plataforma)
    assert len(pagina.linhas) == 23
    assert len(grande.captured_queries) == len(pequena.captured_queries)


def _cargo_com(empresa, base, nome, *codigos):
    cargo = Cargo.objects.create(empresa=empresa, nome=nome, base=base)
    CargoPermissao.objects.bulk_create(CargoPermissao(cargo=cargo, permissao_id=codigo) for codigo in codigos)
    return cargo


def _nomes_exportados(pessoa, **filtro):
    return [linha.fazenda.nome for linha in exportar_fazendas(pessoa, **filtro)]


def test_exportar_feliz_administrador_da_empresa_leva_as_fazendas_dela_e_nao_as_alheias(cenario, conceder_direto, fabrica_pessoa):
    admin = fabrica_pessoa('Admin X')
    conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    assert _nomes_exportados(admin) == ['F1', 'F2']


def test_exportar_curador_de_base_exporta_o_que_ve(cenario, conceder_direto, fabrica_pessoa):
    curador = fabrica_pessoa('Curador X')
    conceder_direto(curador, cenario.cargos_x['curador'], cenario.x)
    assert _nomes_exportados(curador) == ['F1', 'F2']


def test_exportar_plataforma_leva_todas_as_empresas(cenario, plataforma):
    assert _nomes_exportados(plataforma) == ['F1', 'F2', 'FY']


def test_exportar_arquivada_e_permitida_e_o_filtro_de_situacao_vale(cenario, plataforma):
    arquivar(plataforma, cenario.f2)
    assert _nomes_exportados(plataforma, situacao='arquivadas') == ['F2']
    assert _nomes_exportados(plataforma, situacao='ativas') == ['F1', 'FY']


def test_exportar_aplica_busca_do_mesmo_jeito_que_a_listagem(cenario, plataforma):
    assert _nomes_exportados(plataforma, busca='f2') == ['F2']
    assert _nomes_exportados(plataforma, busca='nao existe') == []


def test_exportar_filtra_empresa_e_nao_traz_outra_empresa(cenario, plataforma):
    assert _nomes_exportados(plataforma, empresa_id=cenario.y.pk) == ['FY']


def test_exportar_tecnico_e_usuario_sao_negados(cenario, conceder_direto, fabrica_pessoa):
    tecnico = fabrica_pessoa('Tecnico')
    conceder_direto(tecnico, cenario.cargos_x['tecnico'], cenario.x)
    usuario = fabrica_pessoa('Usuario')
    conceder_direto(usuario, cenario.cargos_x['usuario'], cenario.x)
    for pessoa in (tecnico, usuario):
        with pytest.raises(PermissionDenied):
            exportar_fazendas(pessoa)


def test_exportar_curador_so_de_sub_area_e_negado(cenario, conceder_direto, fabrica_pessoa):
    # Concessão de sub-área não exporta a fazenda que a contém: `pode()` exige a fazenda inteira.
    curador = fabrica_pessoa('Curador de sub-area')
    conceder_direto(curador, cenario.cargos_x['curador'], cenario.g1)
    with pytest.raises(PermissionDenied):
        exportar_fazendas(curador)


def test_exportar_sem_nenhuma_concessao_e_negado(cenario, fabrica_pessoa):
    with pytest.raises(PermissionDenied):
        exportar_fazendas(fabrica_pessoa('Sem acesso'))


def test_exportar_so_leva_fazenda_que_a_pessoa_pode_exportar_mesmo_com_ver_nas_duas(cenario, conceder_direto, fabrica_pessoa):
    # Ver nas duas fazendas, exportar só na F1: `pode(..., 'exportar_dados', fazenda)` filtra a F2 por linha.
    pessoa = fabrica_pessoa('Parcial')
    exportador = _cargo_com(cenario.x, 'tecnico', 'Exportador da F1', 'ver', 'exportar_dados')
    conceder_direto(pessoa, exportador, cenario.f1)
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f2)
    assert _nomes_exportados(pessoa) == ['F1']


def test_pode_exportar_fazendas_so_com_exportar_em_fazenda_inteira(cenario, fabrica_pessoa, conceder_direto):
    # Feliz: Administrador de empresa e Curador de base exportam; negativo: Técnico, Usuário e quem tem só sub-área não.
    adm = fabrica_pessoa('Adm X')
    conceder_direto(adm, cenario.cargos_x['administrador'], cenario.x)
    curador = fabrica_pessoa('Curador X')
    conceder_direto(curador, cenario.cargos_x['curador'], cenario.f1)
    tecnico = fabrica_pessoa('Tecnico X')
    conceder_direto(tecnico, cenario.cargos_x['tecnico'], cenario.x)
    usuario = fabrica_pessoa('Usuario X')
    conceder_direto(usuario, cenario.cargos_x['usuario'], cenario.x)
    sub = fabrica_pessoa('Sub X')
    conceder_direto(sub, cenario.cargos_x['curador'], cenario.t1)
    assert pode_exportar_fazendas(adm) is True
    assert pode_exportar_fazendas(curador) is True
    assert pode_exportar_fazendas(tecnico) is False
    assert pode_exportar_fazendas(usuario) is False
    assert pode_exportar_fazendas(sub) is False


def test_pode_exportar_fazendas_sem_concessao_e_plataforma(cenario, fabrica_pessoa, plataforma):
    assert pode_exportar_fazendas(fabrica_pessoa('Sem concessao')) is False
    assert pode_exportar_fazendas(plataforma) is True


def test_empresas_com_nova_fazenda_lista_so_onde_pode_criar(cenario, fabrica_pessoa, conceder_direto):
    # Administrador de X e Y vê as duas; Usuário não cria; empresa arquivada sai (R11).
    dono = fabrica_pessoa('Dono')
    conceder_direto(dono, cenario.cargos_x['administrador'], cenario.x)
    conceder_direto(dono, cenario.cargos_y['administrador'], cenario.y)
    assert [e.nome for e in empresas_com_nova_fazenda(dono)] == ['Empresa X', 'Empresa Y']
    usuario = fabrica_pessoa('Usuario')
    conceder_direto(usuario, cenario.cargos_x['usuario'], cenario.x)
    assert empresas_com_nova_fazenda(usuario) == []
    Empresa.objects.filter(pk=cenario.y.pk).update(arquivada_em=timezone.now(), arquivada_por=dono, arquivamento=uuid4())
    assert [e.nome for e in empresas_com_nova_fazenda(dono)] == ['Empresa X']


def test_empresas_com_nova_fazenda_sem_concessao_e_vazio(cenario, fabrica_pessoa):
    assert empresas_com_nova_fazenda(fabrica_pessoa('Nenhuma')) == []
