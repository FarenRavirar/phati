"""Camadas sintéticas (004 R4, R5; A5): contrato da 003, ausente ≠ zero, situações, origem e a caixa de coordenadas."""

import copy
import json
from decimal import Decimal
from datetime import date

import pytest

from projeto import camadas_sinteticas as sintetico
from projeto.ficha import CAMPOS, SEM_INFORMACAO, montar_ficha


def _registros():
    return [f['registro'] for c in sintetico.camadas() for f in c['feicoes']]


def _contem(retangulo, ponto):
    xs, ys = [p[0] for p in retangulo[0]], [p[1] for p in retangulo[0]]
    return min(xs) <= ponto[0] <= max(xs) and min(ys) <= ponto[1] <= max(ys)


def _feicoes_em(ponto):
    return [(c['id'], f) for c in sintetico.camadas() for f in c['feicoes'] if _contem(f['geometria'], ponto)]


def test_todo_registro_cumpre_o_contrato_da_003_com_os_dez_campos():
    for registro in _registros():
        assert set(registro) == set(CAMPOS)
        montar_ficha(registro)  # levanta ValueError se fugir do contrato


@pytest.mark.parametrize('campo', CAMPOS)
def test_remover_um_campo_do_registro_quebra_o_contrato(campo):
    registro = {k: v for k, v in _registros()[0].items() if k != campo}
    with pytest.raises(ValueError, match=campo):
        montar_ficha(registro)


def test_as_quatro_situacoes_e_os_dois_rotulos_de_origem_existem():
    assert {r['situacao'] for r in _registros()} == {'vigente', 'em análise', 'substituída', 'arquivada'}
    assert {r['origem'] for r in _registros()} == {'medicao', 'estimativa'}
    assert all(r['metodo'] for r in _registros() if r['origem'] == 'estimativa')


def test_ausente_e_zero_sao_coisas_distintas():
    fichas = {r['situacao'] + str(r['valor']): montar_ficha(r)['valor'] for r in _registros()}
    assert fichas['vigenteNone'] == SEM_INFORMACAO
    assert fichas['em análise0'] == '0 %'


def test_p1_cai_em_tres_camadas_vigente_vigente_e_em_analise():
    achadas = _feicoes_em(sintetico.P1)
    assert [c for c, _ in achadas] == ['camada-a', 'camada-b', 'camada-c']
    assert [f['registro']['situacao'] for _, f in achadas] == ['vigente', 'vigente', 'em análise']
    assert [f['registro']['origem'] for _, f in achadas][:2] == ['medicao', 'estimativa']


@pytest.mark.parametrize(('ponto', 'situacao', 'valor'), [
    (sintetico.P2, 'substituída', 28), (sintetico.P3, 'arquivada', Decimal('6.1')), (sintetico.P4, 'vigente', None),
])
def test_p2_p3_e_p4_caem_em_uma_feicao_so(ponto, situacao, valor):
    (_, feicao), = _feicoes_em(ponto)
    assert feicao['registro']['situacao'] == situacao
    assert feicao['registro']['valor'] == valor


def test_todas_as_coordenadas_ficam_a_menos_de_0_1_grau_do_centro_em_terra_longe_do_oceano_de_0_0():
    for camada in sintetico.camadas():
        for feicao in camada['feicoes']:
            for lon, lat in feicao['geometria'][0]:
                assert abs(lon - sintetico.LON0) < 0.1
                assert abs(lat - sintetico.LAT0) < 0.1
    assert abs(sintetico.LON0) > 10 and abs(sintetico.LAT0) > 5  # nunca volta para o oceano em (0°, 0°)


def test_geojson_e_feature_collection_serializavel_com_ids_unicos_e_texto_pronto():
    colecao = sintetico.geojson()
    assert colecao['type'] == 'FeatureCollection'
    json.dumps(colecao)  # data e Decimal já saem como texto
    ids = [f['id'] for f in colecao['features']]
    assert len(ids) == len(set(ids)) == 6
    for feicao in colecao['features']:
        assert feicao['geometry']['type'] == 'Polygon'
        assert feicao['properties']['camada_id'] in {'camada-a', 'camada-b', 'camada-c'}
        assert feicao['properties']['cor'].startswith('--cor-camada-provisoria-')
        assert all(isinstance(v, str) for v in feicao['properties'].values())


def test_geojson_nao_altera_o_dado_original_entre_chamadas():
    antes = copy.deepcopy(sintetico.camadas())
    sintetico.geojson()
    assert sintetico.camadas() == antes
    assert sintetico.DATA == date(2026, 1, 15)
