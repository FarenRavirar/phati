"""API do catálogo (008 T3.2; R3, R9, R11, R12, R13, R14, R21; D061): envio, prévia, publicação e leitura paginada.

Toda rota passa por `exige_permissao`, que abre `com_permissao` e decide com `pode`. Para envio, camada e fazenda sem
permissão, fora do escopo ou inexistentes, a resposta é a mesma 404 `nao_encontrado` (R11). Atributo oculto
(`visivel=False`) nunca sai na resposta, nem em filtro, nem em busca: coluna oculta ou inexistente no filtro é 422.
"""

import json
from uuid import UUID

from django.db.models import Q
from django.db.models.fields.json import KeyTextTransform
from ninja import File, Query, Router, Schema, Status
from ninja.errors import HttpError
from ninja.files import UploadedFile

from catalogo import envios, publicacao
from catalogo.ingestao import LIMITES_PADRAO, MENSAGEM_TAMANHO, RecusaIngestao
from catalogo.models import AtributoVersao, Camada, EnvioCamada, Feicao, VersaoCamada
from catalogo.publicacao import EnvioNaoEncontrado, RecusaPublicacao, publicar_envio
from permissao.pode import exige_permissao, pode
from territorio.models import Fazenda

roteador = Router(tags=['catalogo'])
LIMITE_PADRAO = 50
LIMITE_MAXIMO = 100


class EntradaPublicacao(Schema):
    estudo_id: int
    metadados: dict
    camada_id: int | None = None
    ocultos: list[str] = []
    nos: list[int | None] = []
    coluna_no: str | None = None
    sistema_confirmado: bool = False


def _recusado(erros):
    # Só a lista de erros: sem valor de atributo e sem caminho interno (R14, R15).
    return Status(422, {'detalhe': 'recusado', 'erros': erros})


def _fazenda_visivel(acao):
    """Alvo da rota por fazenda. Sem `pode` ou inexistente: 404 igual (R11)."""
    def obter(requisicao, fazenda_id, **_):
        fazenda = Fazenda.objects.filter(pk=fazenda_id).first()
        if fazenda is None or not pode(requisicao.user, acao, fazenda):
            raise Fazenda.DoesNotExist()
        return fazenda
    return obter


def _envio_visivel(acao):
    """Alvo da rota por envio: o envio sob a RLS e `pode` sobre a fazenda dele. Sem permissão ou de outra empresa: 404."""
    def obter(requisicao, envio_id, **_):
        envio = EnvioCamada.objects.filter(publico_id=envio_id).select_related('fazenda').first()
        if envio is None or not pode(requisicao.user, acao, envio.fazenda):
            raise EnvioCamada.DoesNotExist()
        return envio.fazenda
    return obter


def _camada_visivel(acao):
    def obter(requisicao, camada_id, **_):
        camada = Camada.objects.filter(publico_id=camada_id).select_related('fazenda').first()
        if camada is None or not pode(requisicao.user, acao, camada.fazenda):
            raise Camada.DoesNotExist()
        return camada.fazenda
    return obter


@roteador.post('fazendas/{fazenda_id}/envios', url_name='catalogo_criar_envio', response={201: dict, 422: dict})
@exige_permissao('publicar_camada', _fazenda_visivel('publicar_camada'))
def criar_envio(request, fazenda_id: int, arquivo: UploadedFile = File(...)):
    # Tamanho antes de ler o conteúdo (`size` é do envio, sem ler o arquivo). Recusa igual à da ingestão (R16).
    if arquivo.size > LIMITES_PADRAO.tamanho_bytes:
        return _recusado([MENSAGEM_TAMANHO])
    fazenda = Fazenda.objects.get(pk=fazenda_id)
    try:
        envio = envios.criar_envio(request.user, fazenda, arquivo.read())
    except RecusaIngestao as erro:
        return _recusado(erro.erros)
    return Status(201, {'envio_id': str(envio.publico_id)})


