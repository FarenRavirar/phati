"""Páginas da casca autenticada: portão de sessão (R5, R8) e renderização no molde único (R1)."""

from functools import wraps
from urllib.parse import urlencode

from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache

from identidade import sessao
from projeto.menu import itens_do_menu

CAMINHO_ENTRAR = '/entrar'
CAMINHO_TROCAR_SENHA = '/trocar-senha'


def destino_seguro(destino):
    """`proximo` só vale como caminho do próprio site; endereço externo ou vazio volta para `/` (R8)."""
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts=set()):
        return destino
    return '/'


def exige_entrada(visao):
    """Sem sessão vigente vai ao login, com a página pedida em `proximo`; senha temporária só vê a troca."""

    @wraps(visao)
    @never_cache
    def interna(requisicao, *args, **kwargs):
        pessoa = requisicao.user
        estava_logada = pessoa.is_authenticated
        if not (estava_logada and sessao.sessao_vigente(requisicao)):
            consulta = {'proximo': requisicao.get_full_path()}
            if estava_logada:
                consulta['expirou'] = '1'  # a tela de login mostra "Sua sessão expirou." (R8)
            return redirect(f'{CAMINHO_ENTRAR}?{urlencode(consulta)}')
        if pessoa.deve_trocar_senha and requisicao.path != CAMINHO_TROCAR_SENHA:
            return redirect(f'{CAMINHO_TROCAR_SENHA}?{urlencode({"proximo": requisicao.get_full_path()})}')
        return visao(requisicao, *args, **kwargs)

    return interna


def renderizar_na_casca(requisicao, modelo, contexto=None, empresa=None, fazenda=None):
    """Renderiza `modelo` (que estende `casca.html`) com o menu da pessoa no escopo atual (a fazenda, ou a empresa)."""
    itens = itens_do_menu(requisicao.user, fazenda or empresa)
    return render(requisicao, modelo, {**(contexto or {}), 'itens_menu': itens, 'empresa': empresa, 'fazenda': fazenda})
