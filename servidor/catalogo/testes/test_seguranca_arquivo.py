"""Segurança do envio (008 T2.5; R3, R16): arquivo hostil recusado, com a mensagem da nossa checagem.

Os casos vêm de test_ingestao.py e de fixtures sintéticas (R17). Cada recusa é tentada com arquivo real, não com mock."""

import io
import stat
import zipfile

import pytest

from catalogo.ingestao import Limites, RecusaIngestao, ingerir_envio
from catalogo.testes.test_ingestao import arquivo, geojson, kml, placemark_ponto, ponto_geojson, recusa, shapefile, zip_com


def bomba_de_entidades(profundidade=9):
    """Billion laughs: cada entidade repete a anterior dez vezes. Recusada antes de qualquer expansão."""
    definicoes = ['<!ENTITY lol0 "lol">']
    for nivel in range(1, profundidade):
        definicoes.append(f'<!ENTITY lol{nivel} "' + f'&lol{nivel - 1};' * 10 + '">')
    return ('<!DOCTYPE kml [' + ''.join(definicoes) + ']>').encode() + kml(placemark_ponto('&lol8;,-10.7'))


# Tipo pelo conteúdo, não pela extensão

def test_tipo_vem_do_conteudo_e_nao_da_extensao(tmp_path):
    from catalogo.ingestao import ingerir_envio

    assert ingerir_envio(arquivo(tmp_path, geojson([ponto_geojson()]), nome='mentira.kml')).formato == 'geojson'
    assert ingerir_envio(arquivo(tmp_path, zip_com({'doc.kml': kml(placemark_ponto('1,2'))}), nome='mentira.geojson')).formato == 'kmz'


def test_zip_com_extensao_de_kml_e_lido_pelo_conteudo_zip(tmp_path):
    from catalogo.ingestao import ingerir_envio

    previa = ingerir_envio(arquivo(tmp_path, shapefile(1, [('ponto', -48.3, -10.7)]), nome='nao-e-kml.kml'))
    assert previa.formato == 'shapefile'


# Shapefile sem projeção

@pytest.mark.django_db
def test_shapefile_sem_prj_e_recusado_antes_de_gravar(tmp_path):
    from catalogo.models import Feicao

    antes = Feicao.objects.count()
    erros = recusa(arquivo(tmp_path, shapefile(1, [('ponto', -48.3, -10.7)], prj=None, sem=('prj',))))
    assert 'sem arquivo de projeção' in erros[0]
    assert Feicao.objects.count() == antes


# KML com entidade externa e bomba de entidades

def test_kml_com_doctype_e_recusado_pelo_nosso_codigo(tmp_path):
    hostil = b'<!DOCTYPE kml [<!ENTITY e SYSTEM "file:///etc/passwd">]>' + kml(placemark_ponto('-48.3,-10.7'))
    assert 'DOCTYPE ou entidade recusado' in recusa(arquivo(tmp_path, hostil))[0]


def test_kml_com_entidade_interna_e_recusado(tmp_path):
    hostil = b'<!DOCTYPE kml [<!ENTITY a "x">]>' + kml(placemark_ponto('-48.3,-10.7'))
    assert 'DOCTYPE ou entidade recusado' in recusa(arquivo(tmp_path, hostil))[0]


def test_kml_com_entidade_externa_http_e_recusado(tmp_path):
    hostil = b'<!DOCTYPE kml [<!ENTITY e SYSTEM "http://exemplo.test/x">]>' + kml(placemark_ponto('-48.3,-10.7'))
    assert 'DOCTYPE ou entidade recusado' in recusa(arquivo(tmp_path, hostil))[0]


def test_bomba_de_entidades_billion_laughs_e_recusada_sem_expandir(tmp_path):
    assert 'DOCTYPE ou entidade recusado' in recusa(arquivo(tmp_path, bomba_de_entidades()))[0]


