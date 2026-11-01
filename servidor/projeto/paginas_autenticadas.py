"""Páginas da casca autenticada: portão de sessão (R5, R8) e renderização no molde único (R1)."""

import re
from functools import lru_cache, wraps
from pathlib import Path
from urllib.parse import urlencode

from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache

from identidade import sessao
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
