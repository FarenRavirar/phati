"""Menu lateral (R2): tabela de itens e filtro pela permissão efetiva do servidor, a cada requisição.

Esconder o item não protege a rota: ela responde 404 a quem não pode (R3). A 003 acrescenta itens a `ITENS`.
"""

from dataclasses import dataclass, replace

from permissao.pode import age_em_algum_escopo, permissoes_efetivas
from projeto.painel import ACOES_DE_GESTAO


@dataclass(frozen=True)
class ItemDoMenu:
    nome: str
    caminho: str
    acoes: tuple[str, ...] = ()  # sem ação, o item é de toda pessoa autenticada
    em_algum_escopo: bool = False  # vale a ação em qualquer lugar, não só no escopo atual
    prefixos: tuple[str, ...] = ()  # páginas filhas que também marcam o item como atual
    atual: str = ''  # `aria-current` do link: 'page' na própria página, 'true' numa página filha; vazio fora disso


ITENS = (
    ItemDoMenu('Início', '/'),
    ItemDoMenu('Fazendas', '/empresas/', prefixos=('/empresa/',)),
    # Ponte provisória (R24): a mesma condição de `PainelSite.has_permission`. A 003 a remove com `site_url` do painel.
    ItemDoMenu('Gestão ↗', '/painel/', ACOES_DE_GESTAO, em_algum_escopo=True),
)


@dataclass(frozen=True)
class Atalho:
    nome: str
    caminho: str
    acao: str  # ação do catálogo que a pessoa precisa ter em algum escopo; nunca o nome do papel (R7)


# Atalhos fixos do Início, na ordem provisória da D081 (a confirmar com a Tatiane). Cada fase de gestão acrescenta a linha
# da própria tela, para o atalho nunca apontar a uma rota que não existe.
ATALHOS: tuple[Atalho, ...] = ()


def atalhos_do_inicio(pessoa):
    return [atalho for atalho in ATALHOS if age_em_algum_escopo(pessoa, atalho.acao)]


def itens_do_menu(pessoa, escopo=None, caminho=None):
    efetivas = permissoes_efetivas(pessoa, escopo)
    return [replace(item, atual=_atual(item, caminho)) for item in ITENS if _visivel(item, pessoa, efetivas)]


def _atual(item, caminho):
    if caminho == item.caminho:
        return 'page'
    # `startswith(())` é falso: item sem páginas filhas nunca cai aqui.
    return 'true' if caminho is not None and caminho.startswith(item.prefixos) else ''


def _visivel(item, pessoa, efetivas):
    if not item.acoes:
        return True
    if item.em_algum_escopo:
        return age_em_algum_escopo(pessoa, *item.acoes)
    return bool(efetivas & set(item.acoes))
