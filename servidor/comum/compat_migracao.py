"""Compatibilidade expand-only das migrações Django (spec 009, R4 e R5).

Analisa o ARQUIVO da migração por AST e por tokens. Nunca importa nem executa o arquivo: o conteúdo é entrada
hostil. Falha fechada: o que não se consegue analisar sai com rc 2, nunca aprovado.

Uso: python -m comum.compat_migracao <arquivo>...  (só `.py` dentro do diretório de trabalho; o resto sai com rc 2)
Códigos: 0 todos compatíveis; 1 alguma reprovada; 2 erro de uso, leitura, sintaxe ou caminho recusado; 3 só reprovadas marcadas com
`# bluegreen: incompativel-por-design` (caminho antigo, R5). Precedência: 2 > 1 > 3 > 0.

Limite conhecido: AddConstraint é aprovado; uma constraint nova pode recusar INSERT da versão anterior. Não checado
pelo verificador; revisão humana na PR.
"""

from __future__ import annotations

import ast
import io
import re
import sys
import tokenize
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path

MARCADOR = '# bluegreen: incompativel-por-design'
# shortcut: teto de leitura contra arquivo enorme; acima dele sai rc 2 sem analisar. Subir se uma migração real passar.
TAMANHO_MAXIMO = 2 * 1024 * 1024

RC_OK, RC_REPROVADA, RC_ERRO, RC_FORA_DO_FLUXO = 0, 1, 2, 3
PRECEDENCIA = (RC_ERRO, RC_REPROVADA, RC_FORA_DO_FLUXO, RC_OK)

# Operações que a versão anterior não tolera enquanto estiver de pé (R4).
REPROVADAS = {
    'RemoveField': 'remove coluna que a versão anterior ainda lê',
    'DeleteModel': 'apaga tabela que a versão anterior ainda usa',
    'RenameField': 'renomeia coluna que a versão anterior ainda lê',
    'RenameModel': 'renomeia tabela que a versão anterior ainda usa',
    'AlterField': 'altera campo (tipo, nulidade ou nome); estreitar não é decidível por AST, reprovada por padrão',
    'AlterModelTable': 'troca o nome da tabela que a versão anterior usa',
    'RemoveConstraint': 'remove restrição da qual a versão anterior pode depender',
    'RemoveIndex': 'remove índice do qual a versão anterior pode depender',
    'AlterUniqueTogether': 'altera unicidade composta: pode quebrar a versão anterior',
    'AlterIndexTogether': 'altera índice composto: pode quebrar a versão anterior',
    'RemoveIndexConcurrently': 'remove índice do qual a versão anterior pode depender',
}
# AddConstraint: limite conhecido, ver a docstring do módulo. ExtensaoUnaccentSemVolta (subclasse de UnaccentExtension,
# territorio/0008): `CREATE EXTENSION IF NOT EXISTS unaccent`, só acrescenta funções no banco; a volta não faz nada
# (spec 012 T4.0). A classe de Django `UnaccentExtension` não está aqui: o reverso dela faz DROP e não é aprovado.
APROVADAS = frozenset({
    'CreateModel', 'AddIndex', 'AddIndexConcurrently', 'AddConstraint', 'AlterModelOptions', 'ExtensaoUnaccentSemVolta',
})

PADROES_SQL = (
    (re.compile(r'\bDROP\b', re.IGNORECASE), 'DROP'),
    (re.compile(r'\bRENAME\b', re.IGNORECASE), 'RENAME'),
    (re.compile(r'\bTRUNCATE\b', re.IGNORECASE), 'TRUNCATE'),
    (re.compile(r'\bSET\s+NOT\s+NULL\b', re.IGNORECASE), 'NOT NULL em coluna existente'),
    (re.compile(r'\bALTER\b[^;]*\bTYPE\b', re.IGNORECASE), 'ALTER ... TYPE'),
    # Coluna nova NOT NULL sem DEFAULT: o INSERT da versão anterior não informa a coluna e quebra.
    (re.compile(r'\bADD\b(?!\s+CONSTRAINT\b)(?![^;]*\bDEFAULT\b)[^;]*\bNOT\s+NULL\b', re.IGNORECASE),
     'ADD COLUMN NOT NULL sem DEFAULT'),
)
PADRAO_DELETE = re.compile(r'\bDELETE\s+FROM\b', re.IGNORECASE)
PADRAO_WHERE = re.compile(r'\bWHERE\b', re.IGNORECASE)
PADRAO_RUNPYTHON = re.compile(r'\b(DROP|RENAME)\b', re.IGNORECASE)


