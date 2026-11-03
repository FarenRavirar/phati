"""Menu lateral (R2): tabela de itens e filtro pela permissão efetiva do servidor, a cada requisição.

Esconder o item não protege a rota: ela responde 404 a quem não pode (R3). A 003 acrescenta itens a `ITENS`.
"""

from dataclasses import dataclass, replace

from permissao.pode import age_em_algum_escopo, escopos_da_acao, permissoes_efetivas
from territorio.listagem import empresas_autorizadas


@dataclass(frozen=True)
class ItemDoMenu:
    nome: str
    caminho: str
    acoes: tuple[str, ...] = ()  # sem ação, o item é de toda pessoa autenticada
    prefixos: tuple[str, ...] = ()  # páginas filhas que também marcam o item como atual
    atual: str = ''  # `aria-current` do link: 'page' na própria página, 'true' numa página filha; vazio fora disso


ITENS = (
    ItemDoMenu('Início', '/'),
    ItemDoMenu('Fazendas', '/empresas/', prefixos=('/empresa/',)),
)


@dataclass(frozen=True)
class Atalho:
    nome: str
    caminho: str  # com `{empresa_id}`, o atalho vale por empresa: um link para cada empresa em que a pessoa tem a ação
    acao: str  # ação do catálogo que a pessoa precisa ter em algum escopo; nunca o nome do papel (R7)


# Atalhos fixos do Início, na ordem provisória da D081 (a confirmar com a Tatiane). Cada fase de gestão acrescenta a linha
# da própria tela, para o atalho nunca apontar a uma rota que não existe.
ATALHOS: tuple[Atalho, ...] = (
    Atalho('Convidar pessoa', '/empresa/{empresa_id}/pessoas/convidar', 'convidar_pessoa'),
)


def atalhos_do_inicio(pessoa):
    atalhos = []
    for atalho in ATALHOS:
        if '{empresa_id}' not in atalho.caminho:
            if age_em_algum_escopo(pessoa, atalho.acao):
                atalhos.append(atalho)
            continue
        # O Administrador da plataforma escolhe a empresa pela lista do Início: um atalho por empresa seria uma parede.
        if pessoa.administrador_plataforma:
            continue
        escopos = escopos_da_acao(pessoa, atalho.acao)
        alcancadas = [e for e in empresas_autorizadas(pessoa) if e.pk in escopos.empresas | escopos.empresas_das_fazendas]
        for empresa in alcancadas:
            nome = atalho.nome if len(alcancadas) == 1 else f'{atalho.nome} · {empresa.nome}'
            atalhos.append(replace(atalho, nome=nome, caminho=atalho.caminho.format(empresa_id=empresa.pk)))
    return atalhos


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
    return bool(efetivas & set(item.acoes))
