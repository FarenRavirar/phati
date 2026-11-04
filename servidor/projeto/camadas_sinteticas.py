"""Camadas sintéticas do mapa de teste (004 R4, R5): dado inventado, gerado em código, no registro do contrato da 003.

Fica em área rural de Porto Nacional (TO), em terra, onde o fundo de satélite do Google tem imagem em zoom 13 ou mais
(em (0°, 0°) é oceano e o Google responde 404). Os retângulos são pequenos (cerca de 3 km) e o centro não é nenhuma fazenda
cadastrada. Cada camada traz retângulos; o ponto P1 cai em três camadas (vigente,
vigente e em análise) e P2, P3 e P4 caem em uma feição só (substituída, arquivada, sem valor).

shortcut: dado gerado em código, sem modelo nem migração; trocar pelo backend de camadas quando existir (spec de camadas).
"""

from datetime import date
from decimal import Decimal

from projeto.ficha import montar_ficha

LON0, LAT0 = -48.30, -10.75  # centro do dado de teste; a câmera inicial do mapa usa o mesmo ponto (mapa.js)
FONTE = 'Levantamento sintético'
RESSALVA = 'Dado sintético de teste de layout.'
DATA = date(2026, 1, 15)

# Pontos de teste (lon, lat): P1 em três camadas; P2, P3 e P4 em uma feição só.
P1 = (LON0, LAT0)
P2 = (LON0 - 0.027, LAT0 + 0.008)
P3 = (LON0 + 0.027, LAT0 + 0.008)
P4 = (LON0, LAT0 - 0.027)


def _retangulo(oeste, sul, leste, norte):
    """Caixa em graus relativos ao centro; anel fechado, sentido anti-horário (RFC 7946)."""
    o, l = (LON0 + v for v in (oeste, leste))
    s, n = (LAT0 + v for v in (sul, norte))
    return [[[o, s], [l, s], [l, n], [o, n], [o, s]]]


def _registro(camada, atributo, valor, unidade, situacao, origem='medicao', metodo=None):
    return {
        'camada': camada, 'atributo': atributo, 'valor': valor, 'unidade': unidade, 'fonte': FONTE, 'data': DATA,
        'situacao': situacao, 'ressalva': RESSALVA, 'origem': origem, 'metodo': metodo,
    }


def camadas():
    """Lista na ordem padrão de desenho (a primeira fica por cima). Cada feição: `id` estável, geometria e registro."""
    return [
        {
            'id': 'camada-a', 'cor': '--cor-camada-provisoria-1', 'feicoes': [
                {'id': 1, 'geometria': _retangulo(-0.014, -0.010, 0.006, 0.010),
                 'registro': _registro('Camada A', 'Teor de argila', 32, '%', 'vigente')},
                {'id': 2, 'geometria': _retangulo(-0.034, 0.002, -0.020, 0.014),
                 'registro': _registro('Camada A', 'Teor de argila', 28, '%', 'substituída')},
            ],
        },
        {
            'id': 'camada-b', 'cor': '--cor-camada-provisoria-2', 'feicoes': [
                {'id': 3, 'geometria': _retangulo(-0.006, -0.006, 0.014, 0.014),
                 'registro': _registro('Camada B', 'Acidez do solo', Decimal('5.8'), 'pH', 'vigente', 'estimativa', 'Interpolação sintética')},
                {'id': 4, 'geometria': _retangulo(0.020, 0.002, 0.034, 0.014),
                 'registro': _registro('Camada B', 'Acidez do solo', Decimal('6.1'), 'pH', 'arquivada')},
            ],
        },
        {
            'id': 'camada-c', 'cor': '--cor-camada-provisoria-3', 'feicoes': [
                {'id': 5, 'geometria': _retangulo(-0.010, -0.014, 0.010, 0.004),
                 'registro': _registro('Camada C', 'Declividade', 0, '%', 'em análise')},
                {'id': 6, 'geometria': _retangulo(-0.008, -0.034, 0.008, -0.020),
                 'registro': _registro('Camada C', 'Declividade', None, '%', 'vigente')},
            ],
        },
    ]


def geojson():
    """`FeatureCollection` em WGS 84 com todas as feições. As propriedades são a saída de `montar_ficha` (texto pronto,
    "Sem informação" para ausente, nunca 0) mais `camada_id` e `cor`; o navegador só mostra, não reformata."""
    feicoes = [
        {
            'type': 'Feature', 'id': feicao['id'], 'geometry': {'type': 'Polygon', 'coordinates': feicao['geometria']},
            'properties': {**montar_ficha(feicao['registro']), 'camada_id': camada['id'], 'cor': camada['cor']},
        }
        for camada in camadas() for feicao in camada['feicoes']
    ]
    return {'type': 'FeatureCollection', 'features': feicoes}
