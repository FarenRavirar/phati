"""Página da fazenda (R11): nome, empresa e árvore de sub-áreas em leitura. Sem criar nem editar (003)."""

from django.views.decorators.http import require_GET

from projeto.escopo import resolver_escopo
from projeto.paginas_autenticadas import exige_acao, exige_entrada, renderizar_na_casca
from territorio.listagem import sub_areas_da_fazenda


def _arvore(sub_areas):
    """Aninha pela `pai`; sub-área cujo pai não veio na lista (acesso só a uma sub-área) é raiz."""
    nos = {s.pk: {'nome': s.nome, 'filhos': []} for s in sub_areas}
    raizes = []
    for s in sub_areas:  # ordenadas por nível, então o pai já existe em `nos` quando vem
        (nos[s.pai_id]['filhos'] if s.pai_id in nos else raizes).append(nos[s.pk])
    return raizes


@require_GET
@exige_entrada
@exige_acao('ver')
def fazenda(requisicao, empresa_id, fazenda_id):
    empresa, escopo = resolver_escopo(requisicao.user, empresa_id, fazenda_id)
    arvore = _arvore(sub_areas_da_fazenda(requisicao.user, escopo))
    return renderizar_na_casca(requisicao, 'fazenda.html', {'arvore': arvore}, empresa=empresa, fazenda=escopo)
