"""Menu lateral (R2): tabela de itens e filtro pela permissão efetiva do servidor, a cada requisição.

Esconder o item não protege a rota: ela responde 404 a quem não pode (R3). A 003 acrescenta itens a `ITENS`.
"""

from dataclasses import dataclass

from permissao.pode import age_em_algum_escopo, permissoes_efetivas
from projeto.painel import ACOES_DE_GESTAO


@dataclass(frozen=True)
class ItemDoMenu:
    nome: str
    caminho: str
    acoes: tuple[str, ...] = ()  # sem ação, o item é de toda pessoa autenticada
    em_algum_escopo: bool = False  # vale a ação em qualquer lugar, não só no escopo atual


ITENS = (
    ItemDoMenu('Início', '/'),
    ItemDoMenu('Fazendas', '/empresas/'),
    # Ponte provisória (R24): a mesma condição de `PainelSite.has_permission`. A 003 a remove com `site_url` do painel.
    ItemDoMenu('Gestão ↗', '/painel/', ACOES_DE_GESTAO, em_algum_escopo=True),
)


def itens_do_menu(pessoa, escopo=None):
    efetivas = permissoes_efetivas(pessoa, escopo)
    return [item for item in ITENS if _visivel(item, pessoa, efetivas)]


def _visivel(item, pessoa, efetivas):
    if not item.acoes:
        return True
    if item.em_algum_escopo:
        return age_em_algum_escopo(pessoa, *item.acoes)
    return bool(efetivas & set(item.acoes))
