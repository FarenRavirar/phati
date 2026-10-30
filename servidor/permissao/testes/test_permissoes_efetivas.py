"""R2, R12, A10: `permissoes_efetivas` diz o que a pessoa exerce em um escopo, sem regra própria."""

import pytest

from permissao.models import Cargo, CargoPermissao, Permissao
from permissao.pode import pode, permissoes_efetivas

pytestmark = pytest.mark.django_db

ACOES_DE_GESTAO = {'convidar_pessoa', 'revogar_acesso', 'redefinir_senha'}


def test_usuario_nao_tem_acao_de_gestao_na_propria_fazenda(cenario, fabrica_pessoa, conceder_direto):
    usuario = fabrica_pessoa('Usuario')
    conceder_direto(usuario, cenario.cargos_x['usuario'], cenario.f1)
    efetivas = permissoes_efetivas(usuario, cenario.f1)
    assert 'ver' in efetivas
    assert not efetivas & ACOES_DE_GESTAO


def test_administrador_da_empresa_tem_as_acoes_de_gestao_nela_e_nas_fazendas(cenario, fabrica_pessoa, conceder_direto):
    admin = fabrica_pessoa('Admin da X')
    conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    assert ACOES_DE_GESTAO <= permissoes_efetivas(admin, cenario.x)
    assert ACOES_DE_GESTAO <= permissoes_efetivas(admin, cenario.f1)


def test_fora_do_escopo_o_conjunto_e_vazio(cenario, fabrica_pessoa, conceder_direto):
    admin = fabrica_pessoa('Admin da X')
    conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    assert permissoes_efetivas(admin, cenario.y) == frozenset()
    assert permissoes_efetivas(admin, cenario.fy) == frozenset()
    assert permissoes_efetivas(admin, None) == frozenset()


def test_pessoa_sem_concessao_nao_tem_acao_alguma(cenario, fabrica_pessoa):
    assert permissoes_efetivas(fabrica_pessoa('Sem Nada'), cenario.f1) == frozenset()


def test_plataforma_tem_todo_o_catalogo(cenario, plataforma):
    assert 'criar_empresa' in permissoes_efetivas(plataforma, None)
    assert ACOES_DE_GESTAO <= permissoes_efetivas(plataforma, cenario.fy)


def test_concordancia_com_pode_em_cada_acao(cenario, fabrica_pessoa, conceder_direto):
    pessoa = fabrica_pessoa('Curadora')
    conceder_direto(pessoa, cenario.cargos_x['curador'], cenario.f1)
    efetivas = permissoes_efetivas(pessoa, cenario.f1)
    assert efetivas  # sem isto a comparação abaixo passaria vazia
    # Conjunto completo, não só os presentes: omissão também reprova (Sourcery, PR #18).
    assert efetivas == {codigo for codigo in Permissao.objects.values_list('codigo', flat=True) if pode(pessoa, codigo, cenario.f1)}
    assert not pode(pessoa, 'criar_empresa', cenario.f1)
    assert 'criar_empresa' not in efetivas


def test_administrador_com_cargo_sem_delegacao_ainda_exerce_delegacao_e_gerencia_de_cargo(cenario, fabrica_pessoa, conceder_direto):
    # Qodo, PR #18: delegação e `gerenciar_cargo` valem pelo nível do Administrador (D043), não pela lista do cargo.
    cargo = Cargo.objects.create(empresa=cenario.x, nome='Admin enxuto', base='administrador')
    CargoPermissao.objects.create(cargo=cargo, permissao_id='ver')
    admin = fabrica_pessoa('Admin enxuto')
    conceder_direto(admin, cargo, cenario.x)
    efetivas = permissoes_efetivas(admin, cenario.x)
    assert {'convidar_pessoa', 'revogar_acesso', 'gerenciar_cargo'} <= efetivas
    assert permissoes_efetivas(admin, cenario.y) == frozenset()


def test_usuario_nao_ganha_delegacao_nem_gerencia_de_cargo(cenario, fabrica_pessoa, conceder_direto):
    usuario = fabrica_pessoa('Usuario')
    conceder_direto(usuario, cenario.cargos_x['usuario'], cenario.x)
    assert not permissoes_efetivas(usuario, cenario.x) & {'convidar_pessoa', 'revogar_acesso', 'gerenciar_cargo'}


def test_redefinir_senha_so_aparece_para_o_administrador_da_empresa(cenario, fabrica_pessoa, conceder_direto):
    # Sourcery, PR #18: a rota recusa quem não é Administrador, ainda que o cargo personalizado traga a ação.
    cargo = Cargo.objects.create(empresa=cenario.x, nome='Curador com redefinição', base='curador')
    for codigo in ('ver', 'redefinir_senha'):
        CargoPermissao.objects.create(cargo=cargo, permissao_id=codigo)
    curador, admin = fabrica_pessoa('Curador'), fabrica_pessoa('Admin da X')
    conceder_direto(curador, cargo, cenario.x)
    conceder_direto(admin, cenario.cargos_x['administrador'], cenario.x)
    assert pode(curador, 'redefinir_senha', cenario.x)
    assert 'redefinir_senha' not in permissoes_efetivas(curador, cenario.x)
    assert 'redefinir_senha' in permissoes_efetivas(admin, cenario.x)


def test_administrador_so_de_fazenda_nao_gerencia_cargo_mas_convida(cenario, fabrica_pessoa, conceder_direto):
    # Greptile, PR #18: cargo é da empresa; a rota exige vínculo na empresa inteira.
    cargo = Cargo.objects.create(empresa=cenario.x, nome='Admin de fazenda enxuto', base='administrador')
    CargoPermissao.objects.create(cargo=cargo, permissao_id='ver')
    admin = fabrica_pessoa('Admin da F1')
    conceder_direto(admin, cargo, cenario.f1)
    efetivas = permissoes_efetivas(admin, cenario.f1)
    assert 'convidar_pessoa' in efetivas
    assert 'gerenciar_cargo' not in efetivas