# Caminho perigoso no compactado

@pytest.mark.parametrize('nome', ['../fora.kml', '/abs/fora.kml', 'C:/fora.kml', 'pasta/../../fora.kml', 'pasta\\..\\..\\fora.kml'])
def test_caminho_perigoso_no_compactado_e_recusado(tmp_path, nome):
    erros = recusa(arquivo(tmp_path, zip_com({nome: kml(placemark_ponto('1,2'))})))
    assert 'caminho fora do envio' in erros[0]


def test_ligacao_simbolica_no_compactado_e_recusada(tmp_path):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        info = zipfile.ZipInfo('doc.kml')
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        z.writestr(info, b'/etc/passwd')
    assert 'ligação simbólica' in recusa(arquivo(tmp_path, buffer.getvalue()))[0]


# Compactado dentro de compactado, entradas, descompressão, tamanho e tempo

def test_compactado_dentro_de_compactado_e_recusado(tmp_path):
    interno = zip_com({'x.txt': b'y'})
    entradas = {'camada.shp': interno, 'camada.shx': b'', 'camada.dbf': b'', 'camada.prj': b'x'}
    assert 'compactado dentro de compactado' in recusa(arquivo(tmp_path, zip_com(entradas)))[0]


def test_compactado_com_entradas_acima_do_limite_e_recusado(tmp_path):
    erros = recusa(arquivo(tmp_path, shapefile(1, [('ponto', -48.3, -10.7)])), Limites(entradas=3))
    assert 'entradas acima do limite' in erros[0]


def test_compactado_que_descompacta_acima_do_limite_e_recusado(tmp_path):
    erros = recusa(arquivo(tmp_path, shapefile(1, [('ponto', -48.3, -10.7)])), Limites(descompactado_bytes=10))
    assert 'descompacta acima do limite' in erros[0]


def test_descompressao_enorme_declarada_e_recusada_mesmo_com_arquivo_pequeno(tmp_path):
    # 5 MB de zeros comprimidos viram poucos KB no envio; o limite de descompactação tem de contar o tamanho real.
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('doc.kml', b'0' * (5 * 1024 * 1024))
    enorme = buffer.getvalue()
    assert len(enorme) < 100 * 1024
    erros = recusa(arquivo(tmp_path, enorme), Limites(descompactado_bytes=1024 * 1024))
    assert 'descompacta acima do limite' in erros[0]


def test_arquivo_acima_do_limite_de_tamanho_e_recusado(tmp_path):
    assert 'acima do limite de tamanho' in recusa(arquivo(tmp_path, geojson([ponto_geojson()])), Limites(tamanho_bytes=10))[0]


def test_tempo_de_leitura_excedido_e_recusado(tmp_path):
    erros = recusa(arquivo(tmp_path, geojson([ponto_geojson()])), Limites(tempo_segundos=-1))
    assert 'tempo de leitura excedido' in erros[0]


# Revisão PR #68 (D): KML em UTF-16 contornava a checagem de DOCTYPE feita em bytes ASCII.


def _kml_em(codificacao, texto):
    return texto.encode(codificacao)


KML_VALIDO = '<?xml version="1.0" encoding="UTF-8"?>' + kml(placemark_ponto('-48.3,-10.7')).decode('utf-8')
KML_COM_DTD = '<!DOCTYPE kml [<!ENTITY a "x">]>' + kml(placemark_ponto('-48.3,-10.7')).decode('utf-8')
BOMBA_TEXTO = bomba_de_entidades().decode('utf-8')
BOM_UTF16_BE = bytes([0xFE, 0xFF])


@pytest.mark.parametrize('codificacao', ['utf-16', 'utf-16-le', 'utf-16-be'])
@pytest.mark.parametrize('texto', [KML_COM_DTD, BOMBA_TEXTO, KML_VALIDO])
def test_kml_que_nao_e_utf8_e_recusado_antes_de_qualquer_leitura_xml(tmp_path, codificacao, texto):
    erros = recusa(arquivo(tmp_path, _kml_em(codificacao, texto)))
    assert erros == ['KML fora de UTF-8 (zeros no arquivo) recusado']


