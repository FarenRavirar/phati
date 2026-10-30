"""R2, R12, A10: `permissoes_efetivas` diz o que a pessoa exerce em um escopo, sem regra própria."""

import pytest

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
    assert efetivas  # sem isto o laço abaixo passaria vazio
    for acao in efetivas:
        assert pode(pessoa, acao, cenario.f1)
    assert not pode(pessoa, 'criar_empresa', cenario.f1)
    assert 'criar_empresa' not in efetivas
