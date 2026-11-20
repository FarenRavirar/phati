"""Envio em prévia (008 T2.4; R12, R13, R15, R16): criação ponta a ponta, recusa sem arquivo nem linha, permissão e RLS.

Gravado pela conexão padrão e lido pelo papel `app` (RLS), como em test_rls.py. Dado sintético (R17)."""

import hashlib
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from django.core.exceptions import PermissionDenied
from django.db import connections, transaction

from catalogo import envios, original
from catalogo.ingestao import Limites, RecusaIngestao
from catalogo.models import EnvioCamada, Feicao, VersaoCamada
from catalogo.testes.test_ingestao import geojson, kml, placemark_poligono, placemark_ponto, ponto_geojson, shapefile, zip_com
from permissao.contexto import fixar_contexto

pytestmark = pytest.mark.django_db(transaction=True, databases=['default', 'app'])


@pytest.fixture
def camadas(settings, tmp_path):
    settings.CAMADAS_DIR = tmp_path / 'camadas'
    settings.CAMADAS_DIR.mkdir()
    return settings.CAMADAS_DIR


@pytest.fixture
def mundo(catalogo_da_corrida, cenario, fabrica_pessoa, conceder_direto):
    """Operador com `publicar_camada` pela concessão do cargo de administrador da empresa X (não pela plataforma)."""
    m = SimpleNamespace(x=cenario.x, f1=cenario.f1, f2=cenario.f2)
    m.operador = fabrica_pessoa('Operadora Sintética')
    conceder_direto(m.operador, cenario.cargos_x['administrador'], cenario.x)
    m.sem_permissao = fabrica_pessoa('Sem Permissao')
    return m


def _envio_valido():
    return geojson([ponto_geojson()])


def _kml_hostil():
    return b'<!DOCTYPE kml [<!ENTITY e SYSTEM "file:///etc/passwd">]><kml><Document/></kml>'


def _arquivos(camadas):
    return sorted(p.name for p in camadas.iterdir())


def test_envio_valido_cria_linha_com_nome_interno_e_hash(camadas, mundo):
    envio = envios.criar_envio(mundo.operador, mundo.f1, _envio_valido())
    assert envio.hash_original == hashlib.sha256(_envio_valido()).hexdigest()
    assert envio.arquivo_temporario in _arquivos(camadas)
    assert original.ler(envio.arquivo_temporario, envio.hash_original) == _envio_valido()


def test_kml_hostil_e_recusado_sem_arquivo_e_sem_linha(camadas, mundo):
    antes = EnvioCamada.objects.count()
    hostil = _kml_hostil()
    with pytest.raises(RecusaIngestao):
        envios.criar_envio(mundo.operador, mundo.f1, hostil)
    assert _arquivos(camadas) == []
    assert EnvioCamada.objects.count() == antes


def test_shapefile_sem_prj_e_recusado_sem_arquivo_e_sem_linha(camadas, mundo):
    antes = EnvioCamada.objects.count()
    sem_prj = shapefile(1, [('ponto', -48.3, -10.7)], prj=None, sem=('prj',))
    with pytest.raises(RecusaIngestao):
        envios.criar_envio(mundo.operador, mundo.f1, sem_prj)
    assert _arquivos(camadas) == []
    assert EnvioCamada.objects.count() == antes


def test_falha_ao_gravar_a_linha_apaga_o_original(camadas, mundo, monkeypatch):
    def falha(**campos):
        raise RuntimeError('banco caiu (simulado)')

    monkeypatch.setattr(EnvioCamada.objects, 'create', falha)
    envio = _envio_valido()
    with pytest.raises(RuntimeError):
        envios.criar_envio(mundo.operador, mundo.f1, envio)
    assert _arquivos(camadas) == []


def test_quem_nao_tem_permissao_nao_grava_nada(camadas, mundo):
    antes = EnvioCamada.objects.count()
    envio = _envio_valido()
    with pytest.raises(PermissionDenied):
        envios.criar_envio(mundo.sem_permissao, mundo.f1, envio)
    assert _arquivos(camadas) == []  # a permissão é checada antes de gravar
    assert EnvioCamada.objects.count() == antes


def test_papel_app_so_enxerga_envio_da_propria_fazenda(camadas, mundo):
    envio_f1 = envios.criar_envio(mundo.operador, mundo.f1, _envio_valido())
    envio_f2 = envios.criar_envio(mundo.operador, mundo.f2, _envio_valido())
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        consulta.execute("SELECT set_config('app.plataforma', '', true), set_config('app.empresas', '', true), "
                         "set_config('app.empresas_de_fazendas', '', true), set_config('app.fazendas', %s, true)",
                         [str(mundo.f1.pk)])
        fixar_contexto(consulta, '', '', '', str(mundo.f1.pk))
        consulta.execute('SELECT id FROM catalogo_envio_camada')
        visiveis = {linha[0] for linha in consulta.fetchall()}
    assert envio_f1.pk in visiveis
    assert envio_f2.pk not in visiveis  # negativo: envio de outra fazenda não aparece para o papel app