def test_kml_utf16_com_bom_big_endian_e_recusado(tmp_path):
    erros = recusa(arquivo(tmp_path, BOM_UTF16_BE + BOMBA_TEXTO.encode('utf-16-be')))
    assert erros == ['KML fora de UTF-8 (zeros no arquivo) recusado']


def test_kmz_com_kml_utf16_e_recusado(tmp_path):
    erros = recusa(arquivo(tmp_path, zip_com({'doc.kml': _kml_em('utf-16', KML_COM_DTD)})))
    assert erros == ['KML fora de UTF-8 (zeros no arquivo) recusado']


def test_kml_utf8_valido_continua_aceito(tmp_path):
    previa = ingerir_envio(arquivo(tmp_path, KML_VALIDO.encode('utf-8')))
    assert previa.contagem == 1


# Revisão PR #68 (E): o caminho de escrita sai de um ponto só e a extensão vem de lista fixa.


def test_destino_de_escrita_so_aceita_extensao_da_lista_fixa(tmp_path):
    from catalogo.ingestao import _destino

    with pytest.raises(RecusaIngestao, match='extensão de leitura fora da lista'):
        _destino(tmp_path, '../x')


def test_nome_do_envio_nao_muda_o_destino_da_leitura(tmp_path):
    # O arquivo enviado é lido pelo conteúdo; o nome (aqui 'fora.kml') não define onde nada é escrito.
    previa = ingerir_envio(arquivo(tmp_path, geojson([ponto_geojson()]), nome='fora.kml'))
    assert previa.formato == 'geojson'
    assert not (tmp_path / 'fora.kml.geojson').exists()



# Profundidade de aninhamento (R16): o GeoJSON com a propriedade `aninhado` tem 7 níveis (objeto, lista, objeto,
# objeto de propriedades, lista, lista, lista). O limite é inclusivo: 7 passa, 6 recusa.

def ponto_aninhado():
    feicao = ponto_geojson()
    feicao['properties']['aninhado'] = [[[1]]]
    return feicao


def test_profundidade_conta_o_caminho_mais_fundo_sem_recursao():
    from catalogo.ingestao import _profundidade
    assert _profundidade({'a': [{'b': []}]}) == 4  # objeto, lista, objeto e a lista vazia (que também é nível)
    assert _profundidade({}) == 1
    assert _profundidade([]) == 1
    assert _profundidade(1) == 0


def test_profundidade_de_colecao_larga_nao_empilha_os_filhos():
    from catalogo.ingestao import _profundidade
    assert _profundidade([[] for _ in range(100_000)]) == 2


def test_profundidade_de_objeto_largo_com_um_ramo_fundo_e_o_do_ramo():
    from catalogo.ingestao import _profundidade
    # raiz (1), 'ramo' (2), 'fundo' com quatro listas aninhadas (3 a 6): a largura de 100_000 chaves escalares não conta.
    objeto = {**{f'k{i}': i for i in range(100_000)}, 'ramo': {'fundo': [[[[]]]]}}
    assert _profundidade(objeto) == 6


def test_geojson_no_limite_de_profundidade_e_aceito(tmp_path):
    previa = ingerir_envio(arquivo(tmp_path, geojson([ponto_aninhado()])), Limites(profundidade_aninhamento=7))
    assert previa.contagem == 1


def test_geojson_acima_do_limite_de_profundidade_e_recusado_antes_de_ler_feicoes(tmp_path):
    erros = recusa(arquivo(tmp_path, geojson([ponto_aninhado()])), Limites(profundidade_aninhamento=6))
    assert erros == ['GeoJSON com aninhamento acima do limite de profundidade']
