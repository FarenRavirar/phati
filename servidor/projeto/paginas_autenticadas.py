"""Páginas da casca autenticada: portão de sessão (R5, R8) e renderização no molde único (R1)."""

import re
from functools import lru_cache, wraps
from pathlib import Path
from urllib.parse import urlencode

from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.cache import add_never_cache_headers
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods

from identidade import sessao
from permissao.pode import pode
from projeto.escopo import cargos_na_empresa, empresa_lembrada, seletor_da_pessoa
from projeto.menu import itens_do_menu, trilha_da

CAMINHO_ENTRAR = '/entrar'
CAMINHO_TROCAR_SENHA = '/trocar-senha'
# Ação que só toca a própria pessoa (trocar a senha, responder ao convite dela): sem alvo de terceiro, sem `pode()`.
PROPRIA_PESSOA = 'propria_pessoa'


@lru_cache(maxsize=1)
def _cor_do_tema():
    """Cor do `<meta name="theme-color">`: lida de `--marca-verde` em `agrion/tokens/colors.css` (pacote AgriOn, spec 012), a única fonte de cor."""
    variaveis = (Path(__file__).parent / 'static' / 'projeto' / 'agrion' / 'tokens' / 'colors.css').read_text(encoding='utf-8')
    return re.findall(r'--marca-verde:\s*(#[0-9A-Fa-f]{6})', variaveis)[0]


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


def cache_proprio(visao):
    """Marca a view que define o próprio `Cache-Control` (hoje, só a rota das camadas, com `ETag` privado): `exige_entrada`
    não põe `no-store` por cima da resposta dela. Achado real (review PR #44, Greptile, média): sem a marca o `never_cache`
    sobrescrevia o cabeçalho e o navegador nunca guardava o corpo. Fica na view mais interna: `wraps` leva o atributo adiante."""
    setattr(visao, 'cache_proprio', True)
    return visao


def exige_entrada(visao):
    """Sem sessão vigente vai ao login, com a página pedida em `proximo`; senha temporária só vê a troca."""
    proprio = getattr(visao, 'cache_proprio', False)

    @wraps(visao)
    def interna(requisicao, *args, **kwargs):
        pessoa = requisicao.user
        estava_logada = pessoa.is_authenticated
        if not (estava_logada and sessao.sessao_vigente(requisicao)):
            # A tela de login mostra "Sua sessão expirou." (R8)
            resposta = redirect(_com_proximo(CAMINHO_ENTRAR, requisicao, **({'expirou': '1'} if estava_logada else {})))
        elif pessoa.deve_trocar_senha and requisicao.path != CAMINHO_TROCAR_SENHA:
            resposta = redirect(_com_proximo(CAMINHO_TROCAR_SENHA, requisicao))
        else:
            resposta = visao(requisicao, *args, **kwargs)
            if proprio:
                return resposta  # só a resposta da própria view; redirecionamentos seguem sem cache
        add_never_cache_headers(resposta)
        return resposta

    setattr(interna, 'exige_entrada', True)  # marca para a varredura de views (o pyright não admite atributo em função)
    return interna


def renderizar_na_casca(requisicao, modelo, contexto=None, empresa=None, fazenda=None, sub_area=None, etapa=''):
    """Renderiza `modelo` (que estende `casca.html`) com o menu da pessoa no escopo atual (a fazenda, ou a empresa).
    Sem empresa na URL, a escolhida no seletor (R17) vale para Pessoas e Cargos; a da URL prevalece (D063).
    `sub_area` e `etapa` completam a trilha (telas.md §0)."""
    escolhida = empresa or empresa_lembrada(requisicao)
    itens = itens_do_menu(requisicao.user, fazenda or empresa, requisicao.path, empresa=escolhida)
    base = {
        'itens_menu': itens, 'trilha_do_topo': trilha_da(itens, empresa, fazenda, sub_area, etapa), 'empresa': empresa, 'fazenda': fazenda,
        'empresa_escolhida': escolhida, 'seletor': seletor_da_pessoa(requisicao.user), 'cargos_da_empresa': cargos_na_empresa(requisicao.user, escolhida),
        'cor_do_tema': _cor_do_tema(),
    }
    return render(requisicao, modelo, {**(contexto or {}), **base})


# Peças comuns das telas de gestão (território e pessoas). Moram aqui, fora dos `*_paginas.py`, para as views só
# declararem e chamarem o serviço: a pergunta de permissão fica num lugar só (003 R28, A26).


LEITURA_E_ESCRITA = require_http_methods(['GET', 'POST'])


def pagina(acao):
    """Portão de sessão, métodos GET e POST e a ação do catálogo que a página declara (varredura de views, R22)."""

    def declarar(visao):
        return LEITURA_E_ESCRITA(exige_entrada(exige_acao(acao)(visao)))

    return declarar


def exigir(requisicao, acao, alvo=None, *, nao_encontrado=False):
    """Alcance sem a ação: 403 (a regra é a mesma da API). `nao_encontrado=True` responde 404, o de alvo inexistente (telas que
    escondem a existência da fazenda, como as de camadas)."""
    if not pode(requisicao.user, acao, alvo):
        raise Http404 if nao_encontrado else PermissionDenied


def campo(nome, rotulo, valor='', erro=None, ajuda=None, **extra):
    return {'id': f'campo_{nome}', 'nome': nome, 'rotulo': rotulo, 'valor': valor, 'erro': erro, 'ajuda': ajuda, **extra}


def texto_do_erro(erro):
    return ' '.join(erro.messages)


def formulario(requisicao, titulo, campos, botao, cancelar, *, subtitulo=None, erro=None, acoes=(), escondidos=None, historico=None, codigo_http=200, **lugar):
    """`lugar` (`empresa`, `fazenda`, `sub_area`) vai à casca. `historico`: `{titulo, linhas, vazio}`, uma lista só de leitura que aparece depois do formulário. `sub_area`: a trilha
    leva até ela (renomear sub-área)."""
    contexto = {
        'titulo': titulo, 'subtitulo': subtitulo, 'campos': campos, 'botao': botao, 'cancelar': cancelar,
        'erro': erro, 'acoes': list(acoes), 'escondidos': escondidos or {}, 'historico': historico,
    }
    resposta = renderizar_na_casca(requisicao, 'formulario.html', contexto, **lugar)
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