def test_sem_assinatura_o_papel_app_nao_enxerga_envio(camadas, mundo):
    envios.criar_envio(mundo.operador, mundo.f1, _envio_valido())
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        consulta.execute('SELECT count(*) FROM catalogo_envio_camada')
        assert consulta.fetchone()[0] == 0


def test_falha_depois_do_insert_na_saida_da_permissao_apaga_o_original(camadas, mundo, monkeypatch):
    # Achado 1: exceção depois da gravação (saída do contexto de permissão) deixava o original no disco.
    @contextmanager
    def saida_falha(pessoa, acao):
        yield
        raise RuntimeError('falha na saída da permissão (simulado)')

    monkeypatch.setattr(envios, 'com_permissao', saida_falha)
    with pytest.raises(RuntimeError):
        envios.criar_envio(mundo.operador, mundo.f1, _envio_valido())
    assert _arquivos(camadas) == []


def test_entrada_acima_do_limite_e_recusada_antes_de_gravar(camadas, mundo, monkeypatch):
    # Achado 2: o limite de tamanho vale antes de gravar, com a mesma mensagem de ingerir_envio.
    monkeypatch.setattr(envios, 'LIMITES_PADRAO', Limites(tamanho_bytes=10))
    antes = EnvioCamada.objects.count()
    with pytest.raises(RecusaIngestao) as excinfo:
        envios.criar_envio(mundo.operador, mundo.f1, _envio_valido())
    assert excinfo.value.erros == ['arquivo acima do limite de tamanho']
    assert _arquivos(camadas) == []
    assert EnvioCamada.objects.count() == antes


def _feicao(coordenadas):
    return {'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Point', 'coordinates': coordenadas}}


# Cada recusa de R6 e de R16 do gate T2.8: nenhuma linha nova, nenhuma feição, nenhum arquivo em CAMADAS_DIR.
RECUSAS = {
    'nan_geojson': geojson([ponto_geojson()]).decode().replace('-48.3', 'NaN').encode(),
    'infinito_geojson': geojson([ponto_geojson()]).decode().replace('-48.3', 'Infinity').encode(),
    'fora_da_faixa': geojson([ponto_geojson(x=200.0)]),
    'anel_aberto': geojson([{'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Polygon', 'coordinates': [
        [[-48.3, -10.7], [-48.29, -10.7], [-48.29, -10.69], [-48.3, -10.69]]]}}]),
    'geometria_invalida': geojson([{'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Polygon', 'coordinates': [
        [[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]}}]),
    'tipo_misturado': kml(placemark_ponto('-48.3,-10.7'), placemark_poligono('-48.3,-10.7 -48.29,-10.7 -48.29,-10.69 -48.3,-10.7')),
    'kml_nan': kml(placemark_ponto('NaN,-10.7')),
    'kml_nao_numerico': kml(placemark_ponto('abc,-10.7')),
    'kml_doctype_hostil': b'<!DOCTYPE kml [<!ENTITY e SYSTEM "file:///etc/passwd">]>' + kml(placemark_ponto('-48.3,-10.7')),
    'camada_vazia': geojson([]),
    'shapefile_nan': shapefile(1, [('ponto', float('nan'), -10.7)]),
    'shapefile_sem_prj': shapefile(1, [('ponto', -48.3, -10.7)], prj=None, sem=('prj',)),
    'zip_caminho_fora': zip_com({'../fora.kml': kml(placemark_ponto('1,2'))}),
    'tipo_nao_suportado': b'texto puro sem formato',
}


@pytest.mark.parametrize('nome', sorted(RECUSAS))
def test_recusa_nao_deixa_linha_feicao_versao_nem_arquivo(camadas, mundo, nome):
    antes = (EnvioCamada.objects.count(), Feicao.objects.count(), VersaoCamada.objects.count())
    with pytest.raises((RecusaIngestao, PermissionDenied)) as excinfo:
        envios.criar_envio(mundo.operador, mundo.f1, RECUSAS[nome])
    assert isinstance(excinfo.value, RecusaIngestao), nome  # recusa de conteúdo, não de permissão
    depois = (EnvioCamada.objects.count(), Feicao.objects.count(), VersaoCamada.objects.count())
    assert depois == antes, nome
    assert _arquivos(camadas) == [], nome


def test_envio_valido_nao_cria_versao_nem_feicao(camadas, mundo):
    # R12: a prévia não persiste versão nem feição; só a linha de envio temporário.
    antes = (VersaoCamada.objects.count(), Feicao.objects.count())
    envios.criar_envio(mundo.operador, mundo.f1, _envio_valido())
    depois = (VersaoCamada.objects.count(), Feicao.objects.count())
    assert depois == antes

