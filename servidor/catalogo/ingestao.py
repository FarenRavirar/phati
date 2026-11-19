"""Ingestão de envio de camada vetorial (008, R3 a R6, R16). Função pura: lê, valida e devolve a prévia; não grava.

Ordem: tamanho, tipo pelo conteúdo, extração segura (zip), pré-checagens próprias, leitura com driver fixo, validação GEOS.
Coordenada não numérica, infinita e anel aberto são checados antes do GDAL: medido na T2.1 (2026-11-19), o GDAL
transforma NaN em geometria vazia, aceita infinito e lê anel aberto sem erro."""

import io
import json
import math
import re
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import NoReturn

from django.contrib.gis.gdal import DataSource, GDALException, OGRGeometry, SpatialReference
from django.contrib.gis.geos import GEOSException

from catalogo.models import SRID_GUARDA

ARQUIVO_TEMP = 'camada'
TAMANHO_BLOCO = 64 * 1024
FAMILIAS = (('Point', 'ponto'), ('LineString', 'linha'), ('Polygon', 'poligono'))
EPSG = re.compile(r'(?:urn:ogc:def:crs:)?EPSG:(?:[^:]*:)?(\d+)')
CRS84 = ('urn:ogc:def:crs:OGC:1.3:CRS84', 'urn:ogc:def:crs:OGC::CRS84')


@dataclass(frozen=True)
class Limites:
    """Limites de envio (spec 008 R16). Quem chama pode passar outros.

    shortcut: valores iniciais não medidos; medir com amostra sintética grande (spec 008 §Riscos) antes de fechar a Fase 2."""

    tamanho_bytes: int = 50 * 1024 * 1024
    entradas: int = 200
    descompactado_bytes: int = 200 * 1024 * 1024
    feicoes: int = 50_000
    campos: int = 100
    tamanho_nome_campo: int = 100
    tempo_segundos: float = 60.0


LIMITES_PADRAO = Limites()


class RecusaIngestao(Exception):
    """Envio recusado. `erros` tem uma linha por problema, na ordem encontrada, para a tela."""

    def __init__(self, erros):
        super().__init__('; '.join(erros))
        self.erros = list(erros)


@dataclass(frozen=True)
class FeicaoPrevia:
    geometria: object  # GEOSGeometry em SRID_GUARDA
    valores: dict


@dataclass(frozen=True)
class Previa:
    formato: str
    tipo: str
    sistema: str  # EPSG e nome detectados
    origem_sistema: str  # arquivo de projeção, formato ou membro crs legado
    transformacao: str  # 'nenhuma', 'equivalencia' ou 'aproximada'
    avisos: tuple
    extensao: tuple  # xmin, ymin, xmax, ymax em SRID_GUARDA
    feicoes: tuple
    campos: tuple  # nomes das colunas do arquivo, na ordem em que vêm

    @property
    def contagem(self):
        return len(self.feicoes)


@dataclass(frozen=True)
class _Leitura:
    formato: str
    caminho: Path
    driver: str
    srid: int | None  # None: vem da camada (shapefile)
    origem: str


class _ConstanteProibida(Exception):
    pass


def _recusa(*erros) -> NoReturn:
    raise RecusaIngestao(list(erros))


def _formato(dados):
    if dados[:4] == b'PK\x03\x04':
        return 'zip'
    inicio = dados.lstrip(b'\xef\xbb\xbf \t\r\n')[:1]
    if inicio == b'{':
        return 'geojson'
    if inicio == b'<':
        return 'kml'  # confirmado pela raiz em _precheck_kml
    return None


def _srid_de_nome(nome):
    casou = EPSG.fullmatch(nome) if isinstance(nome, str) else None
    if casou is None:
        return None
    codigo = int(casou.group(1))
    try:
        SpatialReference(codigo)
    except GDALException:
        return None
    return codigo


