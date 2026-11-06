"""Pacote de referência e estilo base (004b R6, R19, R23; A6, A16)."""

import json
import struct
from pathlib import Path

from pacote import manifesto
from pacote.testes.conftest import REFERENCIA
from projeto import camadas_sinteticas

ESTILO = Path(__file__).resolve().parents[1] / 'estilo_base.json'
CONTRATO = Path(__file__).resolve().parents[2] / 'projeto' / 'contrato_pacote.md'


def test_o_pacote_de_referencia_passa_no_esquema_e_confere_os_arquivos():
    lido = manifesto.ler(REFERENCIA)
    assert lido.arquivos and lido.formato_versao == 1


def _limites(arquivo):
    """(oeste, sul, leste, norte) do cabeçalho PMTiles v3: quatro int32 little-endian em e7 a partir do byte 102."""
    cabecalho = arquivo.read_bytes()[:127]
    assert cabecalho[:7] == b'PMTiles' and cabecalho[7] == 3
    return tuple(valor / 1e7 for valor in struct.unpack_from('<4i', cabecalho, 102))


def test_a_caixa_da_referencia_fica_a_menos_de_0_1_grau_do_centro_de_teste():
    # R19: o dado sintético fica no centro de teste da 004 (em terra, para o fundo online ter imagem). Lê os limites de cada
    # arquivo; trocar a referência por outra região faz este teste falhar (Greptile, PR #50).
    for arquivo in (REFERENCIA / 'fundo.pmtiles', REFERENCIA / 'ortofoto.pmtiles'):
        oeste, sul, leste, norte = _limites(arquivo)
        assert oeste < leste and sul < norte, arquivo.name
        assert abs((oeste + leste) / 2 - camadas_sinteticas.LON0) < 0.1, arquivo.name
        assert abs((sul + norte) / 2 - camadas_sinteticas.LAT0) < 0.1, arquivo.name


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
