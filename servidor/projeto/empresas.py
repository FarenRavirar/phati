"""Seletor de fazenda (R10): fazendas autorizadas agrupadas por empresa, com busca no cliente. Empresa e fazenda fora
do escopo não entram na resposta (R3, D063): a lista vem das mesmas listagens que decidem o 404 do endereço.
Também oferece as ações de gestão da 003 (R9, R11) a quem a permissão efetiva permite."""

from itertools import groupby

from django.urls import reverse
from django.views.decorators.http import require_GET

from permissao.pode import permissoes_efetivas
from projeto.escopo import resolver_escopo
from projeto.paginas_autenticadas import exige_acao, exige_entrada, renderizar_na_casca
from projeto.territorio_paginas import acoes_do_alvo
from territorio.listagem import empresas_autorizadas, fazendas_autorizadas


def _grupos(empresas, fazendas):
    """Uma entrada por empresa, nas empresas dadas, com as fazendas dela; empresa sem fazenda alcançada some."""
    por_empresa = {empresa_id: list(grupo) for empresa_id, grupo in groupby(
        sorted(fazendas, key=lambda f: f.empresa_id), key=lambda f: f.empresa_id)}
    return [(empresa, por_empresa[empresa.pk]) for empresa in empresas if empresa.pk in por_empresa]


@require_GET
@exige_entrada
@exige_acao('ver')
def empresas(requisicao):
    grupos = _grupos(empresas_autorizadas(requisicao.user), fazendas_autorizadas(requisicao.user))
    acoes = []
    if 'criar_empresa' in permissoes_efetivas(requisicao.user):
        acoes.append({'rotulo': 'Cadastrar empresa', 'destino': reverse('empresa_nova')})
    if empresas_autorizadas(requisicao.user, arquivadas=True) or fazendas_autorizadas(requisicao.user, arquivadas=True):
        acoes.append({'rotulo': 'Arquivadas', 'destino': reverse('arquivadas')})
    return renderizar_na_casca(requisicao, 'empresas.html', {'grupos': grupos, 'acoes': acoes})


@require_GET
@exige_entrada
@exige_acao('ver')
def empresa(requisicao, empresa_id):
    escopo, _ = resolver_escopo(requisicao.user, empresa_id)
    # Empresa arquivada continua consultável por inteiro (R11): as fazendas dela, arquivadas pelo mesmo ato, aparecem.
    fazendas = fazendas_autorizadas(requisicao.user, empresa_id=escopo.pk, arquivadas=None if escopo.arquivada_em else False)
    acoes = acoes_do_alvo(escopo, permissoes_efetivas(requisicao.user, escopo))
    contexto = {'grupos': [(escopo, fazendas)] if fazendas else [], 'acoes': acoes, 'empresa_arquivada': escopo.arquivada_em is not None}
    return renderizar_na_casca(requisicao, 'empresas.html', contexto, empresa=escopo)
