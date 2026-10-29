"""A7 (R7, R14): a listagem de fazendas devolve só as autorizadas."""

from datetime import timedelta

import pytest
from django.utils import timezone

from permissao.models import Cargo, CargoPermissao
from territorio.cadastro import criar_fazenda
from territorio.listagem import fazendas_autorizadas
from territorio.models import Empresa, Fazenda

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
