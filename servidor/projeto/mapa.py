"""Mapa de teste de layout (004 R1, R3): a flag e a política de conteúdo só da resposta que leva o mapa.

Flag desligada: a página da fazenda é a da 003 e a CSP é a da 002. A flag nunca liga fora de `AMBIENTES_DE_TESTE`
(trava na partida, `settings.py`)."""

from django.conf import settings
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_GET

from projeto import camadas_sinteticas
from projeto.escopo import resolver_escopo
from projeto.paginas_autenticadas import exige_acao, exige_entrada


def mapa_ativo():
    return settings.MAPA_TESTE_ATIVO


def com_politica_do_mapa(resposta):
    """Troca a CSP só desta resposta (`csp_override` substitui a política, não soma; a de `SECURE_CSP_MAPA` já é completa)."""
    if mapa_ativo():
        resposta._csp_config = settings.SECURE_CSP_MAPA
    return resposta


@require_GET
@exige_entrada
@exige_acao('ver')
def camadas(requisicao, empresa_id, fazenda_id):
    """Camadas sintéticas em GeoJSON (R4). Flag desligada: 404; sem alcance: o 404 de fazenda inexistente (D063), da
    mesma `resolver_escopo` da página. Mesmo acesso de ver a fazenda; permissão por sub-área é da spec de camadas."""
    if not mapa_ativo():
        raise Http404
    resolver_escopo(requisicao.user, empresa_id, fazenda_id)
    return JsonResponse(camadas_sinteticas.geojson(), content_type='application/geo+json')


# Rota de dados da web: entra na matriz de cobertura (R22), que compara a API e as views marcadas assim.
setattr(camadas, 'dados_da_web', True)
