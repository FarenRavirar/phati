"""Menu lateral (R2): tabela de itens e filtro pela permissão efetiva do servidor, a cada requisição.

Esconder o item não protege a rota: ela responde 404 a quem não pode (R3). A 003 acrescenta itens a `ITENS`.
"""

from dataclasses import dataclass, replace

from permissao.pode import administrador_da_empresa, age_em_algum_escopo, escopos_da_acao, permissoes_efetivas
from permissao.uso import usos_da_pessoa
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
    ItemDoMenu('Uso do Google', '/monitor-google', acoes=('ver_monitor_google',)),  # só o Administrador da plataforma (004b R13)
)


@dataclass(frozen=True)
class Atalho:
    nome: str
    caminho: str  # com `{empresa_id}`, o atalho vale por empresa: um link para cada empresa em que a pessoa tem a ação
    acao: str  # ação do catálogo que a pessoa precisa ter em algum escopo; nunca o nome do papel (R7)
    fixo: bool = True  # fixo do papel (R7) sempre aparece; os demais só entram por frequência ou por Fixar (R27)
    fixado: bool = False  # a pessoa fixou este atalho; preenchido por `atalhos_da_pessoa`
    empresa_inteira: bool = False  # o destino exige a ação na empresa inteira: permissão só de fazenda ou sub-área daria 403
    so_administrador: bool = False  # o destino só age para Administrador da empresa (mesma regra de `pode_iniciar_redefinicao`)


# Atalhos fixos do Início, na ordem provisória da D081 (a confirmar com a Tatiane). Cada fase de gestão acrescenta a linha
# da própria tela, para o atalho nunca apontar a uma rota que não existe.
ATALHOS: tuple[Atalho, ...] = (
    Atalho('Convidar pessoa', '/empresa/{empresa_id}/pessoas/convidar', 'convidar_pessoa'),
    # Candidatos a atalho de frequência (R27): cada um é registrado com `registrar_uso` quando a ação dá certo.
    Atalho('Cargos', '/empresa/{empresa_id}/cargos/', 'gerenciar_cargo', fixo=False, empresa_inteira=True),
    # Redefinir é por pessoa: o atalho abre a lista de pessoas, onde cada linha leva à confirmação (A16).
    Atalho('Redefinir senha', '/empresa/{empresa_id}/pessoas/', 'redefinir_senha', fixo=False, so_administrador=True),
    Atalho('Cadastrar fazenda', '/empresa/{empresa_id}/fazenda/nova', 'criar_fazenda', fixo=False, empresa_inteira=True),
)
ACOES_DE_ATALHO = frozenset(atalho.acao for atalho in ATALHOS)
LIMITE_POR_FREQUENCIA = 2  # R27 e A16


def _por_empresa(pessoa, atalho):
    """Um link para cada empresa em que a pessoa tem a ação, no alcance que o destino exige."""
    escopos = escopos_da_acao(pessoa, atalho.acao)
    lugares = escopos.empresas if atalho.empresa_inteira else escopos.empresas | escopos.empresas_das_fazendas
    alcancadas = [e for e in empresas_autorizadas(pessoa) if e.pk in lugares]
    if atalho.so_administrador:
        alcancadas = [e for e in alcancadas if administrador_da_empresa(pessoa, e.pk)]
    return [
        replace(atalho, nome=atalho.nome if len(alcancadas) == 1 else f'{atalho.nome} · {e.nome}', caminho=atalho.caminho.format(empresa_id=e.pk))
        for e in alcancadas
    ]


def atalhos_do_inicio(pessoa):
    atalhos = []
    for atalho in ATALHOS:
        if '{empresa_id}' in atalho.caminho:
            # O Administrador da plataforma escolhe a empresa pela lista do Início: um atalho por empresa seria uma parede.
            if not pessoa.administrador_plataforma:
                atalhos.extend(_por_empresa(pessoa, atalho))
        elif age_em_algum_escopo(pessoa, atalho.acao):
            atalhos.append(atalho)
    return atalhos


def atalhos_da_pessoa(pessoa):
    """Atalhos do Início (R27): fixos do papel, os que a pessoa fixou e até `LIMITE_POR_FREQUENCIA` por frequência, só os que a
    permissão atual ainda dá e que a pessoa não ocultou. Devolve `(mostrados, ocultos, disponiveis)`; os dois últimos são
    `[(acao, nome)]`: `ocultos` para o botão Mostrar e `disponiveis` (permitidos, fora do Início) para o botão Fixar. Ação por empresa gera um link por empresa e conta como um atalho no limite."""
    permitidos = atalhos_do_inicio(pessoa)
    usos = usos_da_pessoa(pessoa)

    def uso_de(acao, campo, padrao):
        return getattr(usos[acao], campo) if acao in usos else padrao

    ocultas = {a.acao for a in permitidos if uso_de(a.acao, 'oculto', False)}
    visiveis = [a for a in permitidos if a.acao not in ocultas]
    fixos = [a for a in visiveis if a.fixo]
    fixados = [replace(a, fixado=True) for a in visiveis if not a.fixo and uso_de(a.acao, 'fixado', False)]
    ja_mostradas = {a.acao for a in fixos + fixados}
    # Empate total (relógio grosseiro): vale a ordem de `ATALHOS`, porque `sorted` é estável.
    candidatas = dict.fromkeys(a.acao for a in visiveis if a.acao not in ja_mostradas and uso_de(a.acao, 'contagem', 0) > 0)
    ranking = sorted(candidatas, key=lambda acao: (-usos[acao].contagem, -usos[acao].ultimo_uso.timestamp()))
    frequentes = [a for acao in ranking[:LIMITE_POR_FREQUENCIA] for a in visiveis if a.acao == acao]
    nomes = {a.acao: a.nome for a in reversed(ATALHOS)}
    mostrados = fixos + fixados + frequentes
    na_tela = {a.acao for a in mostrados}
    disponiveis = sorted({a.acao for a in visiveis if a.acao not in na_tela})
    return mostrados, [(acao, nomes[acao]) for acao in sorted(ocultas)], [(acao, nomes[acao]) for acao in disponiveis]


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