@dataclass(frozen=True)
class Violacao:
    arquivo: str
    linha: int
    operacao: str
    motivo: str


@dataclass(frozen=True)
class Resultado:
    arquivo: str
    marcado: bool
    violacoes: tuple[Violacao, ...]


class ErroAnalise(Exception):
    """Arquivo que não se analisa: falha fechada, rc 2."""


@dataclass
class _Ctx:
    arquivo: str
    inicial: bool
    funcoes: dict[str, ast.FunctionDef]
    criados: frozenset[str]
    constantes: dict[str, ast.expr]


def verificar_arquivo(caminho: str | Path) -> list[Violacao]:
    return list(analisar_arquivo(caminho).violacoes)


def analisar_arquivo(caminho: str | Path) -> Resultado:
    arquivo = str(caminho)
    dados = _ler(arquivo)
    try:
        arvore = ast.parse(dados, filename=arquivo)
        # ast.parse não pega tudo (ex.: keyword repetida); compile só gera código, não executa o arquivo.
        compile(dados, arquivo, 'exec', dont_inherit=True)
        marcado = _tem_marcador(dados)
    except (SyntaxError, ValueError, RecursionError, MemoryError, tokenize.TokenError) as erro:  # UnicodeError é ValueError
        raise ErroAnalise(f'sintaxe ou codificação inválida: {erro}') from erro

    classe = _classe_migration(arvore)
    if classe is None:
        violacoes = [Violacao(arquivo, 1, '(migração)', 'sem class Migration no topo: não é migração analisável')]
    else:
        inicial = Path(arquivo).name.startswith('0001_') or _marca_inicial(classe)
        funcoes = {no.name: no for no in arvore.body if isinstance(no, ast.FunctionDef)}
        ctx = _Ctx(arquivo, inicial, funcoes, frozenset(), _constantes(arvore))
        violacoes = _analisar_classe(classe, arvore, ctx)
    return Resultado(arquivo, marcado, tuple(violacoes))


def _tabelas_criadas(no: ast.expr) -> set[str]:
    # Só o que o banco cria de fato: CreateModel de topo ou em database_operations. state_operations não conta.
    if not isinstance(no, ast.Call):
        return set()
    if _nome_chamada(no) == 'CreateModel':
        nome = _texto(_arg(no, 0, 'name'))
        return {nome} if nome is not None else set()
    if _nome_chamada(no) == 'SeparateDatabaseAndState':
        operacoes = _arg(no, 0, 'database_operations')
        if isinstance(operacoes, (ast.List, ast.Tuple)):
            return set().union(*(_tabelas_criadas(elemento) for elemento in operacoes.elts))
    return set()


def _analisar_sequencia(elementos: list[ast.expr], ctx: _Ctx) -> list[Violacao]:
    # Cada operação vê só as tabelas criadas antes dela na ordem do arquivo.
    violacoes: list[Violacao] = []
    criados: set[str] = set()
    for elemento in elementos:
        violacoes += _analisar_elemento(elemento, replace(ctx, criados=frozenset(criados)))
        criados |= _tabelas_criadas(elemento)
    return violacoes


def _constantes(arvore: ast.Module) -> dict[str, ast.expr]:
    # Constante de módulo atribuída uma única vez, de literal (sem chamada nem nome). Qualquer outra forma fica fora.
    escritas = Counter(no.id for no in ast.walk(arvore) if isinstance(no, ast.Name) and isinstance(no.ctx, ast.Store))
    constantes: dict[str, ast.expr] = {}
    for no in arvore.body:
        if isinstance(no, ast.Assign) and len(no.targets) == 1 and isinstance(no.targets[0], ast.Name):
            nome = no.targets[0].id
            if escritas[nome] == 1 and _literal(no.value):
                constantes[nome] = no.value
    return constantes