def _precheck_geojson(dados):
    def proibe(constante):
        raise _ConstanteProibida(constante)

    try:
        objeto = json.loads(dados.decode('utf-8-sig'), parse_constant=proibe)
    except _ConstanteProibida:
        raise RecusaIngestao(['coordenada NaN ou infinita no GeoJSON']) from None
    except (ValueError, UnicodeDecodeError):
        raise RecusaIngestao(['GeoJSON inválido']) from None
    if not isinstance(objeto, dict):
        raise RecusaIngestao(['GeoJSON inválido'])
    crs = objeto.get('crs')
    if crs is None:
        return 4326, 'formato (WGS 84 assumido pelo GeoJSON)'
    propriedades = crs.get('properties') if isinstance(crs, dict) else None
    nome = propriedades.get('name') if isinstance(propriedades, dict) else None
    if nome in CRS84:  # RFC 7946 §4: CRS84 é o WGS 84 padrão; o membro crs em si é legado
        return 4326, 'membro crs legado do GeoJSON (CRS84 lido como WGS 84)'
    srid = _srid_de_nome(nome)
    if srid is None:
        raise RecusaIngestao(['sistema de referência do membro crs não reconhecido'])
    return srid, 'membro crs legado do GeoJSON'


def _precheck_kml(dados):
    if re.search(rb'<!\s*(?:DOCTYPE|ENTITY)', dados, re.IGNORECASE):
        _recusa('KML com DOCTYPE ou entidade recusado')
    try:
        raiz = ET.fromstring(dados)  # sem DOCTYPE, o analisador não resolve entidade
    except ET.ParseError:
        raise RecusaIngestao(['KML inválido']) from None
    if not raiz.tag.endswith('kml'):
        raise RecusaIngestao(['XML que não é KML'])
    for elemento in raiz.iter():
        if elemento.tag.endswith('coordinates') and elemento.text:
            for token in re.split(r'[\s,]+', elemento.text.strip()):
                if not token:
                    continue
                try:
                    valor = float(token)
                except ValueError:
                    raise RecusaIngestao(['coordenada KML não numérica']) from None
                if not math.isfinite(valor):
                    raise RecusaIngestao(['coordenada KML NaN ou infinita'])


def _ext(nome):
    return PurePosixPath(nome.replace('\\', '/')).suffix.lower().lstrip('.')


def _varrer(arquivo, limites):
    infos = arquivo.infolist()
    if len(infos) > limites.entradas:
        _recusa('compactado com entradas acima do limite')
    total = 0
    for info in infos:
        caminho = info.filename.replace('\\', '/')
        if caminho.startswith('/') or re.match(r'^[A-Za-z]:', caminho) or '..' in caminho.split('/') or '\x00' in caminho:
            _recusa('entrada com caminho fora do envio')
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            _recusa('ligação simbólica no compactado')
        total += info.file_size
        if total > limites.descompactado_bytes:
            _recusa('compactado descompacta acima do limite')
    return infos


def _extrair(arquivo, info, destino, orcamento):
    """Copia a entrada contando os bytes reais (o cabeçalho pode mentir). Devolve o orçamento restante."""
    try:
        with arquivo.open(info) as origem, open(destino, 'wb') as saida:
            primeiro = True
            for bloco in iter(lambda: origem.read(TAMANHO_BLOCO), b''):
                if primeiro and bloco[:4] == b'PK\x03\x04':
                    _recusa('compactado dentro de compactado')
                primeiro = False
                orcamento -= len(bloco)
                if orcamento < 0:
                    _recusa('compactado descompacta acima do limite')
                saida.write(bloco)
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
        _recusa('compactado inválido ou criptografado')
    return orcamento


def _zip_shapefile(arquivo, infos, shps, tmp, limites):
    if len(shps) != 1:
        _recusa('compactado com mais de um shapefile')
    base = PurePosixPath(shps[0].filename.replace('\\', '/')).stem
    presentes = {}
    for info in infos:
        caminho = PurePosixPath(info.filename.replace('\\', '/'))
        if caminho.stem == base and caminho.suffix.lower() in ('.shp', '.shx', '.dbf', '.prj'):
            presentes[_ext(info.filename)] = info
    if 'prj' not in presentes:
        _recusa('shapefile sem arquivo de projeção (.prj): recusado')
    for ext in ('shx', 'dbf'):
        if ext not in presentes:
            _recusa(f'shapefile incompleto: falta .{ext}')
    orcamento = limites.descompactado_bytes
    for ext, info in presentes.items():
        orcamento = _extrair(arquivo, info, tmp / f'{ARQUIVO_TEMP}.{ext}', orcamento)
    return _Leitura('shapefile', tmp / f'{ARQUIVO_TEMP}.shp', 'ESRI Shapefile', None, 'arquivo de projeção (.prj)')


