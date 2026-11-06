"""Rotas do pacote offline (004b R3, R4, R11): manifesto, camadas e arquivos da versão vigente da fazenda.

Todas começam por `resolver_escopo` (404 igual ao de id inexistente) e o nome do arquivo é conferido contra o manifesto,
nunca montado a partir da URL. A leitura por faixa de bytes é própria: o `FileResponse` do Django 6.1.2 não trata
`Range` (medido: sem `Accept-Ranges` e sempre 200).
shortcut: o arquivo passa pelo worker do gunicorn; trocar por `X-Accel-Redirect` do nginx quando o pacote passar de ~100 MB."""

import re
from pathlib import Path

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.utils.cache import get_conditional_response, patch_cache_control
from django.utils.http import quote_etag
from django.views.decorators.http import require_GET

from pacote import manifesto as contrato
from pacote.models import VersaoPacote
from permissao.pode import com_permissao, pode
from projeto import mapa
from projeto.escopo import resolver_escopo
from projeto.paginas_autenticadas import cache_proprio, exige_acao, exige_entrada

_FAIXA = re.compile(r'^bytes=(\d*)-(\d*)$')
_BLOCO = 1 << 20


def _vigente(pessoa, fazenda) -> VersaoPacote:
    with com_permissao(pessoa, 'ver', 'baixar_pacote_offline'):
        versao = VersaoPacote.objects.filter(fazenda=fazenda, vigente=True).first()
    if versao is None:
        raise Http404
    return versao


def _exigir_download(pessoa, fazenda) -> None:
    """Com alcance e sem `baixar_pacote_offline`: 403 (R3); sem alcance o 404 já saiu de `resolver_escopo`."""
    if not pode(pessoa, 'baixar_pacote_offline', fazenda):
        raise PermissionDenied


def _privado(resposta, etag=None):
    # `private` veda proxy e CDN (o dado é de uma fazenda); `no-cache` obriga a revalidar, então o acesso é checado sempre.
    if etag:
        resposta['ETag'] = etag
    patch_cache_control(resposta, private=True, no_cache=True)
    return resposta


@require_GET
@exige_entrada
@exige_acao('baixar_pacote_offline')
@cache_proprio
def pacote_manifesto(requisicao, empresa_id, fazenda_id):
    _, fazenda = resolver_escopo(requisicao.user, empresa_id, fazenda_id)
    _exigir_download(requisicao.user, fazenda)
    versao = _vigente(requisicao.user, fazenda)
    return _privado(JsonResponse(contrato.validar(versao.manifesto).model_dump(mode='json')))


@require_GET
@exige_entrada
@exige_acao('baixar_pacote_offline')
@cache_proprio
def pacote_camadas(requisicao, empresa_id, fazenda_id):
    """As camadas do pacote saem da mesma função da API de camadas da 004 (uma só regra de quem vê o quê, R4)."""
    if not mapa.mapa_ativo():
        raise Http404
    _, fazenda = resolver_escopo(requisicao.user, empresa_id, fazenda_id)
    _exigir_download(requisicao.user, fazenda)
    return _privado(JsonResponse(mapa.camadas_visiveis(requisicao.user, fazenda), content_type='application/geo+json'))


def _faixa(cabecalho: str | None, tamanho: int):
    """`(inicio, fim)` inclusivos, `None` (sem faixa de um trecho: serve inteiro) ou `'invalida'` (416)."""
    achado = _FAIXA.match(cabecalho or '')
    if not achado or (achado[1] == '' and achado[2] == ''):
        return None
    inicio, fim = achado[1], achado[2]
    if inicio == '':  # últimos N bytes
        sufixo = int(fim)
        return (max(tamanho - sufixo, 0), tamanho - 1) if sufixo > 0 and tamanho else 'invalida'
    primeiro = int(inicio)
    ultimo = min(int(fim), tamanho - 1) if fim else tamanho - 1
    return (primeiro, ultimo) if primeiro <= ultimo and primeiro < tamanho else 'invalida'


def _blocos(caminho: Path, inicio: int, fim: int):
    restante = fim - inicio + 1
    with caminho.open('rb') as arquivo:
        arquivo.seek(inicio)
        while restante > 0:
            bloco = arquivo.read(min(_BLOCO, restante))
            if not bloco:
                return
            restante -= len(bloco)
            yield bloco


@require_GET
@exige_entrada
@exige_acao('ver')
@cache_proprio
def pacote_arquivo(requisicao, empresa_id, fazenda_id, nome):
    _, fazenda = resolver_escopo(requisicao.user, empresa_id, fazenda_id)
    versao = _vigente(requisicao.user, fazenda)
    arquivo = next((a for a in contrato.validar(versao.manifesto).arquivos if a.nome == nome), None)
    if arquivo is None:
        raise Http404
    caminho = Path(settings.PACOTES_DIR) / str(fazenda_id) / f'v{versao.numero}' / arquivo.nome
    if not caminho.is_file():
        raise Http404
    etag = quote_etag(arquivo.sha256)
    condicional = get_conditional_response(requisicao, etag=etag)
    if condicional is not None and condicional.status_code in (304, 412):
        return _privado(condicional, etag)
    faixa = _faixa(requisicao.headers.get('Range'), arquivo.bytes)
    if faixa == 'invalida':
        resposta = HttpResponse(status=416)
        resposta['Content-Range'] = f'bytes */{arquivo.bytes}'
        return _privado(resposta, etag)
    inicio, fim = faixa or (0, arquivo.bytes - 1)
    resposta = StreamingHttpResponse(_blocos(caminho, inicio, fim), status=206 if faixa else 200, content_type='application/octet-stream')
    resposta['Content-Length'] = str(fim - inicio + 1 if arquivo.bytes else 0)
    resposta['Accept-Ranges'] = 'bytes'
    if faixa:
        resposta['Content-Range'] = f'bytes {inicio}-{fim}/{arquivo.bytes}'
    return _privado(resposta, etag)


for _visao in (pacote_manifesto, pacote_camadas, pacote_arquivo):
    setattr(_visao, 'dados_da_web', True)  # entram na matriz de cobertura (R18)
