"""Páginas da fazenda e da sub-área (R11, 003 R5, R6, R9, R11): nome, empresa e árvore de sub-áreas, as ações de gestão
que a permissão efetiva da pessoa permite e a seção das sub-áreas arquivadas. Todo nó da árvore leva à página da
sub-área, que existe para quem lê; o que cada pessoa pode fazer ali vem de `permissoes_efetivas`."""

from django.urls import reverse
from django.views.decorators.http import require_GET

from permissao.pode import com_permissao, permissoes_efetivas, pode
from projeto.escopo import resolver_escopo
from projeto.paginas_autenticadas import exige_acao, exige_entrada, renderizar_na_casca
from projeto.territorio_paginas import acoes_do_alvo, resolver_sub_area
from territorio.listagem import sub_areas_da_fazenda
from territorio.models import SubArea
from territorio.niveis import nome_do_nivel


def _arvore(sub_areas, destino_de):
    """Aninha pela `pai`; sub-área cujo pai não veio na lista (acesso só a uma sub-área) é raiz. Cada nó é link para a
    página da sub-área (R5)."""
    nos = {s.pk: {'nome': s.nome, 'filhos': [], 'destino': destino_de(s)} for s in sub_areas}
    raizes = []
    for s in sub_areas:  # ordenadas por nível, então o pai já existe em `nos` quando vem
        (nos[s.pai_id]['filhos'] if s.pai_id in nos else raizes).append(nos[s.pk])
    return raizes


def _destino_da_sub_area(empresa, fazenda, nome_da_url):
    return lambda s: reverse(nome_da_url, kwargs={'empresa_id': empresa.pk, 'fazenda_id': fazenda.pk, 'sub_area_id': s.pk})


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
        _destino_da_sub_area(empresa, escopo, 'sub_area'),
    )
    consultar = _destino_da_sub_area(empresa, escopo, 'sub_area')
    desarquivar = _destino_da_sub_area(empresa, escopo, 'sub_area_desarquivar')
    arquivadas_da_fazenda = [] if arquivada else sub_areas_da_fazenda(requisicao.user, escopo, arquivadas=True)
    ids_arquivados = {s.pk for s in arquivadas_da_fazenda}
    # Restaurar só vale quando o pai não segue arquivado (`ancestral_arquivado`): sem botão que falha.
    arquivadas = [
        {'nome': s.nome, 'consulta': consultar(s), 'destino': desarquivar(s) if s.pai_id not in ids_arquivados and pode(requisicao.user, 'desarquivar', s) else None}
        for s in arquivadas_da_fazenda
    ]
    cadastrar = next((a for a in acoes if a['rotulo'] == 'Cadastrar sub-área'), None)
    contexto = {'arvore': arvore, 'acoes': acoes, 'arquivadas': arquivadas, 'cadastrar': cadastrar}
    return renderizar_na_casca(requisicao, 'fazenda.html', contexto, empresa=empresa, fazenda=escopo)


@require_GET
@exige_entrada
@exige_acao('ver')
def sub_area(requisicao, empresa_id, fazenda_id, sub_area_id):
    """Página da sub-área: nível, o que há dentro dela e as ações que a permissão efetiva da pessoa permite nela."""
    empresa, fazenda_do_endereco, alvo = resolver_sub_area(requisicao, empresa_id, fazenda_id, sub_area_id)
    assert fazenda_do_endereco is not None
    assert isinstance(alvo, SubArea)  # a URL traz os dois ids: `resolver_sub_area` devolve a sub-área ou levanta 404
    efetivas = permissoes_efetivas(requisicao.user, alvo)
    dentro = [
        s for s in sub_areas_da_fazenda(requisicao.user, fazenda_do_endereco, arquivadas=None) if f'/{alvo.pk}/' in s.caminho
    ]
    with com_permissao(requisicao.user, 'ver'):
        nivel = nome_do_nivel(empresa, alvo.nivel)
    contexto = {
        'sub_area': alvo, 'nivel': nivel, 'acoes': acoes_do_alvo(alvo, efetivas),
        'arvore': _arvore(dentro, _destino_da_sub_area(empresa, fazenda_do_endereco, 'sub_area')),
    }
    return renderizar_na_casca(requisicao, 'sub_area.html', contexto, empresa=empresa, fazenda=fazenda_do_endereco)
