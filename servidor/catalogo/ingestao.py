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
EXTENSOES_LEITURA = frozenset({'geojson', 'kml', 'shp', 'shx', 'dbf', 'prj', 'cpg'})
TAMANHO_BLOCO = 64 * 1024
FAMILIAS = (('Point', 'ponto'), ('LineString', 'linha'), ('Polygon', 'poligono'))
EPSG = re.compile(r'(?:urn:ogc:def:crs:)?EPSG:(?:[^:]*:)?(\d+)')
CRS84 = ('urn:ogc:def:crs:OGC:1.3:CRS84', 'urn:ogc:def:crs:OGC::CRS84')
# XML 1.0 (W3C REC-xml, §2.2) não aceita U+0000: zero no arquivo é outra codificação (UTF-16, por exemplo).
KML_FORA_DE_UTF8 = 'KML fora de UTF-8 (zeros no arquivo) recusado'


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
    propriedades: tuple | None = None  # GeoJSON: propriedades como vieram no JSON (tipo original, sem o esquema do GDAL)


@dataclass(frozen=True)
class _Contexto:
    srid: int
    origem_srs: SpatialReference
    alvo: SpatialReference
    campos: tuple
    propriedades: tuple | None


@dataclass(frozen=True)
class _Feicao:
    familia: str | None
    zm: bool
    previa: FeicaoPrevia | None
    erro: str | None


class _ConstanteProibida(Exception):
    pass


def _recusa(*erros) -> NoReturn:
    raise RecusaIngestao(list(erros))


def _destino(tmp, extensao):
    """Único ponto de escrita do envio: `camada.<extensão>` dentro da pasta temporária, com extensão de uma lista fixa."""
    if extensao not in EXTENSOES_LEITURA:
        _recusa('extensão de leitura fora da lista')
    destino = (tmp / f'{ARQUIVO_TEMP}.{extensao}').resolve()
    if not destino.is_relative_to(tmp.resolve()):
        _recusa('destino de escrita fora da pasta do envio')
    return destino


def _formato(dados):
    if dados[:4] == b'PK\x03\x04':
        return 'zip'
    if dados[:2] in (b'\xff\xfe', b'\xfe\xff') or b'\x00' in dados[:4]:
        return 'kml'  # UTF-16: a recusa com a mensagem certa sai de _precheck_kml
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


def _propriedades_do_geojson(objeto):
    """Propriedades de cada feição, como vieram no JSON. Geometria solta não tem propriedades: devolve None."""
    tipo = objeto.get('type')
    if tipo == 'Feature':
        return (objeto.get('properties') if isinstance(objeto.get('properties'), dict) else {},)
    if tipo != 'FeatureCollection':
        return None
    features = objeto.get('features')
    if not isinstance(features, list) or not all(isinstance(f, dict) for f in features):
        raise RecusaIngestao(['GeoJSON inválido'])
    return tuple(f['properties'] if isinstance(f.get('properties'), dict) else {} for f in features)


def _sistema_do_geojson(objeto):
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


def _precheck_geojson(dados):
    def proibe(constante):
        raise _ConstanteProibida(constante)

    try:
        objeto = json.loads(dados.decode('utf-8-sig'), parse_constant=proibe)
    except _ConstanteProibida:
        raise RecusaIngestao(['coordenada NaN ou infinita no GeoJSON']) from None
    except ValueError:  # UnicodeDecodeError é subclasse de ValueError
        raise RecusaIngestao(['GeoJSON inválido']) from None
    if not isinstance(objeto, dict):
        raise RecusaIngestao(['GeoJSON inválido'])
    srid, origem = _sistema_do_geojson(objeto)
    return srid, origem, _propriedades_do_geojson(objeto)


def _proibe_dtd(dados):
    if b'\x00' in dados:
        _recusa(KML_FORA_DE_UTF8)
    if re.search(rb'<!\s*(?:DOCTYPE|ENTITY)', dados, re.IGNORECASE):
        _recusa('KML com DOCTYPE ou entidade recusado')


def _valida_coordenada_kml(token):
    try:
        valor = float(token)
    except ValueError:
        raise RecusaIngestao(['coordenada KML não numérica']) from None
    if not math.isfinite(valor):
        raise RecusaIngestao(['coordenada KML NaN ou infinita'])


