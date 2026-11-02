"""A9 (R11): para cada par (cargo-base, ação do catálogo) a matriz afirma permitido ou negado, por escopo.

As expectativas são escritas à mão aqui (nunca lidas de `cargo_permissao` nem de `COMPOSICAO`); o catálogo só
confere a lista de ações. A parte de URL direta fecha na Fase 5, quando a API existe.
"""

import pytest

from permissao.models import Permissao
from permissao.pode import pode

pytestmark = pytest.mark.django_db

ACOES = [
    'ver', 'baixar_pacote_offline', 'baixar_documento', 'criar_registro_campo', 'propor_alteracao_atributo',
    'revisar_trabalho_de_outro', 'validar_registro', 'validar_atributo', 'conferir_revisao_enviada',
    'enviar_revisao_camada', 'aprovar_atributo', 'aprovar_geometria', 'tornar_revisao_vigente', 'publicar_camada',
    'subir_documento', 'definir_validade_documento', 'convidar_pessoa', 'revogar_acesso', 'redefinir_senha',
    'configurar_prazos_escalada', 'configurar_categorias_campos', 'configurar_niveis_divisao',
    'ajustar_expiracao_pacote', 'criar_empresa', 'criar_fazenda', 'criar_sub_area', 'gerenciar_cargo',
    'renomear', 'arquivar', 'desarquivar',
]  # fmt: skip
BASES = ['administrador', 'curador', 'tecnico', 'usuario']
_LEITURA = {'ver', 'baixar_pacote_offline'}
_TECNICO = _LEITURA | {'baixar_documento', 'criar_registro_campo', 'propor_alteracao_atributo', 'revisar_trabalho_de_outro'}
PERMITIDAS = {
    'administrador': set(ACOES) - {'criar_empresa'},
    'curador': _TECNICO | {
        'validar_registro', 'validar_atributo', 'conferir_revisao_enviada', 'aprovar_atributo', 'subir_documento',
        'definir_validade_documento', 'convidar_pessoa', 'revogar_acesso',
    },
    'tecnico': _TECNICO,
    'usuario': _LEITURA,
}  # fmt: skip


def test_a_lista_da_matriz_e_o_catalogo():
    assert set(Permissao.objects.values_list('codigo', flat=True)) == set(ACOES)
    assert len(ACOES) == 30


@pytest.mark.parametrize('acao', ACOES)
@pytest.mark.parametrize('base', BASES)
def test_matriz_por_cargo_base_acao_e_escopo(base, acao, cenario, fabrica_pessoa, conceder_direto):
    esperado = acao in PERMITIDAS[base]
    cargo = cenario.cargos_x[base]
    na_fazenda = fabrica_pessoa('Na Fazenda')
    na_sub_area = fabrica_pessoa('Na Sub Area')
    na_empresa = fabrica_pessoa('Na Empresa')
    conceder_direto(na_fazenda, cargo, cenario.f1)
    conceder_direto(na_sub_area, cargo, cenario.g1)
    conceder_direto(na_empresa, cargo, cenario.x)

    # Dentro do escopo: o resultado é o da tabela.
    assert pode(na_fazenda, acao, cenario.f1) is esperado
    assert pode(na_fazenda, acao, cenario.t1) is esperado
    assert pode(na_sub_area, acao, cenario.g1) is esperado
    assert pode(na_sub_area, acao, cenario.t1) is esperado
    assert pode(na_empresa, acao, cenario.x) is esperado
    assert pode(na_empresa, acao, cenario.f2) is esperado
    assert pode(na_empresa, acao, cenario.t1) is esperado
    # Fora do escopo: sempre negado, qualquer que seja o cargo.
    assert pode(na_fazenda, acao, cenario.f2) is False
    assert pode(na_fazenda, acao, cenario.x) is False
    assert pode(na_fazenda, acao, cenario.fy) is False
    assert pode(na_sub_area, acao, cenario.g2) is False
    assert pode(na_sub_area, acao, cenario.f1) is False
    assert pode(na_empresa, acao, cenario.y) is False
    assert pode(na_empresa, acao, cenario.fy) is False


@pytest.mark.parametrize('acao', ACOES)
def test_sem_concessao_todo_acesso_e_negado(acao, cenario, fabrica_pessoa):
    sem_nada = fabrica_pessoa('Sem Nada')
    assert pode(sem_nada, acao, cenario.f1) is False
    assert pode(sem_nada, acao, cenario.x) is False
