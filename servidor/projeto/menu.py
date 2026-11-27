"""Menu lateral (R15, R16): tabela de itens, filtro pela permissão efetiva do servidor a cada requisição e a página atual.

Esconder o item não protege a rota: ela responde 404 ou 403 a quem não pode (R3). Cada item decide com a mesma checagem
da view dele (`alcance_na_empresa`, `age_na_plataforma_ou_em_empresa`, `permissoes_efetivas`). A 003 acrescenta itens a `ITENS`.
"""

from dataclasses import dataclass, replace

from permissao.pode import administrador_da_empresa, age_em_algum_escopo, age_na_plataforma_ou_em_empresa, escopos_da_acao, permissoes_efetivas
from permissao.uso import usos_da_pessoa
from projeto.escopo import alcance_na_empresa
from projeto.painel import ACOES_DE_PESSOAS
from territorio.listagem import empresas_autorizadas

CAMINHO_PESSOAS = '/empresa/{empresa_id}/pessoas/'
CAMINHO_CARGOS = '/empresa/{empresa_id}/cargos/'
GRUPO_GESTAO = 'Gestão'


@dataclass(frozen=True)
class ItemDoMenu:
    nome: str
    caminho: str  # com `{empresa_id}`, o item é de uma empresa e só aparece com a empresa escolhida (ou a da URL)
    icone: str = ''  # nome do ícone Lucide, pela tag `icone`
    grupo: str = ''  # título do grupo ('' sem título; 'Gestão' para as telas de gestão)
    acoes: tuple[str, ...] = ()  # sem ação, o item é de toda pessoa autenticada
    prefixos: tuple[str, ...] = ()  # caminhos das páginas filhas; a correspondência mais longa vence (um só item atual)
    atual: str = ''  # `aria-current` do link: 'page' na própria página, 'true' numa página filha; vazio fora disso
    # Com `em_empresa`, `acoes` vale na plataforma ou em alguma empresa inteira, não só na plataforma (005 Q1: o Administrador de
    # empresa lê a auditoria). `permissoes_efetivas(pessoa, None)` dá ação só à plataforma, por isso o item usa o helper.
    em_empresa: bool = False
    # 'alcance': alguma ação no alcance da empresa, como a tela de pessoas; 'inteira': só com a empresa inteira, como cargos (003 R18).
    na_empresa: str = ''
    contador: int = 0  # zero não aparece (telas.md §0); nenhum item tem fonte de contagem nesta fase


ITENS = (
    ItemDoMenu('Início', '/', icone='house'),
    ItemDoMenu('Fazendas', '/empresas/', icone='map', prefixos=('/empresa/', '/fazendas/')),
    ItemDoMenu(
        'Pessoas', CAMINHO_PESSOAS, icone='users', grupo=GRUPO_GESTAO, acoes=ACOES_DE_PESSOAS, na_empresa='alcance',
        prefixos=(CAMINHO_PESSOAS, '/empresa/{empresa_id}/pessoa/', '/empresa/{empresa_id}/titularidade'),
    ),
    ItemDoMenu(
        'Cargos', CAMINHO_CARGOS, icone='shield', grupo=GRUPO_GESTAO, acoes=('gerenciar_cargo',), na_empresa='inteira',
        prefixos=(CAMINHO_CARGOS,),
    ),
    ItemDoMenu('Auditoria', '/auditoria/', icone='scroll-text', grupo=GRUPO_GESTAO, acoes=('ver_auditoria',), em_empresa=True),  # 005 R6: a plataforma e o Administrador de empresa
    ItemDoMenu('Uso do Google', '/monitor-google', icone='gauge', grupo=GRUPO_GESTAO, acoes=('ver_monitor_google',)),  # só o Administrador da plataforma (004b R13)
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
    Atalho('Cargos', CAMINHO_CARGOS, 'gerenciar_cargo', fixo=False, empresa_inteira=True),
    # Redefinir é por pessoa: o atalho abre a lista de pessoas, onde cada linha leva à confirmação (A16).
    Atalho('Redefinir senha', CAMINHO_PESSOAS, 'redefinir_senha', fixo=False, so_administrador=True),
    Atalho('Cadastrar fazenda', '/empresa/{empresa_id}/fazenda/nova', 'criar_fazenda', fixo=False, empresa_inteira=True),
)
ACOES_DE_ATALHO = frozenset(atalho.acao for atalho in ATALHOS)
LIMITE_POR_FREQUENCIA = 2  # R27 e A16


