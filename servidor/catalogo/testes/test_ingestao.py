"""Ingestão de envio (008 T2.1; R3 a R6, R16): caminho feliz e infeliz com fixtures sintéticas de cada formato.

Os arquivos são montados aqui em bytes (GeoJSON, KML, shapefile com struct), sem dado de cliente (R17)."""

import io
import json
import stat
import struct
import zipfile

import pytest
from django.contrib.gis.gdal import SpatialReference

from catalogo import ingestao
from catalogo.ingestao import Limites, RecusaIngestao, ingerir_envio
from catalogo.metadados import atributos_da_previa
from catalogo.models import Feicao

POLIGONO = [[(-48.30, -10.70), (-48.29, -10.70), (-48.29, -10.69), (-48.30, -10.69), (-48.30, -10.70)]]


def geojson(features, crs=None):
    objeto = {'type': 'FeatureCollection', 'features': features}
    if crs is not None:
        objeto['crs'] = {'type': 'name', 'properties': {'name': crs}}
    return json.dumps(objeto).encode('utf-8')


def ponto_geojson(x=-48.3, y=-10.7):
    return {'type': 'Feature', 'properties': {'nome': 'sintetico'}, 'geometry': {'type': 'Point', 'coordinates': [x, y]}}


def kml(*placemarks, cabecalho=''):
    return (cabecalho + '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>' + ''.join(placemarks) + '</Document></kml>').encode('utf-8')


def placemark_ponto(coordenadas):
    return f'<Placemark><name>sintetico</name><Point><coordinates>{coordenadas}</coordinates></Point></Placemark>'


def placemark_poligono(coordenadas):
    return (
        '<Placemark><Polygon><outerBoundaryIs><LinearRing><coordinates>'
        + coordenadas
        + '</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark>'
    )


def zip_com(entradas):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        for nome, dados in entradas.items():
            z.writestr(nome, dados)
    return buffer.getvalue()


