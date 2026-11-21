"""API do catálogo (008 T3.2; R3, R9, R11, R12, R13, R14, R21; D061): envio, prévia, publicação e leitura paginada.

Toda rota passa por `exige_permissao`, que abre `com_permissao` e decide com `pode`. Para envio, camada e fazenda sem
permissão, fora do escopo ou inexistentes, a resposta é a mesma 404 `nao_encontrado` (R11). Atributo oculto
(`visivel=False`) nunca sai na resposta, nem em filtro, nem em busca: coluna oculta ou inexistente no filtro é 422.
"""

import json
from typing import Annotated
from uuid import UUID

from django.conf import settings
from django.db.models import Count, F, Func, OuterRef, Q, Subquery, TextField, Value
from django.db.models.functions import Cast
from ninja import Router, Schema, Status
from ninja.params import functions as parametros  # as funções reais: o `File`/`Query` de `ninja` é alias para o type checker
from ninja.errors import HttpError
from ninja.files import UploadedFile

from catalogo import envios, publicacao
from catalogo.ingestao import LIMITES_PADRAO, MENSAGEM_TAMANHO, RecusaIngestao
from catalogo.models import AtributoVersao, Camada, EnvioCamada, Feicao, VersaoCamada
from catalogo.publicacao import EnvioNaoEncontrado, RecusaPublicacao, publicar_envio
from permissao.pode import exige_permissao, pode
from territorio.models import Fazenda, SubArea

roteador = Router(tags=['catalogo'])
LIMITE_PADRAO = 50
LIMITE_MAXIMO = 100


class EntradaPublicacao(Schema):
    estudo_id: int
    metadados: dict
    camada_id: UUID | None = None  # id público (R1), o mesmo que a API devolve
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


def _alcance_de_feicoes(pessoa, fazenda):
    """Feições que a pessoa lê na camada da fazenda (plan.md:63, R11; decisão do mantenedor). `None`: todas (`ver` na fazenda).
    Senão, só as dos nós em que `pode(ver)` vale (descendentes incluídos pela regra de `pode`). Feição da fazenda (nó None)
    só com `ver` na fazenda. Lista vazia: a pessoa não lê nenhuma feição desta camada."""
    if pode(pessoa, 'ver', fazenda):
        return None
    # Nó arquivado entra: `ver` é ação de leitura e vale em escopo arquivado (`ACOES_DE_LEITURA`, pode.py:33).
    nos = SubArea.objects.filter(fazenda=fazenda).order_by('pk')
    return [no.pk for no in nos if pode(pessoa, 'ver', no)]


def _camada_visivel(acao):
    """Alvo da rota por camada: a fazenda (ver na fazenda) ou um nó visível (plan.md:63: alvo SubArea ou Fazenda). Sem nenhum:
    404 igual ao de camada inexistente (R11)."""
    def obter(requisicao, camada_id, **_):
        camada = Camada.objects.filter(publico_id=camada_id).select_related('fazenda').first()
        if camada is None:
            raise Camada.DoesNotExist()
        if pode(requisicao.user, acao, camada.fazenda):
            return camada.fazenda
        visiveis = _alcance_de_feicoes(requisicao.user, camada.fazenda)
        if not visiveis:
            raise Camada.DoesNotExist()
        return SubArea.objects.get(pk=visiveis[0])
    return obter


def _ler_limitado(arquivo):
    """Conteúdo do arquivo, ou None se passa do limite (R16). `size` conhecido acima do limite recusa sem ler. Tamanho
    desconhecido (`size` None) não é presumido: lê no máximo limite+1 bytes e recusa se passar."""
    limite = LIMITES_PADRAO.tamanho_bytes
    if arquivo.size is not None and arquivo.size > limite:
        return None
    dados = arquivo.read(limite + 1)
    return None if len(dados) > limite else dados


def _valor_texto(nome):
    """Valor da coluna como texto: `valores ->> CAST(nome AS text)`. `KeyTextTransform` trata nome numérico ("2026")
    como índice de array; aqui a chave segue como texto, sempre chave de objeto JSON (achado Codex, P2)."""
    return Func(F('valores'), Cast(Value(nome), output_field=TextField()), template='(%(expressions)s)',
                arg_joiner=' ->> ', output_field=TextField())


def _camada_pk(camada_publica):
    """Camada pelo id público, dentro da RLS da pessoa. Inexistente ou de outro estudo: a mesma recusa (sem vazar)."""
    if camada_publica is None:
        return None
    camada = Camada.objects.filter(publico_id=camada_publica).first()
    if camada is None:
        raise RecusaPublicacao(['camada não encontrada neste estudo'])
    return camada.pk


@roteador.post('fazendas/{fazenda_id}/envios', url_name='catalogo_criar_envio', response={201: dict, 422: dict})
@exige_permissao('publicar_camada', _fazenda_visivel('publicar_camada'))
def criar_envio(request, fazenda_id: int, arquivo: Annotated[UploadedFile, parametros.File()]):
    dados = _ler_limitado(arquivo)
    if dados is None:
        return _recusado([MENSAGEM_TAMANHO])
    fazenda = Fazenda.objects.get(pk=fazenda_id)
    try:
        envio = envios.criar_envio(request.user, fazenda, dados)
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


