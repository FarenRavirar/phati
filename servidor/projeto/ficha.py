"""Contrato de encaixe das regiões do mapa (003 R23): o que a ficha espera de cada feição, em `contrato_mapa.md`.

O mapa, as camadas e a consulta (spec 004 e a de camadas) entregam registros neste formato; aqui o registro vira texto
para a ficha. Ausente nunca vira zero: campo sem dado é "Sem informação", e `0` é um valor medido.
"""

from datetime import date

CAMPOS = ('camada', 'atributo', 'valor', 'unidade', 'fonte', 'data', 'situacao', 'ressalva', 'origem')
SITUACOES = ('vigente', 'em análise', 'substituída', 'arquivada')
ORIGENS = {'medicao': 'Medição de campo', 'estimativa': 'Estimativa'}  # derivado nunca se rotula como medição
SEM_INFORMACAO = 'Sem informação'


def _texto(valor):
    return SEM_INFORMACAO if valor is None or valor == '' else str(valor)


def montar_ficha(registro):
    faltam = [campo for campo in CAMPOS if campo not in registro]
    if faltam:
        raise ValueError(f'Registro sem campo do contrato: {", ".join(faltam)}.')
    if registro['situacao'] not in SITUACOES:
        raise ValueError(f'Situação fora do contrato: {registro["situacao"]!r}.')
    if registro['origem'] not in ORIGENS:
        raise ValueError(f'Origem fora do contrato: {registro["origem"]!r}.')
    valor = registro['valor']
    if valor is None:
        exibido = SEM_INFORMACAO
    else:
        exibido = f'{valor} {registro["unidade"]}' if registro['unidade'] else f'{valor} ({SEM_INFORMACAO.lower()} de unidade)'
    data = registro['data']
    return {
        'camada': _texto(registro['camada']), 'atributo': _texto(registro['atributo']), 'valor': exibido,
        'fonte': _texto(registro['fonte']), 'data': data.strftime('%d/%m/%Y') if isinstance(data, date) else _texto(data),
        'situacao': registro['situacao'].capitalize(), 'ressalva': _texto(registro['ressalva']),
        'origem': ORIGENS[registro['origem']],
    }