def _por_empresa(pessoa, atalho, empresa=None):
    """Um link para cada empresa em que a pessoa tem a ação, no alcance que o destino exige; com `empresa`, só a dela."""
    escopos = escopos_da_acao(pessoa, atalho.acao)
    lugares = escopos.empresas if atalho.empresa_inteira else escopos.empresas | escopos.empresas_das_fazendas
    alcancadas = [e for e in empresas_autorizadas(pessoa) if e.pk in lugares and (empresa is None or e.pk == empresa.pk)]
    if atalho.so_administrador:
        alcancadas = [e for e in alcancadas if administrador_da_empresa(pessoa, e.pk)]
    return [
        replace(atalho, nome=atalho.nome if len(alcancadas) == 1 else f'{atalho.nome} · {e.nome}', caminho=atalho.caminho.format(empresa_id=e.pk))
        for e in alcancadas
    ]


def atalhos_do_inicio(pessoa, empresa=None):
    atalhos = []
    for atalho in ATALHOS:
        if '{empresa_id}' in atalho.caminho:
            # O Administrador da plataforma escolhe a empresa pela lista do Início: um atalho por empresa seria uma parede.
            if not pessoa.administrador_plataforma:
                atalhos.extend(_por_empresa(pessoa, atalho, empresa))
        elif age_em_algum_escopo(pessoa, atalho.acao):
            atalhos.append(atalho)
    return atalhos


def atalhos_da_pessoa(pessoa, empresa=None):
    """Atalhos do Início (R27): fixos do papel, os que a pessoa fixou e até `LIMITE_POR_FREQUENCIA` por frequência, só os que a
    permissão atual ainda dá e que a pessoa não ocultou. Devolve `(mostrados, ocultos, disponiveis)`; os dois últimos são
    `[(acao, nome)]`: `ocultos` para o botão Mostrar e `disponiveis` (permitidos, fora do Início) para o botão Fixar. Ação por empresa gera um link por empresa e conta como um atalho no limite.
    `empresa` (a escolhida no seletor) restringe os atalhos por empresa à dela."""
    permitidos = atalhos_do_inicio(pessoa, empresa)
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


def itens_do_menu(pessoa, escopo=None, caminho=None, empresa=None):
    """`escopo` decide as ações de plataforma e de empresa; `empresa` (a escolhida ou a da URL) abre Pessoas e Cargos."""
    efetivas = permissoes_efetivas(pessoa, escopo)
    visiveis = [_no_escopo(item, empresa) for item in ITENS if _visivel(item, pessoa, efetivas, empresa)]
    atuais = _atuais(visiveis, caminho)
    return [replace(item, atual=atuais.get(item.nome, '')) for item in visiveis]


def trilha_da(itens, empresa=None, fazenda=None, sub_area=None, etapa=''):
    """Trilha do topo (telas.md §0): grupo e página. Em Fazendas: empresa ou fazenda, depois sub-área ou a etapa do envio
    ("Enviar camada"); sub-área e etapa só valem com a fazenda aberta."""
    atual = next((item for item in itens if item.atual), None)
    if atual is None:
        return []
    if atual.nome == 'Fazendas':
        lugar = fazenda or empresa
        trilha = ['Fazendas', lugar.nome] if lugar else ['Fazendas']
        if fazenda and sub_area:
            trilha.append(sub_area.nome)
        if fazenda and etapa:
            trilha.append(etapa)
        return trilha
    return [atual.grupo, atual.nome] if atual.grupo else [atual.nome]


def _no_escopo(item, empresa):
    if empresa is None:
        return item
    return replace(item, caminho=item.caminho.format(empresa_id=empresa.pk), prefixos=tuple(p.format(empresa_id=empresa.pk) for p in item.prefixos))


def _atuais(itens, caminho):
    """Um item só é o atual: o de correspondência mais longa, para `/empresa/1/pessoas/` marcar Pessoas e não Fazendas."""
    if caminho is None:
        return {}
    casos = []
    for item in itens:
        if caminho == item.caminho:
            casos.append((len(item.caminho), item.nome, 'page'))
        elif any(caminho.startswith(prefixo) for prefixo in item.prefixos):
            casos.append((max(len(p) for p in item.prefixos if caminho.startswith(p)), item.nome, 'true'))
    if not casos:
        return {}
    _, nome, marca = max(casos, key=lambda caso: caso[0])
    return {nome: marca}


def _visivel(item, pessoa, efetivas, empresa):
    if item.na_empresa:
        return empresa is not None and alcance_na_empresa(pessoa, empresa, item.acoes, inteira=item.na_empresa == 'inteira')
    if not item.acoes:
        return True
    if item.em_empresa:
        return age_na_plataforma_ou_em_empresa(pessoa, *item.acoes)
    return bool(efetivas & set(item.acoes))