def _zip_kmz(arquivo, kmls, tmp, limites):
    if len(kmls) != 1:
        _recusa('KMZ com mais de um KML')
    destino = tmp / f'{ARQUIVO_TEMP}.kml'
    _extrair(arquivo, kmls[0], destino, limites.descompactado_bytes)
    _precheck_kml(destino.read_bytes())
    return _Leitura('kmz', destino, 'KML', 4326, 'formato (WGS 84 assumido pelo KML dentro do KMZ)')


def _zip(dados, limites, tmp):
    try:
        arquivo = zipfile.ZipFile(io.BytesIO(dados))
    except zipfile.BadZipFile:
        raise RecusaIngestao(['compactado inválido']) from None
    with arquivo:
        infos = _varrer(arquivo, limites)
        shps = [i for i in infos if _ext(i.filename) == 'shp']
        kmls = [i for i in infos if _ext(i.filename) == 'kml']
        if shps and kmls:
            _recusa('compactado com shapefile e KML: formato ambíguo')
        if shps:
            return _zip_shapefile(arquivo, infos, shps, tmp, limites)
        if kmls:
            return _zip_kmz(arquivo, kmls, tmp, limites)
        _recusa('compactado sem shapefile nem KML')


def _caminho_seguro(caminho, pasta):
    """O caminho do GDAL sai da pasta temporária: sem `/vsi`, sem URL e sem query."""
    resolvido = caminho.resolve()
    texto = str(resolvido)
    if not resolvido.is_relative_to(pasta.resolve()) or '://' in texto or '?' in texto or texto.startswith('/vsi'):
        _recusa('caminho de leitura fora da pasta do envio')
    return texto


def _familia(geometria):
    nome = geometria.geom_type.name
    for prefixo, familia in FAMILIAS:
        if nome.replace('Multi', '', 1).startswith(prefixo):
            return familia
    return None


def _pontos(tupla):
    if tupla and isinstance(tupla[0], (int, float)):
        yield tupla[:2]
        return
    for sub in tupla:
        yield from _pontos(sub)


def _anel_aberto(geometria):
    poligonos = [geometria] if geometria.geom_type.name.startswith('Polygon') else list(geometria)
    return any(anel[0] != anel[-1] for poligono in poligonos for anel in poligono.tuple)


def _valor(valor):
    if valor is None or isinstance(valor, (bool, int, float, str)):
        return valor
    return str(valor)


def _transformacao(srid, srs):
    if srid == SRID_GUARDA:
        return 'nenhuma'
    proj = srs.proj or ''
    if '+towgs84=0,0,0,0,0,0,0' in proj or '+datum=WGS84' in proj:
        return 'equivalencia'
    return 'aproximada'


