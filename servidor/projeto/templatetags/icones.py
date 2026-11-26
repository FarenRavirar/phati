"""Tag `{% icone "nome" %}`: embute inline o SVG Lucide de static/projeto/agrion/icones/ (spec 012, R4 e R12).

O SVG é a cópia do pacote AgriOn, com integridade conferida em projeto/testes/test_agrion_copia.py. A saída não tem
`style=`: tamanho e traço são atributos SVG (`width`, `height`, `stroke-width`), e a CSP do projeto não pede `unsafe-inline`.
Registrada em `TEMPLATES[...]['OPTIONS']['builtins']` (settings.py), então o template não precisa de `{% load %}`.
"""

import functools
import re
from pathlib import Path

from django import template
from django.template import TemplateSyntaxError
from django.utils.html import format_html
from django.utils.safestring import SafeString

register = template.Library()

PASTA_ICONES = Path(__file__).resolve().parent.parent / 'static' / 'projeto' / 'agrion' / 'icones'
TAMANHOS = (12, 14, 16, 18, 20, 36)
TAMANHO_PADRAO = 16
TRACO_PADRAO = 1.75
# Só minúsculas, dígitos e hífen: barra, ponto, `..` e vazio não casam, então a leitura nunca sai da pasta.
NOME_VALIDO = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*')
SVG = re.compile(r'<svg\b[^>]*\bviewBox="([^"]+)"[^>]*>(.*?)</svg>', re.DOTALL)


@functools.lru_cache(maxsize=None)
def _conteudo(nome):
    # Chamada só com `nome` já validado por NOME_VALIDO. Erro não fica em cache (lru_cache não guarda exceção).
    try:
        texto = (PASTA_ICONES / f'{nome}.svg').read_text(encoding='utf-8')
    except FileNotFoundError:
        raise TemplateSyntaxError(f'ícone inexistente: {nome!r}') from None
    casado = SVG.search(texto)
    if casado is None:
        raise TemplateSyntaxError(f'ícone sem SVG válido: {nome!r}')
    return casado.group(1), casado.group(2)


@register.simple_tag
def icone(nome, tamanho=TAMANHO_PADRAO, traco=TRACO_PADRAO, rotulo=None, classe=None):
    if not isinstance(nome, str) or not NOME_VALIDO.fullmatch(nome):
        raise TemplateSyntaxError(f'nome de ícone inválido: {nome!r}')
    # `type(...) is int`: 16.0 e True passariam por `in`/isinstance e sairiam como "16.0" ou "1".
    if type(tamanho) is not int or tamanho not in TAMANHOS:
        raise TemplateSyntaxError(f'tamanho de ícone fora de {TAMANHOS}: {tamanho!r}')
    if type(traco) not in (int, float) or not 0 < traco <= 4:
        raise TemplateSyntaxError(f'traço de ícone inválido (0 < traco <= 4): {traco!r}')
    viewbox, miolo = _conteudo(nome)
    classes = f'ag-icone {classe}' if classe else 'ag-icone'
    # Com rótulo o ícone é imagem com nome; sem rótulo é decorativo e some para a leitura de tela.
    acessivel = format_html('role="img" aria-label="{}"', rotulo) if rotulo else SafeString('aria-hidden="true"')
    return format_html(
        '<svg class="{}" width="{}" height="{}" viewBox="{}" fill="none" '
        'stroke="currentColor" stroke-width="{}" stroke-linecap="round" stroke-linejoin="round" {} focusable="false">'
        '{}</svg>',
        classes, tamanho, tamanho, viewbox, traco, acessivel, SafeString(miolo),
    )
