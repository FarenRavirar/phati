"""Contrato de encaixe das regiões do mapa (003 R23): o que a ficha espera de cada feição, em `contrato_mapa.md`.

O mapa, as camadas e a consulta (spec 004 e a de camadas) entregam registros neste formato; aqui o registro vira texto
para a ficha. Ausente nunca vira zero: campo sem dado é "Sem informação", e `0` é um valor medido.
"""

from datetime import date
from decimal import Decimal

from django.utils.formats import number_format

CAMPOS = ('camada', 'atributo', 'valor', 'unidade', 'fonte', 'data', 'situacao', 'ressalva', 'origem', 'metodo')
SITUACOES = ('vigente', 'em análise', 'substituída', 'arquivada')
ORIGENS = {'medicao': 'Medição de campo', 'estimativa': 'Estimativa'}  # derivado nunca se rotula como medição
SEM_INFORMACAO = 'Sem informação'
TEXTOS = ('camada', 'atributo', 'unidade', 'fonte', 'ressalva', 'metodo')


def _texto(valor):
    return SEM_INFORMACAO if valor is None or valor == '' else str(valor)


def _valor_exibido(valor, unidade):
    if valor is None or valor == '':
        return SEM_INFORMACAO
    # Número sai no formato da língua (vírgula decimal); `bool` é `int` em Python e não é medida.
    texto = number_format(valor) if isinstance(valor, int | float | Decimal) else str(valor)
    return f'{texto} {unidade}' if unidade else f'{texto} ({SEM_INFORMACAO.lower()} de unidade)'


def _conferir(registro):
    faltam = [campo for campo in CAMPOS if campo not in registro]
    if faltam:
        raise ValueError(f'Registro sem campo do contrato: {", ".join(faltam)}.')
    if registro['situacao'] not in SITUACOES:
        raise ValueError(f'Situação fora do contrato: {registro["situacao"]!r}.')
    if registro['origem'] not in ORIGENS:
        raise ValueError(f'Origem fora do contrato: {registro["origem"]!r}.')
    for campo in TEXTOS:
        if registro[campo] is not None and not isinstance(registro[campo], str):
            raise ValueError(f'Campo {campo} fora do contrato: esperado texto, veio {type(registro[campo]).__name__}.')
    valor = registro['valor']
    if valor is not None and (isinstance(valor, bool) or not isinstance(valor, int | float | Decimal | str)):
        raise ValueError(f'Campo valor fora do contrato: veio {type(valor).__name__}.')
    if registro['data'] is not None and not isinstance(registro['data'], date):
        raise ValueError(f'Campo data fora do contrato: esperada data, veio {type(registro["data"]).__name__}.')
    # Valor derivado sem método não se explica (AGENTS.md §Código): a ficha recusa em vez de mostrar estimativa muda.
    if registro['origem'] == 'estimativa' and not registro['metodo']:
        raise ValueError('Estimativa sem método.')


def montar_ficha(registro):
    _conferir(registro)
    data = registro['data']
    return {
        'camada': _texto(registro['camada']), 'atributo': _texto(registro['atributo']),
        'valor': _valor_exibido(registro['valor'], registro['unidade']),
        'fonte': _texto(registro['fonte']), 'data': data.strftime('%d/%m/%Y') if data else SEM_INFORMACAO,
        'situacao': registro['situacao'].capitalize(), 'ressalva': _texto(registro['ressalva']),
        'origem': ORIGENS[registro['origem']], 'metodo': _texto(registro['metodo']),
    }
