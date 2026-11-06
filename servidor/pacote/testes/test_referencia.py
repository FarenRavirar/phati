"""Pacote de referência e estilo base (004b R6, R19, R23; A6, A16)."""

import json
from pathlib import Path

from pacote import manifesto
from pacote.testes.conftest import REFERENCIA
from projeto import camadas_sinteticas

ESTILO = Path(__file__).resolve().parents[1] / 'estilo_base.json'
CONTRATO = Path(__file__).resolve().parents[2] / 'projeto' / 'contrato_pacote.md'


def test_o_pacote_de_referencia_passa_no_esquema_e_confere_os_arquivos():
    lido = manifesto.ler(REFERENCIA)
    assert lido.arquivos and lido.formato_versao == 1


def test_a_caixa_da_referencia_fica_a_menos_de_0_1_grau_do_centro_de_teste():
    # R19: o dado sintético fica no centro de teste da 004 (em terra, para o fundo online ter imagem).
    for arquivo in (REFERENCIA / 'fundo.pmtiles', REFERENCIA / 'ortofoto.pmtiles'):
        corpo = arquivo.read_bytes()
        assert corpo[:7] == b'PMTiles'
    lon0, lat0 = camadas_sinteticas.LON0, camadas_sinteticas.LAT0
    assert abs(lon0 - -48.30) < 0.1 and abs(lat0 - -10.75) < 0.1  # as constantes que a referência usa


def test_estilo_e_manifesto_nao_citam_o_google_nem_documentos():
    texto = ESTILO.read_text(encoding='utf-8') + (REFERENCIA / 'manifesto.json').read_text(encoding='utf-8')
    assert 'googleapis' not in texto.lower() and 'google' not in texto.lower()
    assert 'documento' not in (REFERENCIA / 'manifesto.json').read_text(encoding='utf-8').lower()


def test_estilo_usa_so_o_suporte_comum_e_o_protocolo_de_arquivo_local():
    estilo = json.loads(ESTILO.read_text(encoding='utf-8'))
    assert {c['type'] for c in estilo['layers']} <= {'background', 'fill', 'line', 'raster'}
    proibidas = ('layer-opacity', 'layer-blend')
    assert not any(chave.endswith(proibidas) for c in estilo['layers'] for chave in c.get('paint', {}))
    assert all(f['url'].startswith('pmtiles://file://{pacote}/') for f in estilo['sources'].values())


def test_o_contrato_registra_o_uso_de_pmtiles_file_e_as_regras_do_google():
    texto = CONTRATO.read_text(encoding='utf-8')
    assert 'pmtiles://file://' in texto
    for regra in ('R21', 'R22', 'R23'):
        assert regra in texto
