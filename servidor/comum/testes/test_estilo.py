"""A15 (R18): identificadores definidos em `servidor/` ficam em português.

Heurística por lista: acusa o identificador que tiver um token da lista de palavras inglesas,
exceto os nomes exigidos por Python, Django e pytest (lista no teste). Migrações geradas ficam
de fora; as escritas à mão seguem a mesma regra por convenção e revisão.
"""

import ast
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]

# Nomes impostos por linguagem, biblioteca ou ferramenta (AGENTS.md §T0: "API/biblioteca externa").
PERMITIDOS = {
    'Meta', 'name', 'default_auto_field', 'db_table', 'constraints', 'application',
    'INSTALLED_APPS', 'ALLOWED_HOSTS', 'DEBUG', 'SECRET_KEY', 'DATABASES', 'DEFAULT_AUTO_FIELD',
    'LANGUAGE_CODE', 'TIME_ZONE', 'USE_TZ', 'BASE_DIR', 'self', 'cls', 'args', 'kwargs',
}

# Palavras inglesas comuns em nome de código. Cresce quando um nome em inglês escapar.
INGLES = {
    'user', 'users', 'company', 'farm', 'role', 'group', 'permission', 'permissions', 'get', 'set',
    'create', 'update', 'delete', 'list', 'find', 'check', 'can', 'grant', 'revoke', 'login', 'logout',
    'password', 'token', 'session', 'address', 'field', 'value', 'values', 'result', 'results', 'data',
    'item', 'items', 'count', 'total', 'error', 'message', 'config', 'file', 'path', 'key', 'model',
    'query', 'request', 'response', 'handle', 'build', 'make', 'load', 'save', 'read', 'write', 'send',
    'start', 'stop', 'run', 'level', 'parent', 'child', 'owner', 'access', 'allowed', 'created', 'updated',
    'enabled', 'valid', 'invalid', 'default', 'validate', 'normalize', 'helper', 'utils', 'manager',
    'service', 'handler', 'context', 'connection', 'cursor', 'table', 'row', 'rows', 'schema',
}


def _tokens(nome):
    return [t.lower() for t in re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+', nome)]


def _definidos(arvore):
    for no in ast.walk(arvore):
        if isinstance(no, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            yield no.name
        elif isinstance(no, ast.arg):
            yield no.arg
        elif isinstance(no, ast.Name) and isinstance(no.ctx, ast.Store):
            yield no.id
        elif isinstance(no, ast.Attribute) and isinstance(no.ctx, ast.Store):
            yield no.attr
        elif isinstance(no, ast.alias) and no.asname:
            yield no.asname


def achados_em(codigo):
    """Devolve os identificadores em inglês do código dado."""
    nomes = {n for n in _definidos(ast.parse(codigo)) if n not in PERMITIDOS and not n.startswith('__')}
    return sorted(n for n in nomes if set(_tokens(n)) & INGLES)


def test_detecta_identificador_em_ingles():
    assert achados_em('def get_user(): pass') == ['get_user']
    assert achados_em('class UserGroup:\n    nome_do_grupo = 1') == ['UserGroup']
    assert achados_em('def buscar_fazendas_autorizadas(pessoa): pass') == []


def test_identificadores_do_servidor_em_portugues():
    achados = {}
    for arquivo in RAIZ.rglob('*.py'):
        if 'migrations' in arquivo.parts or '.venv' in arquivo.parts:
            continue
        nomes = achados_em(arquivo.read_text(encoding='utf-8'))
        if nomes:
            achados[str(arquivo.relative_to(RAIZ))] = nomes
    assert achados == {}
