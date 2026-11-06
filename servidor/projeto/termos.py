"""Termos de uso e Política de privacidade (004b R15, A11): páginas públicas, com o texto do mantenedor.

O texto vem de arquivo local, fora do repositório (`PHATI_TERMOS_ARQUIVO`, JSON com as chaves `termos` e `privacidade`; cada
valor é texto simples, parágrafos separados por linha em branco). Sem o texto a página só existe em `PHATI_AMBIENTE=local`,
com aviso de texto ausente; fora do local responde 404 e o rodapé não a linka.
"""

import json
import logging
from pathlib import Path

from django.conf import settings
from django.http import Http404
from django.shortcuts import render
from django.urls import NoReverseMatch, reverse
from django.views.decorators.http import require_GET

REGISTRO = logging.getLogger(__name__)
SECOES = {'termos': 'Termos de uso', 'privacidade': 'Política de privacidade'}
TERMO_DO_GOOGLE = 'https://cloud.google.com/maps-platform/terms'
SEM_TEXTO = 'O texto do mantenedor ainda não foi fornecido (aviso só do ambiente local).'


def _ler():
    caminho = settings.TERMOS_ARQUIVO
    if not caminho:
        return {}
    try:
        dados = json.loads(Path(caminho).read_text(encoding='utf-8'))
    except (OSError, ValueError):  # arquivo ausente, ilegível ou JSON inválido: sem texto, e a causa fica no log
        REGISTRO.exception('Texto dos termos ilegível.')
        return {}
    if not isinstance(dados, dict):
        return {}
    return {chave: valor for chave, valor in dados.items() if chave in SECOES and isinstance(valor, str) and valor.strip()}


def paragrafos(secao):
    """Parágrafos do texto do mantenedor, ou `None` se ele não existe."""
    texto = _ler().get(secao)
    return None if texto is None else [p.strip() for p in texto.split('\n\n') if p.strip()]


def disponivel(secao):
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
    if secao not in SECOES:
        raise Http404
    texto = paragrafos(secao)
    if texto is None:
        if settings.AMBIENTE != 'local':
            raise Http404
        texto = [SEM_TEXTO]
    contexto = {
        'titulo': SECOES[secao], 'paragrafos': texto, 'termo_do_google': TERMO_DO_GOOGLE,
        'beacon': secao == 'privacidade',
    }
    return render(requisicao, 'termos.html', contexto)
