"""A7 (R7, R14): a listagem de fazendas devolve só as autorizadas."""

from datetime import timedelta
from importlib import import_module

import pytest
from django.utils import timezone

from permissao.models import Cargo, CargoPermissao, Permissao
from territorio.cadastro import criar_fazenda
from territorio.listagem import empresas_autorizadas, fazendas_autorizadas, sub_areas_da_fazenda
from territorio.models import Empresa, Fazenda, SubArea

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
    for codigo, descricao, delegavel in import_module('permissao.migrations.0001_initial').ACOES:
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
