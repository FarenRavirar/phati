"""Página da fazenda (R11, 003 R5, R6, R9, R11): nome, empresa e árvore de sub-áreas, as ações de gestão que a permissão
efetiva da pessoa permite e a seção das sub-áreas arquivadas."""

from django.urls import reverse
from django.views.decorators.http import require_GET

from permissao.pode import permissoes_efetivas, pode
from projeto.escopo import resolver_escopo
from projeto.paginas_autenticadas import exige_acao, exige_entrada, renderizar_na_casca
from projeto.territorio_paginas import acoes_do_alvo
from territorio.listagem import sub_areas_da_fazenda


def _arvore(sub_areas, destino_de=None):
    """Aninha pela `pai`; sub-área cujo pai não veio na lista (acesso só a uma sub-área) é raiz. Com `destino_de`, cada nó
    vira link para a página dele (R5); sem ele, texto."""
    nos = {s.pk: {'nome': s.nome, 'filhos': [], 'destino': destino_de(s) if destino_de else None} for s in sub_areas}
    raizes = []
    for s in sub_areas:  # ordenadas por nível, então o pai já existe em `nos` quando vem
        (nos[s.pai_id]['filhos'] if s.pai_id in nos else raizes).append(nos[s.pk])
    return raizes


def _destino_da_sub_area(empresa, fazenda, nome_da_url):
    return lambda s: reverse(nome_da_url, kwargs={'empresa_id': empresa.pk, 'fazenda_id': fazenda.pk, 'sub_area_id': s.pk})


def _destino_se_pode_renomear(pessoa, empresa, fazenda):
    """Link do nó só para quem pode renomear *aquela* sub-área (Administrador só de sub-área inclusive). Fazenda
    arquivada não liga; nas outras, a lista traz só sub-áreas ativas, então o arquivamento não se consulta de novo."""
    if fazenda.arquivada_em is not None:
        return None
    destino = _destino_da_sub_area(empresa, fazenda, 'sub_area_editar')
    return lambda s: destino(s) if pode(pessoa, 'renomear', s, arquivado=False) else None


@require_GET
@exige_entrada
@exige_acao('ver')
def fazenda(requisicao, empresa_id, fazenda_id):
    empresa, escopo = resolver_escopo(requisicao.user, empresa_id, fazenda_id)
    assert escopo is not None  # a URL traz o id da fazenda: `resolver_escopo` devolve a fazenda ou levanta 404
    efetivas = permissoes_efetivas(requisicao.user, escopo)
    acoes = acoes_do_alvo(escopo, efetivas)
    # Fazenda arquivada continua consultável por inteiro (R11): a árvore mostra tudo e não há seção separada.
    arquivada = escopo.arquivada_em is not None
    arvore = _arvore(
        sub_areas_da_fazenda(requisicao.user, escopo, arquivadas=None if arquivada else False),
        _destino_se_pode_renomear(requisicao.user, empresa, escopo),
    )
    desarquivar = _destino_da_sub_area(empresa, escopo, 'sub_area_desarquivar')
    arquivadas = [
        {'nome': s.nome, 'destino': desarquivar(s) if 'desarquivar' in efetivas else None}
        for s in ([] if arquivada else sub_areas_da_fazenda(requisicao.user, escopo, arquivadas=True))
    ]
    cadastrar = next((a for a in acoes if a['rotulo'] == 'Cadastrar sub-área'), None)
    contexto = {'arvore': arvore, 'acoes': acoes, 'arquivadas': arquivadas, 'cadastrar': cadastrar}
    return renderizar_na_casca(requisicao, 'fazenda.html', contexto, empresa=empresa, fazenda=escopo)
