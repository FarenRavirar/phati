"""Seletor de fazenda (R10): fazendas autorizadas agrupadas por empresa, com busca no cliente. Empresa e fazenda fora
do escopo não entram na resposta (R3, D063): a lista vem das mesmas listagens que decidem o 404 do endereço."""

from itertools import groupby

from django.views.decorators.http import require_GET

from projeto.escopo import resolver_escopo
from projeto.paginas_autenticadas import exige_acao, exige_entrada, renderizar_na_casca
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
    return renderizar_na_casca(requisicao, 'empresas.html', {'grupos': grupos})


@require_GET
@exige_entrada
@exige_acao('ver')
def empresa(requisicao, empresa_id):
    escopo, _ = resolver_escopo(requisicao.user, empresa_id)
    fazendas = fazendas_autorizadas(requisicao.user, empresa_id=escopo.pk)
    return renderizar_na_casca(requisicao, 'empresas.html', {'grupos': [(escopo, fazendas)] if fazendas else []}, empresa=escopo)