def _coordenadas_kml(raiz):
    for elemento in raiz.iter():
        if elemento.tag.endswith('coordinates') and elemento.text:
            for token in re.split(r'[\s,]+', elemento.text.strip()):
                if token:
                    _valida_coordenada_kml(token)


def _precheck_kml(dados):
    _proibe_dtd(dados)  # antes de qualquer leitura XML: o analisador expande entidade interna
    try:
        raiz = ET.fromstring(dados)  # sem DOCTYPE, o analisador não resolve entidade
    except ET.ParseError:
        raise RecusaIngestao(['KML inválido']) from None
    if not raiz.tag.endswith('kml'):
        raise RecusaIngestao(['XML que não é KML'])
    _coordenadas_kml(raiz)


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
    except (zipfile.BadZipFile, RuntimeError):  # NotImplementedError é subclasse de RuntimeError
        _recusa('compactado inválido ou criptografado')
    return orcamento


def _zip_shapefile(arquivo, infos, shps, tmp, limites):
    if len(shps) != 1:
        _recusa('compactado com mais de um shapefile')
    base = PurePosixPath(shps[0].filename.replace('\\', '/')).stem
    presentes = {}
    for info in infos:
        caminho = PurePosixPath(info.filename.replace('\\', '/'))
        if caminho.stem == base and caminho.suffix.lower() in ('.shp', '.shx', '.dbf', '.prj', '.cpg'):
            presentes[_ext(info.filename)] = info
    if 'prj' not in presentes:
        _recusa('shapefile sem arquivo de projeção (.prj): recusado')
    for ext in ('shx', 'dbf'):
        if ext not in presentes:
            _recusa(f'shapefile incompleto: falta .{ext}')
    orcamento = limites.descompactado_bytes
    for ext, info in presentes.items():  # .cpg é opcional e vai junto: diz a codificação do dbf
        orcamento = _extrair(arquivo, info, _destino(tmp, ext), orcamento)
    return _Leitura('shapefile', _destino(tmp, 'shp'), 'ESRI Shapefile', None, 'arquivo de projeção (.prj)')


def _zip_kmz(arquivo, kmls, tmp, limites):
    if len(kmls) != 1:
        _recusa('KMZ com mais de um KML')
    destino = _destino(tmp, 'kml')
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


def _abrir_camada(leitura):
    # shortcut: a abertura pelo GDAL (DataSource) não é interrompível pelo prazo, que só vale no laço de feições; subir para processo filho com timeout se um envio real demorar nessa etapa.
    try:
        ds = DataSource(_caminho_seguro(leitura.caminho, leitura.caminho.parent), ds_driver=leitura.driver)
    except GDALException:
        raise RecusaIngestao([f'não foi possível ler o arquivo como {leitura.formato}']) from None
    if len(ds) != 1:
        raise RecusaIngestao(['o arquivo tem mais de uma camada'])
    return ds[0]


def _sistema(leitura, camada):
    if leitura.formato != 'shapefile':
        return leitura.srid, leitura.origem
    srid = camada.srs.srid if camada.srs is not None else None
    if srid is None:
        _recusa('shapefile com projeção não reconhecida')
    return srid, leitura.origem


def _limites_da_camada(camada, limites):
    if len(camada) == 0:
        _recusa('arquivo sem feições')
    if len(camada) > limites.feicoes:
        _recusa('arquivo com feições acima do limite')
    campos = camada.fields
    if len(campos) > limites.campos:
        _recusa('arquivo com campos acima do limite')
    if any(len(nome) > limites.tamanho_nome_campo for nome in campos):
        _recusa('nome de campo acima do limite')
    return campos


def _erro_geometria(indice, geometria, familia, ctx):
    """Checa a geometria já lida e a leva ao sistema de guarda. Devolve o erro da feição, ou None se passou."""
    if not all(math.isfinite(c) for ponto in _pontos(geometria.tuple) for c in ponto):
        return f'feição {indice}: coordenada NaN ou infinita'
    if familia == 'poligono' and _anel_aberto(geometria):
        return f'feição {indice}: anel aberto'
    if ctx.srid != SRID_GUARDA:
        try:
            geometria.transform(ctx.alvo)
        except GDALException:  # coordenada finita fora do domínio da projeção de origem
            return f'feição {indice}: coordenada fora do domínio do sistema de origem'
    if not all(-180 <= x <= 180 and -90 <= y <= 90 for x, y in _pontos(geometria.tuple)):
        return f'feição {indice}: coordenada fora da faixa do sistema'
    return None


