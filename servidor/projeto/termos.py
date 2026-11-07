"""Termos de uso e Política de privacidade (004b R15, A11): páginas públicas, com o texto do mantenedor.

O texto vem de arquivo local, fora do repositório (`PHATI_TERMOS_ARQUIVO`, JSON com as chaves `termos` e `privacidade`; cada
valor é texto simples, parágrafos separados por linha em branco). Sem o texto a página só existe em `PHATI_AMBIENTE=local`,
com aviso de texto ausente; fora do local responde 404 e o rodapé não a linka.
"""

import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_GET

REGISTRO = logging.getLogger(__name__)
SECOES = {'termos': 'Termos de uso', 'privacidade': 'Política de privacidade'}
# Os dois documentos que a cláusula 3.2.2(a)(i) dos termos do Google Maps Platform manda os termos do aplicativo citar.
TERMO_DO_GOOGLE = 'https://maps.google.com/help/terms_maps/'
PRIVACIDADE_DO_GOOGLE = 'https://policies.google.com/privacy'
SEM_TEXTO = 'O texto do mantenedor ainda não foi fornecido (aviso só do ambiente local).'


@lru_cache(maxsize=8)
def _interpretar(caminho, _versao):
    """Lê e valida o arquivo. `_versao` (mtime) só entra na chave do cache: arquivo trocado é lido de novo."""
    try:
        dados = json.loads(Path(caminho).read_text(encoding='utf-8'))
    except (OSError, ValueError):  # ilegível ou JSON inválido: sem texto, e a causa fica no log
        REGISTRO.exception('Texto dos termos ilegível.')
        return {}
    if not isinstance(dados, dict):
        return {}
    return {chave: valor for chave, valor in dados.items() if chave in SECOES and isinstance(valor, str) and valor.strip()}


def _ler():
    """Textos válidos por seção. O rodapé consulta isto a cada página, então o arquivo só é relido quando muda."""
    caminho = settings.TERMOS_ARQUIVO
    if not caminho:
        return {}
    try:
        versao = os.stat(caminho).st_mtime_ns
    except OSError:  # arquivo ausente: sem texto, e a causa fica no log
        REGISTRO.exception('Texto dos termos ilegível.')
        return {}
    return _interpretar(caminho, versao)


def paragrafos(secao):
    """Parágrafos do texto do mantenedor, ou `None` se ele não existe."""
    texto = _ler().get(secao)
    return None if texto is None else [p.strip() for p in re.split(r'\n\s*\n', texto) if p.strip()]


def disponivel(secao):
    """A página responde: há texto do mantenedor ou o ambiente é `local`."""
    return paragrafos(secao) is not None or settings.AMBIENTE == 'local'


def disponiveis(_requisicao):
    """Variável de contexto do rodapé: o link só aparece para a página que de fato responde. Rota ausente (urlconf de
    teste, página de erro) tira o rodapé em vez de derrubar a página."""
    try:
        return {'termos_links': [(reverse(secao), SECOES[secao]) for secao in SECOES if disponivel(secao)]}
    except NoReverseMatch:
        return {'termos_links': []}


@require_GET
def pagina(requisicao, secao):
    """Página pública de `secao`; 404 para seção desconhecida ou sem texto fora do ambiente local."""
    if secao not in SECOES:
        raise Http404
    texto = paragrafos(secao)
    if texto is None:
        if settings.AMBIENTE != 'local':
            raise Http404
        texto = [SEM_TEXTO]
    contexto = {
        'titulo': SECOES[secao], 'paragrafos': texto, 'termo_do_google': TERMO_DO_GOOGLE,
        'privacidade_do_google': PRIVACIDADE_DO_GOOGLE,
    }
    return render(requisicao, 'termos.html', contexto)
