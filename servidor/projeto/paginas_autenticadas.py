"""Páginas da casca autenticada: portão de sessão (R5, R8) e renderização no molde único (R1)."""

import re
from functools import lru_cache, wraps
from pathlib import Path
from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from identidade import sessao
from permissao.pode import pode
from projeto.menu import itens_do_menu

CAMINHO_ENTRAR = '/entrar'
CAMINHO_TROCAR_SENHA = '/trocar-senha'
# Ação que só toca a própria pessoa (trocar a senha, responder ao convite dela): sem alvo de terceiro, sem `pode()`.
PROPRIA_PESSOA = 'propria_pessoa'


@lru_cache(maxsize=1)
def _cor_do_tema():
    """Cor do `<meta name="theme-color">`: lida de `--cor-primaria` em `tokens.css`, a única fonte de cor (R4, R13 da 002)."""
    variaveis = (Path(__file__).parent / 'static' / 'projeto' / 'tokens.css').read_text(encoding='utf-8')
    return re.findall(r'--cor-primaria:\s*(#[0-9A-Fa-f]{6})', variaveis)[0]


def destino_seguro(destino):
    """`proximo` só vale como caminho do próprio site; endereço externo ou vazio volta para `/` (R8)."""
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts=set()):
        return destino
    return '/'


def _proximo_de(requisicao):
    # Só GET volta pelo endereço: depois do login um POST (Aceitar, Recusar) viraria GET e daria 405; a pessoa cai em `/`.
    return requisicao.get_full_path() if requisicao.method in ('GET', 'HEAD') else None


def _com_proximo(caminho, requisicao, **consulta):
    proximo = _proximo_de(requisicao)
    if proximo is not None:
        consulta = {'proximo': proximo, **consulta}
    return f'{caminho}?{urlencode(consulta)}' if consulta else caminho


def exige_acao(acao):
    """Declara a ação do catálogo que a página exige (R22); a varredura de views confere que toda página autenticada
    declara uma. A checagem em si fica em `resolver_escopo`/listagens, a mesma da API."""

    def declarar(visao):
        visao.acao_exigida = acao
        return visao

    return declarar


def exige_entrada(visao):
    """Sem sessão vigente vai ao login, com a página pedida em `proximo`; senha temporária só vê a troca."""

    @wraps(visao)
    @never_cache
    def interna(requisicao, *args, **kwargs):
        pessoa = requisicao.user
        estava_logada = pessoa.is_authenticated
        if not (estava_logada and sessao.sessao_vigente(requisicao)):
            # A tela de login mostra "Sua sessão expirou." (R8)
            return redirect(_com_proximo(CAMINHO_ENTRAR, requisicao, **({'expirou': '1'} if estava_logada else {})))
        if pessoa.deve_trocar_senha and requisicao.path != CAMINHO_TROCAR_SENHA:
            return redirect(_com_proximo(CAMINHO_TROCAR_SENHA, requisicao))
        return visao(requisicao, *args, **kwargs)

    setattr(interna, 'exige_entrada', True)  # marca para a varredura de views (o pyright não admite atributo em função)
    return interna


def renderizar_na_casca(requisicao, modelo, contexto=None, empresa=None, fazenda=None):
    """Renderiza `modelo` (que estende `casca.html`) com o menu da pessoa no escopo atual (a fazenda, ou a empresa)."""
    itens = itens_do_menu(requisicao.user, fazenda or empresa, requisicao.path)
    base = {'itens_menu': itens, 'empresa': empresa, 'fazenda': fazenda, 'cor_do_tema': _cor_do_tema()}
    return render(requisicao, modelo, {**(contexto or {}), **base})


# Peças comuns das telas de gestão (território e pessoas). Moram aqui, fora dos `*_paginas.py`, para as views só
# declararem e chamarem o serviço: a pergunta de permissão fica num lugar só (003 R28, A26).


LEITURA_E_ESCRITA = require_http_methods(['GET', 'POST'])


def pagina(acao):
    """Portão de sessão, métodos GET e POST e a ação do catálogo que a página declara (varredura de views, R22)."""

    def declarar(visao):
        return LEITURA_E_ESCRITA(exige_entrada(exige_acao(acao)(visao)))

    return declarar


def exigir(requisicao, acao, alvo=None):
    """Alcance sem a ação: 403 (a regra é a mesma da API)."""
    if not pode(requisicao.user, acao, alvo):
        raise PermissionDenied


def campo(nome, rotulo, valor='', erro=None, ajuda=None, **extra):
    return {'id': f'campo_{nome}', 'nome': nome, 'rotulo': rotulo, 'valor': valor, 'erro': erro, 'ajuda': ajuda, **extra}


def texto_do_erro(erro):
    return ' '.join(erro.messages)


def formulario(requisicao, titulo, campos, botao, cancelar, *, subtitulo=None, erro=None, empresa=None, fazenda=None, acoes=(), escondidos=None, codigo_http=200):
    contexto = {
        'titulo': titulo, 'subtitulo': subtitulo, 'campos': campos, 'botao': botao, 'cancelar': cancelar,
        'erro': erro, 'acoes': list(acoes), 'escondidos': escondidos or {},
    }
    resposta = renderizar_na_casca(requisicao, 'formulario.html', contexto, empresa=empresa, fazenda=fazenda)
    resposta.status_code = codigo_http
    return resposta


def confirmacao(requisicao, cancelar, *, titulo, texto, efeitos, botao, empresa=None, fazenda=None, escondidos=None, erro=None, codigo_http=200):
    contexto = {
        'titulo': titulo, 'texto': texto, 'efeitos': efeitos, 'botao': botao, 'cancelar': cancelar,
        'escondidos': escondidos or {}, 'erro': erro,
    }
    resposta = renderizar_na_casca(requisicao, 'confirmacao.html', contexto, empresa=empresa, fazenda=fazenda)
    resposta.status_code = codigo_http
    return resposta