@roteador.get('envios/{envio_id}', url_name='catalogo_previa', response={200: dict, 422: dict})
@exige_permissao('publicar_camada', _envio_visivel('publicar_camada'))
def previa(request, envio_id: UUID):
    envio = EnvioCamada.objects.get(publico_id=envio_id)
    try:
        return publicacao.ler_previa(envio)
    except (RecusaPublicacao, RecusaIngestao) as erro:
        return _recusado(erro.erros)


@roteador.post('envios/{envio_id}/publicar', url_name='catalogo_publicar', response={201: dict, 422: dict})
@exige_permissao('publicar_camada', _envio_visivel('publicar_camada'))
def publicar(request, envio_id: UUID, dados: EntradaPublicacao):
    envio = EnvioCamada.objects.get(publico_id=envio_id)
    try:
        versao = publicar_envio(
            request.user, envio.pk, estudo_id=dados.estudo_id, metadados=dados.metadados, camada_id=dados.camada_id,
            ocultos=tuple(dados.ocultos), nos=dados.nos, coluna_no=dados.coluna_no,
            sistema_confirmado=dados.sistema_confirmado,
        )
    except EnvioNaoEncontrado:
        raise EnvioCamada.DoesNotExist() from None
    except (RecusaPublicacao, RecusaIngestao) as erro:
        return _recusado(erro.erros)
    return Status(201, {'camada_id': str(versao.camada.publico_id), 'versao': versao.numero})


@roteador.get('fazendas/{fazenda_id}/camadas', url_name='catalogo_camadas_listar', response={200: dict})
@exige_permissao('ver', _fazenda_visivel('ver'))
def camadas(request, fazenda_id: int, limite: int = Query(LIMITE_PADRAO, ge=1, le=LIMITE_MAXIMO),
            deslocamento: int = Query(0, ge=0)):
    itens = [
        {'camada_id': str(c.publico_id), 'nome': c.nome, 'divisao': c.coluna_no is not None}
        for c in Camada.objects.filter(fazenda_id=fazenda_id).order_by('id')[deslocamento:deslocamento + limite]
    ]
    return {'itens': itens, 'limite': limite, 'deslocamento': deslocamento}


@roteador.get('camadas/{camada_id}/versoes/{numero}/feicoes', url_name='catalogo_feicoes_listar', response={200: dict, 422: dict})
@exige_permissao('ver', _camada_visivel('ver'))
def feicoes(request, camada_id: UUID, numero: int, limite: int = Query(LIMITE_PADRAO, ge=1, le=LIMITE_MAXIMO),
            deslocamento: int = Query(0, ge=0), coluna: str | None = None, valor: str | None = None,
            busca: str | None = None):
    camada = Camada.objects.get(publico_id=camada_id)
    versao = VersaoCamada.objects.get(camada=camada, numero=numero)
    visiveis = sorted(AtributoVersao.objects.filter(versao=versao, visivel=True).values_list('nome', flat=True))
    if coluna is not None and (coluna not in visiveis or valor is None):
        raise HttpError(422, 'filtro_invalido')  # coluna oculta ou inexistente: 422, nunca "sem resultado" (R9)
    qs = Feicao.objects.filter(versao=versao).order_by('id')
    if coluna is not None:
        qs = qs.annotate(_filtro=KeyTextTransform(coluna, 'valores')).filter(_filtro=valor)
    if busca:
        # Busca só nas colunas visíveis: a oculta não entra no alcance da busca (R9).
        qs = qs.annotate(**{f'_c{i}': KeyTextTransform(nome, 'valores') for i, nome in enumerate(visiveis)})
        alcance = Q(pk__in=[])
        for i in range(len(visiveis)):
            alcance |= Q(**{f'_c{i}__icontains': busca})
        qs = qs.filter(alcance)
    # `indice` é o ordinal da feição na versão (1..N, pela pk): identificador que não expõe a chave primária (T3.8).
    itens = [
        {'indice': deslocamento + i, 'geometria': json.loads(f.geometria.json),
         'valores': {nome: f.valores.get(nome) for nome in visiveis}}
        for i, f in enumerate(qs[deslocamento:deslocamento + limite], start=1)
    ]
    return {'itens': itens, 'limite': limite, 'deslocamento': deslocamento}
