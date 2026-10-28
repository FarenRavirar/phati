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
    'LANGUAGE_CODE', 'TIME_ZONE', 'USE_TZ', 'ROOT_URLCONF', 'urlpatterns', 'self', 'cls', 'args', 'kwargs',
    # Django impõe estes nomes (usuário customizado, hasher, sessão, e-mail).
    'USERNAME_FIELD', 'password', 'last_login', 'AUTH_USER_MODEL', 'PASSWORD_HASHERS', 'DEFAULT_FROM_EMAIL',
    'SESSION_COOKIE_HTTPONLY', 'SESSION_COOKIE_SECURE', 'SESSION_COOKIE_SAMESITE', 'SESSION_COOKIE_AGE',
    'session',  # request.session é atributo do Django
}

# Palavras inglesas comuns em nome de código. Cresce quando um nome em inglês escapar.
INGLES = {
    'user', 'users', 'company', 'farm', 'role', 'group', 'permission', 'permissions', 'get', 'set',
    'create', 'update', 'delete', 'list', 'find', 'check', 'can', 'grant', 'revoke', 'login', 'logout',
    'password', 'token', 'session', 'address', 'field', 'value', 'values', 'result', 'results',
    'items', 'count', 'error', 'message', 'config', 'file', 'path', 'key', 'model',
    'query', 'request', 'response', 'handle', 'build', 'make', 'load', 'save', 'read', 'write', 'send',
    'start', 'stop', 'run', 'level', 'parent', 'child', 'owner', 'access', 'allowed', 'created', 'updated',
    'enabled', 'valid', 'invalid', 'default', 'validate', 'normalize', 'helper', 'utils', 'manager',
    'service', 'handler', 'context', 'connection', 'cursor', 'table', 'row', 'rows', 'schema',
}


def _palavras(nome):
    return [t.lower() for t in re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+', nome)]


def _ingles(palavra):
    # Palavra da lista, ou o plural dela; a palavra inteira vem antes ('access' não vira 'acces').
    return palavra in INGLES or (palavra.endswith('s') and palavra[:-1] in INGLES)


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
        elif isinstance(no, ast.ExceptHandler) and no.name:
            yield no.name
        elif isinstance(no, (ast.MatchAs, ast.MatchStar)) and no.name:
            yield no.name
        elif isinstance(no, ast.MatchMapping) and no.rest:
            yield no.rest


def achados_em(codigo):
    """Devolve os identificadores em inglês do código dado."""
    nomes = {n for n in _definidos(ast.parse(codigo)) if n not in PERMITIDOS and not (n.startswith('__') and n.endswith('__'))}
    return sorted(n for n in nomes if any(_ingles(p) for p in _palavras(n)))


def test_detecta_identificador_em_ingles():
    assert achados_em('def get_user(): pass') == ['get_user']
    assert achados_em('class UserGroup:\n    nome_do_grupo = 1') == ['UserGroup']
    assert achados_em('def buscar_fazendas_autorizadas(pessoa): pass') == []


def test_palavra_inglesa_que_termina_em_s_e_palavra_portuguesa_ambigua():
    assert achados_em('access = 1') == ['access']
    assert achados_em('tokens = 1') == ['tokens']
    # 'data' (dia) e 'total' são palavras do português: não podem ser barradas.
    assert achados_em('data = 1') == []
    assert achados_em('valor_total = 2') == []


def test_nomes_de_except_e_de_match_tambem_contam():
    assert achados_em('try: pass\nexcept Exception as error: pass') == ['error']
    assert achados_em('try: pass\nexcept Exception as erro: pass') == []
    assert achados_em('match x:\n case [result, *values]: pass') == ['result', 'values']
    assert achados_em('match x:\n case {"a": 1, **results}: pass') == ['results']
    assert achados_em('match x:\n case {"a": 1, **resto}: pass') == []


def test_dunder_do_python_passa_mas_dois_underscores_de_nome_ingles_nao():
    assert achados_em('class Empresa:\n    def __init__(self): pass') == []
    assert achados_em('def __get_user(): pass') == ['__get_user']
    assert achados_em('_tokens = 1') == ['_tokens']


def test_identificadores_do_servidor_em_portugues():
    achados = {}
    for arquivo in RAIZ.rglob('*.py'):
        if 'migrations' in arquivo.parts or '.venv' in arquivo.parts:
            continue
        nomes = achados_em(arquivo.read_text(encoding='utf-8'))
        if nomes:
            achados[str(arquivo.relative_to(RAIZ))] = nomes
    assert achados == {}