@roteador.get('envios/{envio_id}/geometria', url_name='catalogo_geometria', response={200: dict, 422: dict})
@exige_permissao('publicar_camada', _envio_visivel('publicar_camada'))
def geometria(request, envio_id: UUID,
              limite: Annotated[int, parametros.Query(ge=1, le=settings.CATALOGO_GEOMETRIA_LIMITE_MAXIMO)] = settings.CATALOGO_GEOMETRIA_LIMITE_PADRAO):
    envio = EnvioCamada.objects.get(publico_id=envio_id)
    try:
        return publicacao.ler_geometria(envio, limite)
    except EnvioNaoEncontrado:
        raise EnvioCamada.DoesNotExist() from None
    except (RecusaPublicacao, RecusaIngestao) as erro:
        return _recusado(erro.erros)


@roteador.post('envios/{envio_id}/publicar', url_name='catalogo_publicar', response={201: dict, 422: dict})
@exige_permissao('publicar_camada', _envio_visivel('publicar_camada'))
def publicar(request, envio_id: UUID, dados: EntradaPublicacao):
    envio = EnvioCamada.objects.get(publico_id=envio_id)
    try:
        versao = publicar_envio(
            request.user, envio.pk, estudo_id=dados.estudo_id, metadados=dados.metadados, camada_id=_camada_pk(dados.camada_id),
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
def camadas(request, fazenda_id: int, limite: Annotated[int, parametros.Query(ge=1, le=LIMITE_MAXIMO)] = LIMITE_PADRAO,
            deslocamento: Annotated[int, parametros.Query(ge=0)] = 0):
    itens = [
        {'camada_id': str(c.publico_id), 'nome': c.nome, 'divisao': c.coluna_no is not None}
        for c in Camada.objects.filter(fazenda_id=fazenda_id).order_by('id')[deslocamento:deslocamento + limite]
    ]
    return {'itens': itens, 'limite': limite, 'deslocamento': deslocamento}


@roteador.get('camadas/{camada_id}/versoes/{numero}/feicoes', url_name='catalogo_feicoes_listar', response={200: dict, 422: dict})
@exige_permissao('ver', _camada_visivel('ver'))
def feicoes(request, camada_id: UUID, numero: int, limite: Annotated[int, parametros.Query(ge=1, le=LIMITE_MAXIMO)] = LIMITE_PADRAO,
            deslocamento: Annotated[int, parametros.Query(ge=0)] = 0, coluna: str | None = None, valor: str | None = None,
            busca: str | None = None):
    camada = Camada.objects.get(publico_id=camada_id)
    versao = VersaoCamada.objects.get(camada=camada, numero=numero)
    alcance = _alcance_de_feicoes(request.user, camada.fazenda)
    # Filtro único de leitura: o ordinal também conta só o alcance, para não vazar a posição das feições de outros nós.
    filtro = Q() if alcance is None else Q(sub_area_id__in=alcance)
    visiveis = sorted(AtributoVersao.objects.filter(versao=versao, visivel=True).values_list('nome', flat=True))
    if coluna is not None and (coluna not in visiveis or valor is None):
        raise HttpError(422, 'filtro_invalido')  # coluna oculta ou inexistente: 422, nunca "sem resultado" (R9)
    # `_indice`: ordinal da feição na versão COMPLETA (pela pk), calculado antes de filtrar, então não muda com filtro,
    # busca ou página. Subconsulta correlata: conta as feições da versão com pk ≤ a da linha (custo por linha, não medido).
    ordinal = Feicao.objects.filter(versao=versao).filter(filtro, pk__lte=OuterRef('pk')).order_by().values('versao').annotate(
        total=Count('pk')).values('total')
    qs = Feicao.objects.filter(versao=versao).filter(filtro).annotate(_indice=Subquery(ordinal)).order_by('id')
    if coluna is not None:
        qs = qs.annotate(_filtro=_valor_texto(coluna)).filter(_filtro=valor)
    if busca:
        # Busca só nas colunas visíveis: a oculta não entra no alcance da busca (R9).
        qs = qs.annotate(**{f'_c{i}': _valor_texto(nome) for i, nome in enumerate(visiveis)})
        alcance = Q(pk__in=[])
        for i in range(len(visiveis)):
            alcance |= Q(**{f'_c{i}__icontains': busca})
        qs = qs.filter(alcance)
    itens = [
        {'indice': linha['_indice'], 'geometria': json.loads(linha['geometria'].json),
         'valores': {nome: linha['valores'].get(nome) for nome in visiveis}}
        for linha in qs.values('_indice', 'geometria', 'valores')[deslocamento:deslocamento + limite]
    ]
    return {'itens': itens, 'limite': limite, 'deslocamento': deslocamento}
