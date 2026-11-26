"""Filtros dos componentes de `templates/componentes/` (spec 012, R14).

Os componentes são includes, não tags: estes filtros só validam variante e mapeiam a situação do Selo, sem
`if` em cascata repetido em cada template. Registrados em `TEMPLATES[...]['OPTIONS']['builtins']` (settings.py).
"""

from django import template

register = template.Library()

# Mesmo mapeamento de `SITUACOES` em COMPONENTES.md / feedback/Selo.jsx: situação -> (tom, texto).
SITUACOES_DO_SELO = {
    'vigente': ('sucesso', 'Vigente'),
    'em_analise': ('aviso', 'Em análise'),
    'recusada': ('erro', 'Recusada'),
    'arquivada': ('neutro', 'Arquivada'),
    'pendente': ('info', 'Pendente'),
    'ativo': ('sucesso', 'Ativo'),
    'convidado': ('info', 'Convidado'),
}
# Limite de linhas do Esqueleto: sem teto, um `linhas` absurdo geraria HTML sem fim. Shortcut: 20 linhas, subir se uma tela precisar mais.
LINHAS_DO_ESQUELETO_MAX = 20


@register.filter
def dentre(valor, opcoes):
    """`valor` se estiver na lista `opcoes` (palavras separadas por espaço); senão `''`. Use com `|default:` para o padrão."""
    if not isinstance(valor, str):
        return ''
    return valor if valor in opcoes.split() else ''


@register.filter
def selo_tom(situacao):
    """Tom da situação do Selo, ou `''` quando a situação não é conhecida (o Selo cai no `tom` informado)."""
    if not isinstance(situacao, str):
        return ''
    return SITUACOES_DO_SELO.get(situacao, ('',))[0]


@register.filter
def selo_rotulo(situacao):
    """Texto da situação do Selo, ou `''` quando a situação não é conhecida."""
    if not isinstance(situacao, str):
        return ''
    return SITUACOES_DO_SELO.get(situacao, ('', ''))[1]


@register.filter
def repetir(quantidade):
    """`range` de `quantidade` posições para o `for` do template. Valor que não é inteiro entre 1 e o máximo vira vazio."""
    if type(quantidade) is not int or not 1 <= quantidade <= LINHAS_DO_ESQUELETO_MAX:
        return range(0)
    return range(quantidade)


@register.filter
def iniciais(nome):
    """Iniciais das duas primeiras palavras de `nome`, em maiúsculas; `''` quando o valor não é texto ou está vazio."""
    if not isinstance(nome, str):
        return ''
    return ''.join(palavra[0] for palavra in nome.split()[:2]).upper()


@register.filter
def na_posicao(valores, posicao):
    """Item `posicao` de `valores` (lista de destinos paralela às linhas); `''` quando não há lista ou o item falta."""
    if not isinstance(valores, (list, tuple)) or type(posicao) is not int or not 0 <= posicao < len(valores):
        return ''
    return valores[posicao]