def _valores(indice, feicao, ctx):
    """Valores como vieram: do JSON quando é GeoJSON (o GDAL unificaria o tipo da coluna), do leitor no resto."""
    if ctx.propriedades is not None:
        original = ctx.propriedades[indice - 1]
        return {nome: _valor(original.get(nome)) for nome in ctx.campos}
    return {nome: _valor(feicao.get(nome)) for nome in ctx.campos}


def _processar_feicao(indice, feicao, ctx):
    try:
        bruta = feicao.geom
    except GDALException:
        return _Feicao(None, False, None, f'feição {indice}: geometria ausente')
    if bruta.empty:
        return _Feicao(None, False, None, f'feição {indice}: geometria vazia ou com coordenada NaN')
    geometria = OGRGeometry(memoryview(bruta.wkb), srs=ctx.origem_srs)
    familia = _familia(geometria)
    if familia is None:
        return _Feicao(None, False, None, f'feição {indice}: tipo de geometria sem suporte')
    zm = geometria.is_measured or geometria.coord_dim > 2
    if zm:
        geometria.set_measured(False)
        geometria.set_3d(False)
    erro = _erro_geometria(indice, geometria, familia, ctx)
    if erro:
        return _Feicao(familia, zm, None, erro)
    try:
        geos = geometria.geos
    except GEOSException:
        return _Feicao(familia, zm, None, f'feição {indice}: geometria recusada pelo GEOS')
    if not geos.valid:
        return _Feicao(familia, zm, None, f'feição {indice}: geometria inválida ({geos.valid_reason})')
    geos.srid = SRID_GUARDA
    return _Feicao(familia, zm, FeicaoPrevia(geos, _valores(indice, feicao, ctx)), None)


def _previa(leitura, origem, ctx, familias, feicoes, zm):
    transformacao = _transformacao(ctx.srid, ctx.origem_srs)
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
        sistema=f'EPSG:{ctx.srid} ({ctx.origem_srs.name})',
        origem_sistema=origem,
        transformacao=transformacao,
        avisos=tuple(avisos),
        extensao=(min(e[0] for e in extensoes), min(e[1] for e in extensoes), max(e[2] for e in extensoes), max(e[3] for e in extensoes)),
        feicoes=tuple(feicoes),
        campos=ctx.campos,
    )


def _ler(leitura, limites, prazo):
    camada = _abrir_camada(leitura)
    srid, origem = _sistema(leitura, camada)
    campos = _limites_da_camada(camada, limites)
    if leitura.propriedades is not None and len(leitura.propriedades) != len(camada):
        _recusa('GeoJSON com feições inconsistentes entre o JSON e a leitura')
    ctx = _Contexto(srid, SpatialReference(srid), SpatialReference(SRID_GUARDA), campos, leitura.propriedades)
    erros, familias, feicoes, zm = [], set(), [], 0
    for indice, feicao in enumerate(camada, start=1):
        if time.monotonic() > prazo:
            _recusa('tempo de leitura excedido')
        resultado = _processar_feicao(indice, feicao, ctx)
        if resultado.familia:
            familias.add(resultado.familia)
        zm += resultado.zm
        if resultado.erro:
            erros.append(resultado.erro)
        elif resultado.previa:
            feicoes.append(resultado.previa)
    if len(familias) > 1:
        erros.append('tipo misturado na mesma camada: ' + ', '.join(sorted(familias)))
    if erros:
        raise RecusaIngestao(erros)
    return _previa(leitura, origem, ctx, familias, feicoes, zm)


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
            srid, origem, propriedades = _precheck_geojson(dados)
            destino = _destino(tmp, 'geojson')
            destino.write_bytes(dados)
            leitura = _Leitura('geojson', destino, 'GeoJSON', srid, origem, propriedades)
        elif formato == 'kml':
            _precheck_kml(dados)
            destino = _destino(tmp, 'kml')
            destino.write_bytes(dados)
            leitura = _Leitura('kml', destino, 'KML', 4326, 'formato (WGS 84 assumido pelo KML)')
        else:
            _recusa('tipo de arquivo não suportado')
        return _ler(leitura, limites, prazo)