def _ler(leitura, limites, prazo):
    # shortcut: a abertura pelo GDAL (DataSource) não é interrompível pelo prazo, que só vale no laço de feições; subir para processo filho com timeout se um envio real demorar nessa etapa.
    try:
        ds = DataSource(_caminho_seguro(leitura.caminho, leitura.caminho.parent), ds_driver=leitura.driver)
    except GDALException:
        raise RecusaIngestao([f'não foi possível ler o arquivo como {leitura.formato}']) from None
    if len(ds) != 1:
        raise RecusaIngestao(['o arquivo tem mais de uma camada'])
    camada = ds[0]
    srid, origem = leitura.srid, leitura.origem
    if leitura.formato == 'shapefile':
        srid = camada.srs.srid if camada.srs is not None else None
        if srid is None:
            _recusa('shapefile com projeção não reconhecida')
    if len(camada) == 0:
        _recusa('arquivo sem feições')
    if len(camada) > limites.feicoes:
        _recusa('arquivo com feições acima do limite')
    campos = camada.fields
    if len(campos) > limites.campos:
        _recusa('arquivo com campos acima do limite')
    if any(len(nome) > limites.tamanho_nome_campo for nome in campos):
        _recusa('nome de campo acima do limite')

    origem_srs = SpatialReference(srid)
    alvo = SpatialReference(SRID_GUARDA)
    erros, familias, feicoes = [], set(), []
    zm = 0
    for indice, feicao in enumerate(camada, start=1):
        if time.monotonic() > prazo:
            _recusa('tempo de leitura excedido')
        try:
            bruta = feicao.geom
        except GDALException:
            erros.append(f'feição {indice}: geometria ausente')
            continue
        if bruta.empty:
            erros.append(f'feição {indice}: geometria vazia ou com coordenada NaN')
            continue
        geometria = OGRGeometry(memoryview(bruta.wkb), srs=origem_srs)
        familia = _familia(geometria)
        if familia is None:
            erros.append(f'feição {indice}: tipo de geometria sem suporte')
            continue
        familias.add(familia)
        if geometria.is_measured or geometria.coord_dim > 2:
            zm += 1
            geometria.set_measured(False)
            geometria.set_3d(False)
        if not all(math.isfinite(c) for ponto in _pontos(geometria.tuple) for c in ponto):
            erros.append(f'feição {indice}: coordenada NaN ou infinita')
            continue
        if familia == 'poligono' and _anel_aberto(geometria):
            erros.append(f'feição {indice}: anel aberto')
            continue
        if srid != SRID_GUARDA:
            geometria.transform(alvo)
        if not all(-180 <= x <= 180 and -90 <= y <= 90 for x, y in _pontos(geometria.tuple)):
            erros.append(f'feição {indice}: coordenada fora da faixa do sistema')
            continue
        try:
            geos = geometria.geos
        except GEOSException:
            erros.append(f'feição {indice}: geometria recusada pelo GEOS')
            continue
        if not geos.valid:
            erros.append(f'feição {indice}: geometria inválida ({geos.valid_reason})')
            continue
        geos.srid = SRID_GUARDA
        feicoes.append(FeicaoPrevia(geos, {nome: _valor(feicao.get(nome)) for nome in campos}))
    if len(familias) > 1:
        erros.append('tipo misturado na mesma camada: ' + ', '.join(sorted(familias)))
    if erros:
        raise RecusaIngestao(erros)

    transformacao = _transformacao(srid, origem_srs)
    avisos = []
    if 'legado' in origem:
        avisos.append('membro crs do GeoJSON é legado (a RFC 7946 o removeu); sistema lido e mostrado na prévia')
    if zm:
        avisos.append(f'Z e M descartados em {zm} feições (altitude e medida não entram no modelo 2D)')
    if transformacao == 'aproximada':
        avisos.append('transformação aproximada, sem grade de correção')
    extensoes = [f.geometria.extent for f in feicoes]
    return Previa(
        formato=leitura.formato,
        tipo=next(iter(familias)),
        sistema=f'EPSG:{srid} ({origem_srs.name})',
        origem_sistema=origem,
        transformacao=transformacao,
        avisos=tuple(avisos),
        extensao=(min(e[0] for e in extensoes), min(e[1] for e in extensoes), max(e[2] for e in extensoes), max(e[3] for e in extensoes)),
        feicoes=tuple(feicoes),
        campos=tuple(campos),
    )


def ingerir_envio(caminho, limites=LIMITES_PADRAO):
    """Lê o envio em `caminho` e devolve a prévia, ou levanta RecusaIngestao com a lista de erros."""
    prazo = time.monotonic() + limites.tempo_segundos
    caminho = Path(caminho)
    if caminho.is_symlink() or not caminho.is_file():
        _recusa('envio não é arquivo comum')
    if caminho.stat().st_size > limites.tamanho_bytes:
        _recusa('arquivo acima do limite de tamanho')
    dados = caminho.read_bytes()
    formato = _formato(dados)
    with tempfile.TemporaryDirectory() as pasta:
        tmp = Path(pasta)
        if formato == 'zip':
            leitura = _zip(dados, limites, tmp)
        elif formato == 'geojson':
            srid, origem = _precheck_geojson(dados)
            (tmp / f'{ARQUIVO_TEMP}.geojson').write_bytes(dados)
            leitura = _Leitura('geojson', tmp / f'{ARQUIVO_TEMP}.geojson', 'GeoJSON', srid, origem)
        elif formato == 'kml':
            _precheck_kml(dados)
            (tmp / f'{ARQUIVO_TEMP}.kml').write_bytes(dados)
            leitura = _Leitura('kml', tmp / f'{ARQUIVO_TEMP}.kml', 'KML', 4326, 'formato (WGS 84 assumido pelo KML)')
        else:
            _recusa('tipo de arquivo não suportado')
        return _ler(leitura, limites, prazo)