def _literal(no: ast.expr) -> bool:
    # Lista fica de fora: é mutável (`LISTA.append(...)` não aparece como reatribuição).
    if isinstance(no, ast.Tuple):
        return all(_literal(elemento) for elemento in no.elts)
    return isinstance(no, ast.Constant)


def _valor(no: ast.expr, ctx: _Ctx) -> ast.expr:
    if isinstance(no, ast.Name) and no.id in ctx.constantes:
        return ctx.constantes[no.id]
    return no


def _ler(arquivo: str) -> bytes:
    try:
        with open(arquivo, 'rb') as origem:
            dados = origem.read(TAMANHO_MAXIMO + 1)
    except OSError as erro:
        raise ErroAnalise(f'arquivo ilegível: {erro.strerror or erro}') from erro
    if len(dados) > TAMANHO_MAXIMO:
        raise ErroAnalise(f'arquivo acima de {TAMANHO_MAXIMO} bytes: não analisado')
    return dados


def _tem_marcador(dados: bytes) -> bool:
    # Só token COMMENT vale: texto igual dentro de string literal não conta.
    return any(
        token.type == tokenize.COMMENT and token.string.strip() == MARCADOR
        for token in tokenize.tokenize(io.BytesIO(dados).readline)
    )


def _classe_migration(arvore: ast.Module) -> ast.ClassDef | None:
    return next((no for no in arvore.body if isinstance(no, ast.ClassDef) and no.name == 'Migration'), None)


def _marca_inicial(classe: ast.ClassDef) -> bool:
    return any(
        isinstance(no, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'initial' for t in no.targets)
        and _e_true(no.value)
        for no in classe.body
    )


def _analisar_classe(classe: ast.ClassDef, arvore: ast.Module, ctx: _Ctx) -> list[Violacao]:
    atribuicoes = [no for no in classe.body if isinstance(no, (ast.Assign, ast.AnnAssign)) and _atribui(no, 'operations')]
    valor = atribuicoes[0].value if len(atribuicoes) == 1 else None
    referencias = [
        no for no in ast.walk(arvore)
        if (isinstance(no, ast.Name) and no.id == 'operations') or (isinstance(no, ast.Attribute) and no.attr == 'operations')
    ]
    if len(referencias) != 1 or not isinstance(valor, (ast.List, ast.Tuple)):
        texto = 'operations ausente, montada ou alterada por código: não analisável'
        return [Violacao(ctx.arquivo, classe.lineno, '(operations)', f'(operations): {texto}')]
    return _analisar_sequencia(list(valor.elts), ctx)


def _atribui(no: ast.stmt, nome: str) -> bool:
    if isinstance(no, ast.Assign):
        return any(isinstance(t, ast.Name) and t.id == nome for t in no.targets)
    if isinstance(no, ast.AnnAssign):
        return isinstance(no.target, ast.Name) and no.target.id == nome
    return False


def _analisar_elemento(no: ast.expr, ctx: _Ctx) -> list[Violacao]:
    if not isinstance(no, ast.Call):
        return [_viol(ctx, no, '(operação)', 'elemento não é chamada literal de operação: não analisável')]
    return _analisar_operacao(no, ctx)


def _analisar_operacao(no: ast.Call, ctx: _Ctx) -> list[Violacao]:
    nome = _nome_chamada(no)
    if nome in REPROVADAS:
        return [_viol(ctx, no, nome, REPROVADAS[nome])]
    if any(isinstance(a, ast.Starred) for a in no.args) or any(k.arg is None for k in no.keywords):
        return [_viol(ctx, no, nome, 'argumentos com *args ou **kwargs: não analisável')]
    if nome in APROVADAS:
        return []
    if nome == 'AddField':
        return _addfield(no, ctx)
    if nome == 'RunSQL':
        return _runsql(no, ctx)
    if nome == 'RunPython':
        return _runpython(no, ctx)
    if nome == 'SeparateDatabaseAndState':
        return _separate(no, ctx)
    return [_viol(ctx, no, nome, 'operação não listada nas regras de compatibilidade: não analisável')]