def _cabecalho_shp(tipo_forma, comprimento_bytes):
    cab = struct.pack('>i', 9994) + b'\x00' * 20 + struct.pack('>i', comprimento_bytes // 2)
    cab += struct.pack('<ii', 1000, tipo_forma) + b'\x00' * 64
    return cab


def _conteudo_forma(tipo_forma, forma):
    if forma[0] == 'ponto':
        return struct.pack('<idd', 1, forma[1], forma[2])
    if forma[0] == 'ponto_z':
        return struct.pack('<idddd', 11, forma[1], forma[2], forma[3], 0.0)
    if forma[0] == 'ponto_m':
        return struct.pack('<iddd', 21, forma[1], forma[2], forma[3])
    aneis = forma[1]
    pontos = [p for anel in aneis for p in anel]
    partes, inicio = [], 0
    for anel in aneis:
        partes.append(inicio)
        inicio += len(anel)
    xs = [p[0] for p in pontos]
    ys = [p[1] for p in pontos]
    corpo = struct.pack('<i4d2i', tipo_forma, min(xs), min(ys), max(xs), max(ys), len(aneis), len(pontos))
    corpo += struct.pack('<%di' % len(partes), *partes)
    return corpo + b''.join(struct.pack('<dd', x, y) for x, y in pontos)


def shapefile(tipo_forma, formas, prj=None, sem=(), cpg=None, valor_dbf='sintetico'):
    """Zip com camada.shp, .shx, .dbf e .prj (e .cpg se dado); `sem` retira arquivos (ex.: ('prj',))."""
    conteudos = [_conteudo_forma(tipo_forma, f) for f in formas]
    corpo = b''.join(struct.pack('>ii', i + 1, len(c) // 2) + c for i, c in enumerate(conteudos))
    shp = _cabecalho_shp(tipo_forma, 100 + len(corpo)) + corpo
    registros_shx, deslocamento = b'', 100
    for c in conteudos:
        registros_shx += struct.pack('>ii', deslocamento // 2, len(c) // 2)
        deslocamento += 8 + len(c)
    shx = _cabecalho_shp(tipo_forma, 100 + len(registros_shx)) + registros_shx
    dbf = struct.pack('<BBBBIHH', 3, 126, 1, 1, len(formas), 32 + 32 + 1, 11) + b'\x00' * 20
    dbf += b'nome'.ljust(11, b'\x00') + b'C' + b'\x00' * 4 + struct.pack('<BB', 10, 0) + b'\x00' * 14
    dbf += b'\x0d'
    for _ in formas:
        dbf += b' ' + valor_dbf.encode(cpg.lower() if cpg else 'utf-8').ljust(10)[:10]
    dbf += b'\x1a'
    arquivos = {'camada.shp': shp, 'camada.shx': shx, 'camada.dbf': dbf}
    if prj is None:
        prj = SpatialReference(4674).wkt
    if prj:
        arquivos['camada.prj'] = prj.encode('utf-8')
    if cpg:
        arquivos['camada.cpg'] = cpg.encode('ascii')
    return zip_com({nome: dados for nome, dados in arquivos.items() if nome.rsplit('.', 1)[1] not in sem})


def arquivo(tmp_path, dados, nome='envio'):
    caminho = tmp_path / nome
    caminho.write_bytes(dados)
    return caminho


def recusa(caminho, limites=Limites()):
    with pytest.raises(RecusaIngestao) as excinfo:
        ingerir_envio(caminho, limites)
    return excinfo.value.erros


def coords(previa):
    return previa.feicoes[0].geometria.coords


# Caminho feliz

def test_geojson_sem_crs_e_lido_como_wgs84_assumido(tmp_path):
    previa = ingerir_envio(arquivo(tmp_path, geojson([ponto_geojson()])))
    assert previa.formato == 'geojson'
    assert previa.origem_sistema == 'formato (WGS 84 assumido pelo GeoJSON)'
    assert previa.transformacao == 'equivalencia'
    assert previa.contagem == 1
    assert previa.feicoes[0].geometria.srid == 4674
    assert coords(previa) == pytest.approx((-48.3, -10.7), abs=1e-9)
    assert previa.feicoes[0].valores == {'nome': 'sintetico'}


def test_geojson_com_crs_legado_e_lido_e_mostrado(tmp_path):
    previa = ingerir_envio(arquivo(tmp_path, geojson([ponto_geojson()], crs='urn:ogc:def:crs:EPSG::4674')))
    assert previa.origem_sistema == 'membro crs legado do GeoJSON'
    assert previa.sistema.startswith('EPSG:4674')
    assert previa.transformacao == 'nenhuma'


def test_kml_e_wgs84_e_altitude_e_descartada_com_aviso(tmp_path):
    previa = ingerir_envio(arquivo(tmp_path, kml(placemark_ponto('-48.3,-10.7,0'))))
    assert previa.formato == 'kml'
    assert previa.origem_sistema == 'formato (WGS 84 assumido pelo KML)'
    assert previa.transformacao == 'equivalencia'
    assert any('Z e M descartados' in aviso for aviso in previa.avisos)
    assert previa.feicoes[0].geometria.hasz is False
    assert coords(previa) == pytest.approx((-48.3, -10.7), abs=1e-9)


def test_kmz_e_extraido_e_lido_como_wgs84(tmp_path):
    previa = ingerir_envio(arquivo(tmp_path, zip_com({'doc.kml': kml(placemark_ponto('-48.3,-10.7'))})))
    assert previa.formato == 'kmz'
    assert previa.contagem == 1


def test_shapefile_sirgas_2000_com_prj_e_publicado_sem_transformacao(tmp_path):
    previa = ingerir_envio(arquivo(tmp_path, shapefile(1, [('ponto', -48.3, -10.7)])))
    assert previa.formato == 'shapefile'
    assert previa.origem_sistema == 'arquivo de projeção (.prj)'
    assert previa.transformacao == 'nenhuma'
    assert previa.sistema.startswith('EPSG:4674')


def test_shapefile_utm_e_reprojetado_com_ordem_de_eixo_longitude_latitude(tmp_path):
    prj = SpatialReference(31983).wkt
    previa = ingerir_envio(arquivo(tmp_path, shapefile(1, [('ponto', 700000.0, 8800000.0)], prj=prj)))
    x, y = coords(previa)
    assert -44 < x < -42  # 200 km a leste do meridiano central -45, na latitude de -10,8
    assert -11 < y < -10
    assert previa.transformacao == 'equivalencia'


def test_shapefile_sad69_e_aproximado_e_avisa(tmp_path):
    prj = SpatialReference(4618).wkt
    previa = ingerir_envio(arquivo(tmp_path, shapefile(1, [('ponto', -48.3, -10.7)], prj=prj)))
    assert previa.transformacao == 'aproximada'
    assert any('aproximada' in aviso for aviso in previa.avisos)


def test_shapefile_com_altitude_e_medida_e_descartado_com_aviso(tmp_path):
    previa = ingerir_envio(arquivo(tmp_path, shapefile(21, [('ponto_m', -48.3, -10.7, 7.0)])))
    assert any('Z e M descartados' in aviso for aviso in previa.avisos)
    assert previa.feicoes[0].geometria.hasz is False




def test_poligono_com_anel_fechado_e_aceito(tmp_path):
    coordenadas = ' '.join(f'{x},{y}' for x, y in POLIGONO[0])
    previa = ingerir_envio(arquivo(tmp_path, kml(placemark_poligono(coordenadas))))
    assert previa.tipo == 'poligono'


# Caminho infeliz: formato e sistema de referência



def test_shapefile_com_prj_que_nao_e_sistema_e_recusado(tmp_path):
    erros = recusa(arquivo(tmp_path, shapefile(1, [('ponto', -48.3, -10.7)], prj='isto nao e um sistema')))
    assert 'projeção não reconhecida' in erros[0]


def test_shapefile_incompleto_sem_dbf_e_recusado(tmp_path):
    erros = recusa(arquivo(tmp_path, shapefile(1, [('ponto', -48.3, -10.7)], sem=('dbf',))))
    assert 'falta .dbf' in erros[0]


def test_geojson_com_crs_desconhecido_e_recusado(tmp_path):
    erros = recusa(arquivo(tmp_path, geojson([ponto_geojson()], crs='urn:ogc:def:crs:EPSG::9999')))
    assert 'não reconhecido' in erros[0]


def test_geojson_com_crs_sem_codigo_epsg_e_recusado(tmp_path):
    erros = recusa(arquivo(tmp_path, geojson([ponto_geojson()], crs='sistema-inventado')))
    assert 'não reconhecido' in erros[0]


@pytest.mark.parametrize('texto', [b'{nao e json', b'{"a": "\xff"}', b'{"type": "FeatureCollection", "features": "x"}'])
def test_geojson_malformado_ou_sem_lista_de_feicoes_e_recusado(tmp_path, texto):
    assert recusa(arquivo(tmp_path, texto)) == ['GeoJSON inválido']


def test_tipo_nao_suportado_e_recusado(tmp_path):
    assert 'tipo de arquivo não suportado' in recusa(arquivo(tmp_path, b'texto puro sem formato'))[0]


def test_xml_que_nao_e_kml_e_recusado(tmp_path):
    assert 'XML que não é KML' in recusa(arquivo(tmp_path, b'<outro><x/></outro>'))[0]


def test_zip_sem_shapefile_nem_kml_e_recusado(tmp_path):
    assert 'sem shapefile nem KML' in recusa(arquivo(tmp_path, zip_com({'leia.txt': b'oi'})))[0]


def test_zip_corrompido_e_recusado(tmp_path):
    assert 'compactado inválido' in recusa(arquivo(tmp_path, b'PK\x03\x04lixo que nao e zip'))[0]


def test_caminho_que_nao_e_arquivo_comum_e_recusado(tmp_path):
    assert 'não é arquivo comum' in recusa(tmp_path)[0]


# Caminho infeliz: geometria e valores

@pytest.mark.parametrize('valor', ['NaN', 'Infinity', '-Infinity'])
def test_geojson_com_nan_ou_infinito_e_recusado(tmp_path, valor):
    texto = geojson([ponto_geojson()]).decode().replace('-48.3', valor)
    assert 'NaN ou infinita' in recusa(arquivo(tmp_path, texto.encode()))[0]


def test_kml_com_nan_e_recusado(tmp_path):
    assert 'NaN ou infinita' in recusa(arquivo(tmp_path, kml(placemark_ponto('NaN,-10.7'))))[0]


def test_kml_com_infinito_e_recusado(tmp_path):
    assert 'NaN ou infinita' in recusa(arquivo(tmp_path, kml(placemark_ponto('Infinity,-10.7'))))[0]


def test_kml_com_coordenada_nao_numerica_e_recusado(tmp_path):
    assert 'não numérica' in recusa(arquivo(tmp_path, kml(placemark_ponto('abc,-10.7'))))[0]


# DTD e entidade (spec 011 R5): a regex de _proibe_dtd é a primeira barreira; o analisador (defusedxml, forbid_dtd) é a segunda.
DTD_COM_ENTIDADE = (
    b'<?xml version="1.0"?><!DOCTYPE kml [<!ENTITY nome "sintetico">]>'
    b'<kml xmlns="http://www.opengis.net/kml/2.2"><Document><Placemark><name>&nome;</name></Placemark></Document></kml>'
)


def test_kml_com_doctype_e_entidade_e_recusado(tmp_path):
    assert 'KML com DOCTYPE ou entidade recusado' in recusa(arquivo(tmp_path, DTD_COM_ENTIDADE))[0]


def test_kml_com_doctype_e_recusado_pelo_analisador_sem_a_regex(monkeypatch):
    monkeypatch.setattr(ingestao, '_proibe_dtd', lambda dados: None)
    with pytest.raises(RecusaIngestao) as excinfo:
        ingestao._precheck_kml(DTD_COM_ENTIDADE)
    assert excinfo.value.erros == ['KML com DOCTYPE ou entidade recusado']


def test_kml_com_doctype_em_utf16_e_recusado(tmp_path):
    assert 'KML fora de UTF-8' in recusa(arquivo(tmp_path, DTD_COM_ENTIDADE.decode().encode('utf-16')))[0]


def test_kml_valido_passa_pelo_analisador_sem_erro():
    assert ingestao._precheck_kml(kml(placemark_ponto('-48.3,-10.7'))) is None


def test_kml_malformado_e_recusado(tmp_path):
    assert 'KML inválido' in recusa(arquivo(tmp_path, b'<kml><Document>'))[0]


def test_shapefile_com_nan_e_recusado_sem_publicar(tmp_path):
    erros = recusa(arquivo(tmp_path, shapefile(1, [('ponto', float('nan'), -10.7)])))
    assert 'NaN' in erros[0]  # o GDAL pode ler como vazia ou como NaN: a mensagem cita NaN nos dois casos


def test_shapefile_com_infinito_e_recusado(tmp_path):
    assert 'NaN ou infinita' in recusa(arquivo(tmp_path, shapefile(1, [('ponto', float('inf'), -10.7)])))[0]


def test_coordenada_fora_da_faixa_e_recusada(tmp_path):
    assert 'fora da faixa' in recusa(arquivo(tmp_path, geojson([ponto_geojson(x=200.0)])))[0]


def test_anel_aberto_em_geojson_e_recusado(tmp_path):
    anel = [[-48.3, -10.7], [-48.29, -10.7], [-48.29, -10.69], [-48.3, -10.69]]
    feicao = {'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Polygon', 'coordinates': [anel]}}
    assert 'anel aberto' in recusa(arquivo(tmp_path, geojson([feicao])))[0]


def test_anel_aberto_em_shapefile_e_recusado_antes_do_geos(tmp_path):
    aberto = [[(-48.3, -10.7), (-48.29, -10.7), (-48.29, -10.69), (-48.3, -10.69)]]
    assert 'anel aberto' in recusa(arquivo(tmp_path, shapefile(5, [('poligono', aberto)])))[0]


def test_geometria_invalida_e_recusada_com_motivo_do_geos(tmp_path):
    borboleta = [[(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)]]
    feicao = {'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Polygon', 'coordinates': [[list(p) for p in borboleta[0]]]}}
    assert 'geometria inválida' in recusa(arquivo(tmp_path, geojson([feicao])))[0]


def test_geometria_nula_e_recusada(tmp_path):
    feicao = {'type': 'Feature', 'properties': {}, 'geometry': None}
    assert 'geometria ausente' in recusa(arquivo(tmp_path, geojson([feicao])))[0]


def test_tipo_misturado_na_mesma_camada_e_recusado(tmp_path):
    misto = kml(placemark_ponto('-48.3,-10.7'), placemark_poligono(' '.join(f'{x},{y}' for x, y in POLIGONO[0])))
    assert 'tipo misturado' in recusa(arquivo(tmp_path, misto))[0]


def test_geometria_de_colecao_e_recusada_por_tipo(tmp_path):
    colecao = {'type': 'Feature', 'properties': {}, 'geometry': {'type': 'GeometryCollection', 'geometries': [{'type': 'Point', 'coordinates': [1, 2]}]}}
    assert 'tipo de geometria sem suporte' in recusa(arquivo(tmp_path, geojson([colecao])))[0]


def test_camada_vazia_e_recusada(tmp_path):
    assert 'sem feições' in recusa(arquivo(tmp_path, geojson([])))[0]


@pytest.mark.parametrize('crs', ['urn:ogc:def:crs:OGC:1.3:CRS84', 'urn:ogc:def:crs:OGC::CRS84'])
def test_geojson_com_crs84_legado_e_lido_como_wgs84_com_aviso(tmp_path, crs):
    previa = ingerir_envio(arquivo(tmp_path, geojson([ponto_geojson()], crs=crs)))
    assert previa.origem_sistema == 'membro crs legado do GeoJSON (CRS84 lido como WGS 84)'
    assert previa.sistema.startswith('EPSG:4326')
    assert previa.transformacao == 'equivalencia'
    assert any('é legado' in aviso for aviso in previa.avisos)
    assert coords(previa) == pytest.approx((-48.3, -10.7), abs=1e-9)


def test_geojson_com_crs_epsg_legado_tambem_avisa_que_e_legado(tmp_path):
    previa = ingerir_envio(arquivo(tmp_path, geojson([ponto_geojson()], crs='urn:ogc:def:crs:EPSG::4674')))
    assert any('é legado' in aviso for aviso in previa.avisos)


def test_nome_de_campo_acima_do_limite_e_recusado(tmp_path):
    erros = recusa(arquivo(tmp_path, shapefile(1, [('ponto', -48.3, -10.7)])), Limites(tamanho_nome_campo=3))
    assert 'nome de campo acima do limite' in erros[0]


def test_nome_de_campo_no_limite_e_aceito(tmp_path):
    previa = ingerir_envio(arquivo(tmp_path, shapefile(1, [('ponto', -48.3, -10.7)])), Limites(tamanho_nome_campo=4))
    assert previa.contagem == 1


@pytest.mark.django_db
def test_recusa_nao_altera_contagem_de_linhas(tmp_path):
    antes = Feicao.objects.count()
    recusa(arquivo(tmp_path, geojson([ponto_geojson(x=200.0)])))
    assert Feicao.objects.count() == antes


class _ArquivoQueDescompactaMais:
    """Leitor de entrada que entrega mais bytes do que o cabeçalho declara: a contagem tem de ser pelo real."""

    def open(self, info):
        return io.BytesIO(b'0' * (3 * 1024 * 1024))


def test_descompressao_conta_bytes_reais_quando_o_cabecalho_mente(tmp_path):
    from catalogo.ingestao import _extrair

    origem, destino = _ArquivoQueDescompactaMais(), tmp_path / 'x.kml'
    with pytest.raises(RecusaIngestao) as excinfo:
        _extrair(origem, None, destino, 1024 * 1024)
    assert 'descompacta acima do limite' in excinfo.value.erros[0]


def test_descompressao_dentro_do_orcamento_devolve_o_restante(tmp_path):
    from catalogo.ingestao import _extrair

    restante = _extrair(_ArquivoQueDescompactaMais(), None, tmp_path / 'x.kml', 10 * 1024 * 1024)
    assert restante == 10 * 1024 * 1024 - 3 * 1024 * 1024


# Tolerância A2 (spec 008): mesma origem e destino dá geometria idêntica; entre sistemas, área dentro de 0,001 % (T0.3)


def test_mesma_origem_e_destino_geometria_identica(tmp_path):
    origem = [(-48.30, -10.70), (-48.29, -10.70), (-48.29, -10.69), (-48.30, -10.69), (-48.30, -10.70)]
    previa = ingerir_envio(arquivo(tmp_path, shapefile(5, [('poligono', [origem])])))
    assert previa.transformacao == 'nenhuma'
    assert previa.feicoes[0].geometria.coords[0] == tuple(origem)


@pytest.mark.django_db
def test_area_entre_sistemas_conferida_por_102033_dentro_de_0_001_por_cento(tmp_path):
    from django.db import connection

    anel_utm = [(700000.0, 8800000.0), (701000.0, 8800000.0), (701000.0, 8801000.0), (700000.0, 8801000.0), (700000.0, 8800000.0)]
    previa = ingerir_envio(arquivo(tmp_path, shapefile(5, [('poligono', [anel_utm])], prj=SpatialReference(31983).wkt)))
    ewkt = previa.feicoes[0].geometria.ewkt
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT ST_Area(ST_GeomFromEWKT(%s)::geography), ST_Area(ST_Transform(ST_GeomFromEWKT(%s), 102033))',
            [ewkt, ewkt],
        )
        area_geografia, area_igual = cursor.fetchone()
    assert area_geografia > 0
    assert abs(area_geografia - area_igual) / area_geografia <= 0.00001


def test_feicoes_que_se_sobrepoem_sao_aceitas_e_nao_cortadas(tmp_path):
    # R5: a sobreposição permanece como está; nada é cortado, simplificado nem corrigido.
    quadrado_a = [(-48.30, -10.70), (-48.29, -10.70), (-48.29, -10.69), (-48.30, -10.69), (-48.30, -10.70)]
    quadrado_b = [(-48.295, -10.695), (-48.285, -10.695), (-48.285, -10.685), (-48.295, -10.685), (-48.295, -10.695)]
    previa = ingerir_envio(arquivo(tmp_path, shapefile(5, [('poligono', [quadrado_a]), ('poligono', [quadrado_b])])))
    assert previa.contagem == 2
    assert previa.feicoes[0].geometria.coords[0] == tuple(quadrado_a)
    assert previa.feicoes[1].geometria.coords[0] == tuple(quadrado_b)
    assert previa.feicoes[0].geometria.intersects(previa.feicoes[1].geometria)


def test_feicoes_no_limite_sao_aceitas(tmp_path):
    previa = ingerir_envio(arquivo(tmp_path, geojson([ponto_geojson(), ponto_geojson()])), Limites(feicoes=2))
    assert previa.contagem == 2


def test_feicoes_acima_do_limite_sao_recusadas(tmp_path):
    erros = recusa(arquivo(tmp_path, geojson([ponto_geojson(), ponto_geojson()])), Limites(feicoes=1))
    assert 'feições acima do limite' in erros[0]


def test_campos_acima_do_limite_sao_recusados(tmp_path):
    erros = recusa(arquivo(tmp_path, geojson([ponto_geojson()])), Limites(campos=0))
    assert 'campos acima do limite' in erros[0]


# Revisão PR #68 (A, B, C)


@pytest.mark.parametrize('cpg', ['UTF-8', 'ISO-8859-1'])
def test_cpg_declarado_e_preservado_e_acento_sai_certo(tmp_path, cpg):
    # Achado A: o .cpg (codificação do dbf) era descartado; sem ele o GDAL lê os acentos com outra codificação.
    previa = ingerir_envio(arquivo(tmp_path, shapefile(1, [('ponto', -48.3, -10.7)], cpg=cpg, valor_dbf='São Paulo')))
    assert previa.feicoes[0].valores['nome'] == 'São Paulo'


def ponto_com_propriedades(propriedades, x=-48.3):
    return {'type': 'Feature', 'properties': propriedades, 'geometry': {'type': 'Point', 'coordinates': [x, -10.7]}}


def test_geojson_com_tipos_mistos_na_coluna_preserva_os_valores_originais(tmp_path):
    # Achado B: o GDAL unifica o esquema da coluna e entregaria '1' em vez de 1.
    envio = geojson([ponto_com_propriedades({'codigo': 1}), ponto_com_propriedades({'codigo': 'abc'}, x=-48.2)])
    previa = ingerir_envio(arquivo(tmp_path, envio))
    assert [feicao.valores['codigo'] for feicao in previa.feicoes] == [1, 'abc']
    assert atributos_da_previa(previa)[0].tipo == 'misto'


def test_coordenada_finita_fora_do_dominio_da_projecao_vira_recusa_por_feicao(tmp_path):
    # Achado C: 1e100 é finito, mas o GDAL não transforma em EPSG:31983; a exceção não pode vazar.
    envio = geojson([ponto_com_propriedades({'codigo': 'x'}, x=1e100)], crs='urn:ogc:def:crs:EPSG::31983')
    erros = recusa(arquivo(tmp_path, envio))
    assert erros[0].startswith('feição 1:')


def test_geojson_com_lista_e_objeto_preserva_a_estrutura_do_json(tmp_path):
    # Achado K: lista e objeto viravam str() do Python ('[1, None, True]'); ficam como vieram no JSON.
    envio = geojson([ponto_com_propriedades({'lista': [1, None, True], 'objeto': {'n': 2}})])
    previa = ingerir_envio(arquivo(tmp_path, envio))
    assert previa.feicoes[0].valores == {'lista': [1, None, True], 'objeto': {'n': 2}}
    assert {atributo.nome: atributo.tipo for atributo in atributos_da_previa(previa)} == {'lista': 'estrutura', 'objeto': 'estrutura'}


def entradas_do_zip(dados):
    with zipfile.ZipFile(io.BytesIO(dados)) as z:
        return {info.filename: z.read(info) for info in z.infolist()}


def test_shapefile_com_prj_de_outra_pasta_nao_substitui_o_da_pasta_do_shp(tmp_path):
    # Achado J: o .prj de outra pasta (UTM) não pode entrar no lugar do .prj da pasta do .shp.
    de_a = entradas_do_zip(shapefile(1, [('ponto', -48.3, -10.7)]))
    de_b = entradas_do_zip(shapefile(1, [('ponto', 700000.0, 8800000.0)], prj=SpatialReference(31983).wkt))
    misto = zip_com({**{f'a/{nome}': dados for nome, dados in de_a.items()}, 'b/camada.prj': de_b['camada.prj']})
    previa = ingerir_envio(arquivo(tmp_path, misto))
    assert previa.sistema.startswith('EPSG:4674')
    assert coords(previa) == pytest.approx((-48.3, -10.7), abs=1e-9)


def test_shapefile_com_dbf_de_outra_pasta_e_recusado_como_incompleto(tmp_path):
    de_a = entradas_do_zip(shapefile(1, [('ponto', -48.3, -10.7)]))
    misto = zip_com({'a/camada.shp': de_a['camada.shp'], 'a/camada.shx': de_a['camada.shx'], 'a/camada.prj': de_a['camada.prj'], 'b/camada.dbf': de_a['camada.dbf']})
    assert recusa(arquivo(tmp_path, misto)) == ['shapefile incompleto: falta .dbf']


def test_shapefile_com_componente_repetido_na_mesma_pasta_e_recusado(tmp_path):
    de_a = entradas_do_zip(shapefile(1, [('ponto', -48.3, -10.7)]))
    repetido = zip_com({**{f'a/{nome}': dados for nome, dados in de_a.items()}, 'a/camada.DBF': de_a['camada.dbf']})
    assert recusa(arquivo(tmp_path, repetido)) == ['shapefile com componente repetido na mesma pasta']


def test_dbf_homonimo_em_outra_pasta_nao_substitui_o_da_pasta_do_shp(tmp_path):
    # Achado 5 (J): dois camada.dbf em pastas diferentes; vale só o da pasta do .shp.
    de_a = entradas_do_zip(shapefile(1, [('ponto', -48.3, -10.7)]))
    de_b = entradas_do_zip(shapefile(1, [('ponto', -48.3, -10.7)], valor_dbf='outro'))
    misto = zip_com({**{f'a/{nome}': dados for nome, dados in de_a.items()}, 'b/camada.dbf': de_b['camada.dbf']})
    previa = ingerir_envio(arquivo(tmp_path, misto))
    assert previa.feicoes[0].valores['nome'] == 'sintetico'


def test_abrir_fonte_com_driver_certo_devolve_a_camada(tmp_path):
    from catalogo.ingestao import _abrir_fonte
    caminho = arquivo(tmp_path, geojson([ponto_geojson()]))
    assert len(_abrir_fonte(caminho, 'GeoJSON')) == 1


def test_abrir_fonte_que_o_gdal_nao_abre_levanta_mensagem_em_portugues(tmp_path, monkeypatch):
    # O errcheck do Django lança antes do nosso `if not ponteiro` quando o GDAL falha; o ramo nosso é forçado aqui.
    from django.contrib.gis.gdal import GDALException
    from django.contrib.gis.gdal.prototypes import ds as capi
    from catalogo.ingestao import _abrir_fonte
    monkeypatch.setattr(capi, 'open_ds', lambda *args: None)
    caminho = tmp_path / 'nao_abre.geojson'
    with pytest.raises(GDALException, match=r'^Não foi possível abrir a fonte de dados em ".*nao_abre\.geojson"$'):
        _abrir_fonte(caminho, 'GeoJSON')


def test_topojson_gravado_como_geojson_e_recusado(tmp_path):
    # Achado 3: o DataSource do Django não limita o driver; aqui só o driver GeoJSON pode abrir.
    topo = {'type': 'Topology', 'arcs': [[[0, 0], [1, 1]]], 'objects': {'l': {'type': 'LineString', 'arcs': [0]}}}
    assert recusa(arquivo(tmp_path, json.dumps(topo).encode())) == ['não foi possível ler o arquivo como geojson']


def zip_deflate_com_bloco_invalido(entradas):
    # Achado do Codex: o primeiro bloco DEFLATE recebe BTYPE=11 (inválido), com cabeçalho local e CRC intactos.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for nome, dados in entradas.items():
            z.writestr(nome, dados)
    dados = bytearray(buffer.getvalue())
    tamanho_nome, tamanho_extra = struct.unpack('<HH', dados[26:30])
    dados[30 + tamanho_nome + tamanho_extra] |= 0x06
    return bytes(dados)


def test_kmz_com_deflate_corrompido_e_recusado_como_compactado_invalido(tmp_path):
    corrompido = zip_deflate_com_bloco_invalido({'doc.kml': kml(placemark_ponto('-48.3,-10.7'))})
    assert recusa(arquivo(tmp_path, corrompido)) == ['compactado inválido ou criptografado']


def test_shapefile_com_deflate_corrompido_e_recusado_como_compactado_invalido(tmp_path):
    de_a = entradas_do_zip(shapefile(1, [('ponto', -48.3, -10.7)]))
    assert recusa(arquivo(tmp_path, zip_deflate_com_bloco_invalido(de_a))) == ['compactado inválido ou criptografado']


def test_kmz_com_crc_ruim_e_recusado_como_compactado_invalido(tmp_path):
    # Entrada armazenada (sem compressão): byte alterado no conteúdo quebra o CRC-32 do zipfile.
    dados = bytearray(zip_com({'doc.kml': kml(placemark_ponto('-48.3,-10.7'))}))
    tamanho_nome, tamanho_extra = struct.unpack('<HH', dados[26:30])
    dados[30 + tamanho_nome + tamanho_extra + 5] ^= 0x01
    assert recusa(arquivo(tmp_path, bytes(dados))) == ['compactado inválido ou criptografado']


PROFUNDIDADE_EXCEDIDA = ['GeoJSON com aninhamento acima do limite de profundidade']


def test_json_muito_aninhado_e_recusado_por_profundidade(tmp_path):
    # Achado 4: aninhamento fundo. Conforme a plataforma, o json lança RecursionError (pilha C) ou devolve a estrutura;
    # a recusa é a mesma nos dois casos (spec 011, CI 3.15 x86_64 divergiu do arm64).
    profundo = b'{"a": ' + b'[' * 100000 + b']' * 100000 + b'}'
    assert recusa(arquivo(tmp_path, profundo)) == PROFUNDIDADE_EXCEDIDA


def test_parser_que_estoura_a_pilha_e_recusado_por_profundidade(tmp_path, monkeypatch):
    def estoura_a_pilha(*_args, **_kwargs):
        raise RecursionError('maximum recursion depth exceeded')

    monkeypatch.setattr(ingestao.json, 'loads', estoura_a_pilha)
    assert recusa(arquivo(tmp_path, b'{"type": "FeatureCollection"}')) == PROFUNDIDADE_EXCEDIDA


def test_parser_que_devolve_estrutura_funda_e_recusado_por_profundidade(tmp_path, monkeypatch):
    funda = {}
    atual = funda
    for _ in range(100):  # 100 níveis: acima do limite de 64
        atual['a'] = {}
        atual = atual['a']
    monkeypatch.setattr(ingestao.json, 'loads', lambda *_args, **_kwargs: funda)
    assert recusa(arquivo(tmp_path, b'{"type": "FeatureCollection"}')) == PROFUNDIDADE_EXCEDIDA

