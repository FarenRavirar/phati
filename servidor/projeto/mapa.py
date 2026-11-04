"""Mapa de teste de layout (004 R1, R3): a flag e a política de conteúdo só da resposta que leva o mapa.

Flag desligada: a página da fazenda é a da 003 e a CSP é a da 002. A flag nunca liga fora de `AMBIENTES_DE_TESTE`
(trava na partida, `settings.py`)."""

import hashlib

from django.conf import settings
from django.http import Http404, JsonResponse
from django.utils.cache import get_conditional_response, patch_cache_control
from django.utils.http import quote_etag
from django.views.decorators.http import require_GET

from projeto import camadas_sinteticas
from projeto.escopo import resolver_escopo
from projeto.paginas_autenticadas import cache_proprio, exige_acao, exige_entrada


def mapa_ativo():
    """Mapa de teste de layout ligado (`PHATI_MAPA_TESTE_ATIVO`); a trava de ambiente já barrou a flag fora dos ambientes de teste."""
    return settings.MAPA_TESTE_ATIVO


def fundo_google_ativo():
    """Fundo Google (R17): só com o mapa de teste ligado; `settings.py` já barra a flag fora dos ambientes de teste."""
    return mapa_ativo() and settings.MAPA_FUNDO_GOOGLE_ATIVO


def chave_google():
    """Chave restrita por referenciador (R18): vai à página só com a flag do Google; sem ela, string vazia."""
    return settings.MAPA_GOOGLE_CHAVE if fundo_google_ativo() else ''


def com_politica_do_mapa(resposta):
    """Troca a CSP só desta resposta (`csp_override` substitui a política, não soma; as de `SECURE_CSP_MAPA*` já são completas).
    Os domínios do Google (R18) entram só com a flag do Google."""
    if mapa_ativo():
        resposta._csp_config = settings.SECURE_CSP_MAPA_GOOGLE if fundo_google_ativo() else settings.SECURE_CSP_MAPA
        if fundo_google_ativo():
            # A chave vem restrita por referenciador. Medido com a chave real (T3.6, 2026-11-04): origem permitida 200, origem
            # não permitida 403, e sem `Referer` ainda 200 (o `fetch` entre origens leva o cabeçalho `Origin`, que o Google aceita).
            # `strict-origin-when-cross-origin` (R18) manda só a origem, nunca o caminho, a outro domínio.
            resposta['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return resposta


@require_GET
@exige_entrada
@exige_acao('ver')
@cache_proprio
def camadas(requisicao, empresa_id, fazenda_id):
    """Camadas sintéticas em GeoJSON (R4). Flag desligada: 404; sem alcance: o 404 de fazenda inexistente (D063), da
    mesma `resolver_escopo` da página. Mesmo acesso de ver a fazenda; permissão por sub-área é da spec de camadas."""
    if not mapa_ativo():
        raise Http404
    resolver_escopo(requisicao.user, empresa_id, fazenda_id)
    resposta = JsonResponse(camadas_sinteticas.geojson(), content_type='application/geo+json')
    # Cache do navegador e do aplicativo (dado próprio, sem cota): `private` veda proxy e CDN compartilhado (o dado é de uma
    # fazenda) e `no-cache` obriga a revalidar a cada uso, então o acesso é checado no servidor sempre e o `ETag` só poupa o
    # corpo (304). O 304 sai depois de `resolver_escopo`: quem perdeu o acesso recebe 404, nunca 304. Quando houver versão de
    # camada na URL, trocar por `max-age` longo com `immutable`.
    etag = quote_etag(hashlib.sha256(resposta.content).hexdigest())
    resposta['ETag'] = etag
    patch_cache_control(resposta, private=True, no_cache=True)
    condicional = get_conditional_response(requisicao, etag=etag, response=resposta)
    # Sem `Last-Modified`, o Django trata um `If-Unmodified-Since` válido como falha (412); a rota não tem data de modificação, então
    # essa condição é ignorada. `If-Match` que não bate segue 412. Achado real (review PR #44, CodeRabbit, menor).
    if condicional is not None and condicional.status_code == 412 and 'HTTP_IF_MATCH' not in requisicao.META:
        condicional = None
    return condicional or resposta


# Rota de dados da web: entra na matriz de cobertura (R22), que compara a API e as views marcadas assim.
setattr(camadas, 'dados_da_web', True)