def _addfield(no: ast.Call, ctx: _Ctx) -> list[Violacao]:
    # Migração inicial: tabela criada no mesmo arquivo não é lida pela versão anterior. Só isto é relaxado.
    if ctx.inicial and _texto(_arg(no, 0, 'model_name')) in ctx.criados:
        return []
    campo = _arg(no, 2, 'field')
    if isinstance(campo, ast.Call) and _nome_chamada(campo) == 'ManyToManyField':
        return []  # M2M cria tabela nova, não coluna na tabela existente
    if isinstance(campo, ast.Call) and not any(k.arg is None for k in campo.keywords):
        opcoes = {k.arg: k.value for k in campo.keywords}
        if _e_true(opcoes.get('null')) or _tem_valor(opcoes.get('db_default')):
            return []
        if _tem_valor(opcoes.get('default')):
            texto = ('o default do Django não existe no banco: o INSERT da versão anterior quebra em NOT NULL '
                     '(use db_default=)')
            return [_viol(ctx, no, 'AddField', texto)]
    texto = 'sem null=True nem db_default= (ou campo não analisável): NOT NULL sem valor quebra INSERT da versão anterior'
    return [_viol(ctx, no, 'AddField', texto)]


def _runsql(no: ast.Call, ctx: _Ctx) -> list[Violacao]:
    # Só o sentido de ida (`sql`): o reverso não roda no fluxo de troca, e reprovaria RLS (DROP POLICY).
    sql = _arg(no, 0, 'sql')
    if sql is None:
        return [_viol(ctx, no, 'RunSQL', 'sem argumento sql: não analisável')]
    textos = _textos_sql(sql, ctx)
    if textos is None:
        texto = 'SQL não literal (variável que não é constante literal do módulo, f-string, chamada ou concatenação): não analisável'
        return [_viol(ctx, no, 'RunSQL', texto)]
    return [
        _viol(ctx, no, 'RunSQL', f'SQL destrutivo ({motivo})')
        for texto in textos for motivo in _sql_destrutivo(texto)
    ]


def _textos_sql(no: ast.expr, ctx: _Ctx) -> list[str] | None:
    no = _valor(no, ctx)
    if isinstance(no, ast.Constant) and isinstance(no.value, str):
        return [no.value]
    if not isinstance(no, (ast.List, ast.Tuple)):
        return None
    textos = []
    for elemento in no.elts:
        alvo = _valor(elemento, ctx)
        if isinstance(alvo, ast.Tuple) and alvo.elts:
            alvo = _valor(alvo.elts[0], ctx)
        if not (isinstance(alvo, ast.Constant) and isinstance(alvo.value, str)):
            return None
        textos.append(alvo.value)
    return textos


def _sql_destrutivo(texto: str) -> list[str]:
    # shortcut: texto simples, sem entender comentário, string de SQL ou bloco $$. DELETE é separado por ';' e
    # o WHERE é procurado no mesmo trecho; limite conhecido: `;` dentro de função plpgsql pode separar errado.
    motivos = [nome for padrao, nome in PADROES_SQL if padrao.search(texto)]
    if any(PADRAO_DELETE.search(trecho) and not PADRAO_WHERE.search(trecho) for trecho in texto.split(';')):
        motivos.append('DELETE FROM sem WHERE')
    return motivos


def _runpython(no: ast.Call, ctx: _Ctx) -> list[Violacao]:
    # Só a função de ida, e só se estiver no mesmo arquivo. Limite: não segue helper, não analisa .update().
    codigo = _arg(no, 0, 'code')
    if not isinstance(codigo, ast.Name):
        return [_viol(ctx, no, 'RunPython', 'função não referenciada por nome: não analisável')]
    funcao = ctx.funcoes.get(codigo.id)
    if funcao is None:
        return [_viol(ctx, no, 'RunPython', f'função {codigo.id} não está no arquivo: não analisável')]
    violacoes = []
    for sub in ast.walk(funcao):
        if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute) and sub.func.attr == 'delete':
            violacoes.append(_viol(ctx, sub, 'RunPython', 'chama .delete(): remove dado que a versão anterior pode ler'))
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and PADRAO_RUNPYTHON.search(sub.value):
            violacoes.append(_viol(ctx, sub, 'RunPython', 'string com DROP ou RENAME dentro da função'))
    return violacoes


