"""Os quatro cargos-base de cada empresa, criados com ela (R8; plan.md §Catálogo de ações e cargos-base).

Valor inicial escolhido pelo agente; o mantenedor ajusta. Cargo é personalizável depois de criado. Ação nova
no catálogo (migração, risco R-7) entra nos cargos já criados por essa mesma migração.
"""

from permissao.models import Cargo, CargoPermissao, Permissao
from permissao.pode import ACOES_DA_PLATAFORMA

NOMES = {'administrador': 'Administrador', 'curador': 'Curador', 'tecnico': 'Técnico', 'usuario': 'Usuário'}

_LEITURA = ('ver', 'baixar_pacote_offline')
_TECNICO = (*_LEITURA, 'baixar_documento', 'criar_registro_campo', 'propor_alteracao_atributo', 'revisar_trabalho_de_outro')
# O Administrador leva todas as ações menos as da plataforma; não está aqui porque acompanha o catálogo.
COMPOSICAO = {
    'curador': (
        *_TECNICO,
        'validar_registro',
        'validar_atributo',
        'conferir_revisao_enviada',
        'aprovar_atributo',
        'subir_documento',
        'definir_validade_documento',
        'convidar_pessoa',
        'revogar_acesso',
    ),
    'tecnico': _TECNICO,
    'usuario': _LEITURA,
}


def criar_cargos_base(empresa):
    """Cria os quatro cargos da empresa e devolve `{base: Cargo}`. Chamar dentro da transação de quem cria a empresa."""
    cargos = {}
    for base, nome in NOMES.items():
        cargo = Cargo.objects.create(empresa=empresa, nome=nome, base=base)
        if base == 'administrador':
            codigos = Permissao.objects.exclude(codigo__in=ACOES_DA_PLATAFORMA).values_list('codigo', flat=True)
        else:
            codigos = COMPOSICAO[base]
        CargoPermissao.objects.bulk_create(CargoPermissao(cargo=cargo, permissao_id=codigo) for codigo in codigos)
        cargos[base] = cargo
    return cargos
