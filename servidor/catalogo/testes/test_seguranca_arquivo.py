"""Segurança do envio (008 T2.5; R3, R16): arquivo hostil recusado, com a mensagem da nossa checagem.

Os casos vêm de test_ingestao.py e de fixtures sintéticas (R17). Cada recusa é tentada com arquivo real, não com mock."""

import io
import stat
import zipfile

import pytest

from catalogo.ingestao import Limites
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