def _separate(no: ast.Call, ctx: _Ctx) -> list[Violacao]:
    # Só database_operations é analisado; state_operations mexe só no estado do Django.
    operacoes = _arg(no, 0, 'database_operations')  # Django: __init__(database_operations=None, state_operations=None)
    if operacoes is None or (isinstance(operacoes, ast.Constant) and operacoes.value is None):
        return []
    if not isinstance(operacoes, (ast.List, ast.Tuple)):
        return [_viol(ctx, no, 'SeparateDatabaseAndState', 'database_operations não literal: não analisável')]
    return _analisar_sequencia(list(operacoes.elts), ctx)


def _arg(no: ast.Call, posicao: int, nome: str) -> ast.expr | None:
    if len(no.args) > posicao:
        return no.args[posicao]
    return next((k.value for k in no.keywords if k.arg == nome), None)


def _nome_chamada(no: ast.Call) -> str:
    if isinstance(no.func, ast.Attribute):
        return no.func.attr
    if isinstance(no.func, ast.Name):
        return no.func.id
    return '?'


def _texto(no: ast.expr | None) -> str | None:
    if isinstance(no, ast.Constant) and isinstance(no.value, str):
        return no.value.lower()
    return None


def _e_true(no: ast.expr | None) -> bool:
    return isinstance(no, ast.Constant) and no.value is True


def _tem_valor(no: ast.expr | None) -> bool:
    return no is not None and not (isinstance(no, ast.Constant) and no.value is None)


def _viol(ctx: _Ctx, no: ast.AST, operacao: str, texto: str) -> Violacao:
    return Violacao(ctx.arquivo, getattr(no, 'lineno', 1), operacao, f'{operacao}: {texto}')


def _codigo(resultado: Resultado) -> int:
    if not resultado.violacoes:
        return RC_OK
    return RC_FORA_DO_FLUXO if resultado.marcado else RC_REPROVADA


def _motivo_recusa(caminho: Path) -> str | None:
    # CLI de dev/CI: só analisa `.py` dentro do diretório de trabalho, para não ler caminho arbitrário do disco.
    if caminho.suffix != '.py':
        return 'só arquivo .py é analisado'
    if not caminho.is_relative_to(Path.cwd().resolve()):
        return 'fora do diretório de trabalho'
    return None


def principal(argumentos: list[str]) -> int:
    if not argumentos:
        print('uso: python -m comum.compat_migracao <arquivo>...', file=sys.stderr)
        return RC_ERRO
    codigos = []
    for arquivo in argumentos:
        caminho = Path(arquivo).resolve()
        motivo = _motivo_recusa(caminho)
        if motivo is not None:
            print(f'ERRO {arquivo}: {motivo}', file=sys.stderr)
            codigos.append(RC_ERRO)
            continue
        try:
            resultado = analisar_arquivo(caminho)
        except ErroAnalise as erro:
            print(f'ERRO {caminho}: {erro}', file=sys.stderr)
            codigos.append(RC_ERRO)
            continue
        codigos.append(_codigo(resultado))
        _imprimir(resultado)
    return next(codigo for codigo in PRECEDENCIA if codigo in codigos)


def _imprimir(resultado: Resultado) -> None:
    if not resultado.violacoes:
        print(f'OK {resultado.arquivo}')
    elif resultado.marcado:
        print(f'FORA_DO_FLUXO {resultado.arquivo}')
        for v in resultado.violacoes:
            print(f'  {v.arquivo}:{v.linha} {v.motivo}')
    else:
        for v in resultado.violacoes:
            print(f'REPROVADA {v.arquivo}:{v.linha} {v.motivo}')


if __name__ == '__main__':
    raise SystemExit(principal(sys.argv[1:]))
