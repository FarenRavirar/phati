"""003 R10: nome dos níveis da divisão, por empresa; "Nível N" quando não há nome; ligação à criação de sub-área."""

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from comum.models import EventoAuditoria
from territorio.cadastro import arquivar, criar_sub_area
from territorio.models import NivelDivisao, SubArea
from territorio.niveis import definir_nivel, limpar_nivel, nome_do_nivel, nomes_dos_niveis

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_x(cenario, fabrica_pessoa, conceder_direto):
    pessoa = fabrica_pessoa('Admin da X')
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.x)
    return pessoa


def test_nivel_sem_nome_mostra_nivel_n_e_nunca_um_nome_inventado(cenario):
    assert nomes_dos_niveis(cenario.x) == {1: 'Nível 1', 2: 'Nível 2', 3: 'Nível 3'}
    assert nome_do_nivel(cenario.x, 3) == 'Nível 3'


def test_definir_nivel_grava_e_audita_o_nome_antigo_e_o_novo(cenario, admin_x):
    definir_nivel(admin_x, cenario.x, 2, 'Talhão')
    definir_nivel(admin_x, cenario.x, 2, '  Pivô  ')
    assert nome_do_nivel(cenario.x, 2) == 'Pivô'
    primeiro, segundo = EventoAuditoria.objects.filter(acao='nivel_definido').order_by('pk')
    assert primeiro.detalhes == {'nivel': 2, 'nome_antigo': None, 'nome_novo': 'Talhão'}
    assert segundo.detalhes == {'nivel': 2, 'nome_antigo': 'Talhão', 'nome_novo': 'Pivô'}


def test_renomear_o_nivel_muda_o_que_a_criacao_de_sub_area_mostra(cenario, admin_x):
    definir_nivel(admin_x, cenario.x, 1, 'Gleba')
    pai = criar_sub_area(admin_x, cenario.f2, 'Gleba Norte')
    assert nome_do_nivel(cenario.x, pai.nivel) == 'Gleba'
    definir_nivel(admin_x, cenario.x, 1, 'Quadra')
    filha = criar_sub_area(admin_x, cenario.f2, 'Subdivisão', pai=SubArea.objects.get(pk=pai.pk))
    assert nome_do_nivel(cenario.x, filha.nivel - 1) == 'Quadra'


@pytest.mark.parametrize('nivel', [0, 4])
def test_nivel_fora_de_1_a_3_e_recusado(cenario, admin_x, nivel):
    with pytest.raises(ValidationError) as erro:
        definir_nivel(admin_x, cenario.x, nivel, 'Qualquer')
    assert erro.value.code == 'nivel_invalido'


@pytest.mark.parametrize('nome', ['', '   ', 'x' * 101])
def test_nome_de_nivel_invalido_e_recusado(cenario, admin_x, nome):
    with pytest.raises(ValidationError) as erro:
        definir_nivel(admin_x, cenario.x, 1, nome)
    assert erro.value.code == 'nome_invalido'
    assert not NivelDivisao.objects.filter(empresa=cenario.x).exists()


def test_so_quem_tem_a_acao_na_empresa_define_nivel(cenario, fabrica_pessoa, conceder_direto):
    for base in ('curador', 'tecnico', 'usuario'):
        pessoa = fabrica_pessoa(f'Pessoa {base}')
        conceder_direto(pessoa, cenario.cargos_x[base], cenario.x)
        with pytest.raises(PermissionDenied):
            definir_nivel(pessoa, cenario.x, 1, 'Invasor')
    estranho = fabrica_pessoa('Admin da Y')
    conceder_direto(estranho, cenario.cargos_y['administrador'], cenario.y)
    with pytest.raises(PermissionDenied):
        definir_nivel(estranho, cenario.x, 1, 'Invasor')
    assert not NivelDivisao.objects.filter(empresa=cenario.x).exists()


def test_empresa_arquivada_nao_define_nivel(cenario, plataforma):
    arquivar(plataforma, cenario.x)
    with pytest.raises(PermissionDenied):
        definir_nivel(plataforma, cenario.x, 1, 'Gleba')


def test_limpar_nivel_volta_a_mostrar_nivel_n_e_audita_o_nome_antigo(cenario, admin_x):
    definir_nivel(admin_x, cenario.x, 1, 'Quadra')
    limpar_nivel(admin_x, cenario.x, 1)
    assert nome_do_nivel(cenario.x, 1) == 'Nível 1'
    ultimo = EventoAuditoria.objects.filter(acao='nivel_definido').order_by('pk').last()
    assert ultimo is not None
    assert ultimo.detalhes == {'nivel': 1, 'nome_antigo': 'Quadra', 'nome_novo': None}


def test_limpar_nivel_sem_nome_nao_faz_nada_e_exige_permissao(cenario, admin_x, fabrica_pessoa, conceder_direto):
    limpar_nivel(admin_x, cenario.x, 2)
    assert not EventoAuditoria.objects.filter(acao='nivel_definido').exists()
    usuario = fabrica_pessoa('Usuaria')
    conceder_direto(usuario, cenario.cargos_x['usuario'], cenario.x)
    with pytest.raises(PermissionDenied):
        limpar_nivel(usuario, cenario.x, 2)
    with pytest.raises(ValidationError):
        limpar_nivel(admin_x, cenario.x, 4)
