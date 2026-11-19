"""Metadados e atributos da prévia (008 T2.3; R8, R9, R10, R21). Função pura: valida e organiza; não grava.

Metadados: §6.2 de DEFINICAO.md, sem o que outras specs cobrem (situação, elaborador, revisor, aprovação: revisão
e vigência; resumo do que mudou e motivação: revisão; documentos: spec de documentos). Obrigatórios só nome, tema e
origem (R8). Opcional vazio vira `None` (o "Sem dados" da tela); zero e texto vazio não viram ausente.

Atributos: cada coluna do arquivo vira um atributo consultável (R9). Valor ausente fica `None`; valor do arquivo
não é convertido de tipo (R10). O tipo detectado (texto, número, lógico, vazio, misto) é só informação da prévia:
o modelo `AtributoVersao` não tem coluna de tipo (ver relatório T2.3)."""

from dataclasses import dataclass
from datetime import date

from catalogo.ingestao import Previa, RecusaIngestao

OBRIGATORIOS = ('nome', 'tema', 'origem')
# §6.2 de DEFINICAO.md, o que não é de outra spec (situação, aprovação e histórico: revisão e vigência; "o que mudou",
# motivação, autorização, revisão precedente: revisão; documentos vinculados: documentos).
OPCIONAIS = (
    'metodo',
    'escala_resolucao',
    'unidades',
    'limitacoes',
    'ressalvas',
    'notas_tecnicas',
    'validade_vigencia',
    'elaborador',
    'revisor',
    'data_coleta',
    'data_referencia',
    'data_elaboracao',
    'data_documento',
    'data_publicacao',
)
DATAS = ('data_coleta', 'data_referencia', 'data_elaboracao', 'data_documento', 'data_publicacao')
# shortcut: limites de texto iniciais, a medir com amostra sintética; nome e tema seguem Camada.nome e Estudo.nome (200).
LIMITE_NOME = 200
LIMITE_TEXTO = 2000
LIMITE_NOME_ATRIBUTO = 100  # AtributoVersao.nome


@dataclass(frozen=True)
class Metadados:
    obrigatorios: dict  # nome, tema, origem -> texto
    opcionais: dict  # campo -> texto, ou None para "Sem dados" (ausência explícita, nunca zero)


@dataclass(frozen=True)
class Atributo:
    nome: str
    tipo: str  # 'texto', 'numero', 'logico', 'vazio' ou 'misto'; só informação da prévia
    valores: tuple  # um por feição, na ordem da prévia; None é ausente


@dataclass(frozen=True)
class PreviaCompleta:
    previa: Previa
    metadados: Metadados
    atributos: tuple


def _texto(bruto, campo, limite, erros, obrigatorio):
    valor = bruto.get(campo)
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        if obrigatorio:
            erros.append(f'{campo} é obrigatório')
        return None
    if not isinstance(valor, str):
        erros.append(f'{campo} deve ser texto, não {type(valor).__name__}')
        return None
    if '\x00' in valor:
        erros.append(f'{campo} com caractere nulo')
        return None
    if len(valor) > limite:
        erros.append(f'{campo} acima de {limite} caracteres')
        return None
    return valor.strip()


def validar_metadados(bruto):
    """`bruto`: dict vindo do formulário ou da API. Levanta RecusaIngestao com todos os erros de uma vez."""
    erros = []
    desconhecidos = set(bruto) - set(OBRIGATORIOS) - set(OPCIONAIS)
    if desconhecidos:
        erros.append('metadado desconhecido: ' + ', '.join(sorted(str(c) for c in desconhecidos)))
    obrigatorios = {campo: _texto(bruto, campo, LIMITE_NOME if campo in ('nome', 'tema') else LIMITE_TEXTO, erros, True) for campo in OBRIGATORIOS}
    opcionais = {campo: _texto(bruto, campo, LIMITE_TEXTO, erros, False) for campo in OPCIONAIS}
    for campo in DATAS:
        texto = opcionais[campo]
        if texto is None:
            continue
        try:
            date.fromisoformat(texto)
        except ValueError:
            erros.append(f'{campo} deve ser data AAAA-MM-DD')
            opcionais[campo] = None
    if erros:
        raise RecusaIngestao(erros)
    return Metadados(obrigatorios=obrigatorios, opcionais=opcionais)


def _tipo(valores):
    presentes = [v for v in valores if v is not None]
    if not presentes:
        return 'vazio'
    tipos = set()
    for valor in presentes:
        if isinstance(valor, bool):
            tipos.add('logico')
        elif isinstance(valor, (int, float)):
            tipos.add('numero')
        else:
            tipos.add('texto')
    return tipos.pop() if len(tipos) == 1 else 'misto'


def atributos_da_previa(previa):
    """Uma coluna do arquivo vira um atributo. Nome vazio, com controle, longo ou repetido é recusado com o número da coluna."""
    erros, atributos, vistos = [], [], set()
    for posicao, nome in enumerate(previa.campos, start=1):
        if not isinstance(nome, str) or not nome.strip():
            erros.append(f'coluna {posicao}: nome vazio')
            continue
        if any(ord(c) < 32 for c in nome):
            erros.append(f'coluna {posicao}: caractere de controle no nome')
            continue
        if len(nome) > LIMITE_NOME_ATRIBUTO:
            erros.append(f'coluna {posicao}: nome acima de {LIMITE_NOME_ATRIBUTO} caracteres')
            continue
        if nome in vistos:
            erros.append(f'coluna {posicao}: nome repetido')
            continue
        vistos.add(nome)
        valores = tuple(feicao.valores.get(nome) for feicao in previa.feicoes)
        atributos.append(Atributo(nome=nome, tipo=_tipo(valores), valores=valores))
    if erros:
        raise RecusaIngestao(erros)
    return tuple(atributos)


def montar_previa(previa, bruto):
    """Prévia completa: metadados validados e atributos das colunas. Erros dos dois lados saem juntos."""
    erros = []
    try:
        metadados = validar_metadados(bruto)
    except RecusaIngestao as recusa:
        erros.extend(recusa.erros)
        metadados = None
    try:
        atributos = atributos_da_previa(previa)
    except RecusaIngestao as recusa:
        erros.extend(recusa.erros)
        atributos = None
    if metadados is None or atributos is None:
        raise RecusaIngestao(erros)
    return PreviaCompleta(previa=previa, metadados=metadados, atributos=atributos)
