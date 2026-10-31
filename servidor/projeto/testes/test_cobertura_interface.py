"""Matriz backend ↔ interface (R21, A16): rota, função de serviço e ação do catálogo têm tela ou justificativa.

A matriz é comparada com o código, não só relida: rota, função pública dos módulos de serviço ou ação do catálogo
sem linha faz o teste falhar, e linha que sobrou ou função citada que não importa mais também (achados do Qodo, do
Greptile e do CodeRabbit, PR #22). Cada validação é uma função; os casos negativos chamam a mesma função com uma
matriz adulterada, então remover a validação os reprova.
"""

import importlib
import inspect
import json
from pathlib import Path

import pytest
from django.urls import URLPattern

from permissao.models import Permissao
from projeto.api import api

RAIZ = Path(__file__).resolve().parents[2]
MATRIZ = RAIZ / 'projeto' / 'cobertura_interface.json'
APLICACOES = ('comum', 'identidade', 'permissao', 'territorio')
# Arquivos que não são serviço: rotas (a matriz as cobre por `rotas`), modelos, admin, config do app e checagens.
NAO_SAO_SERVICO = {'__init__', 'apps', 'admin', 'api', 'models', 'checks'}


def _matriz():
    return json.loads(MATRIZ.read_text(encoding='utf-8'))


def _rotas_da_api():
    return {padrao.name for padrao in api.urls[0] if isinstance(padrao, URLPattern) and padrao.name and padrao.name != 'api-root'}


def _importa(caminho):
    modulo, _, nome = caminho.rpartition('.')
    return getattr(importlib.import_module(modulo), nome, None)


def _modulos_de_servico():
    """Descobertos no disco, não lidos da matriz: arquivo novo de serviço entra na checagem sozinho."""
    return sorted(
        f'{aplicacao}.{arquivo.stem}'
        for aplicacao in APLICACOES
        for arquivo in (RAIZ / aplicacao).glob('*.py')
        if arquivo.stem not in NAO_SAO_SERVICO
    )


def _funcoes_publicas(modulos):
    """`modulo.funcao` de cada função definida (não importada) em `modulos`, sem as que começam por `_`."""
    achadas = set()
    for nome_do_modulo in modulos:
        modulo = importlib.import_module(nome_do_modulo)
        for nome, funcao in inspect.getmembers(modulo, inspect.isfunction):
            if funcao.__module__ == nome_do_modulo and not nome.startswith('_'):
                achadas.add(f'{nome_do_modulo}.{nome}')
    return achadas


def _problemas_das_rotas(rotas):
    problemas = [f'rota sem linha: {nome}' for nome in sorted(_rotas_da_api() - set(rotas))]
    problemas += [f'linha sem rota: {nome}' for nome in sorted(set(rotas) - _rotas_da_api())]
    return problemas + [f'rota sem texto: {nome}' for nome, texto in rotas.items() if not texto.strip()]


def _problemas_das_funcoes(funcoes):
    problemas = [f'função pública sem linha: {nome}' for nome in sorted(_funcoes_publicas(_modulos_de_servico()) - set(funcoes))]
    problemas += [f'função citada que não importa: {nome}' for nome in sorted(funcoes) if _importa(nome) is None]
    return problemas + [f'função sem texto: {nome}' for nome, texto in funcoes.items() if not texto.strip()]


def _problemas_das_acoes(acoes):
    catalogo = set(Permissao.objects.values_list('codigo', flat=True))
    problemas = [f'ação do catálogo sem linha: {nome}' for nome in sorted(catalogo - set(acoes))]
    problemas += [f'linha sem ação no catálogo: {nome}' for nome in sorted(set(acoes) - catalogo)]
    return problemas + [f'ação sem texto: {nome}' for nome, texto in acoes.items() if not texto.strip()]


def test_a_matriz_cobre_todas_as_rotas_sem_linha_sobrando():
    assert _problemas_das_rotas(_matriz()['rotas']) == []


def test_rota_sem_linha_ou_linha_sem_rota_ou_sem_texto_e_detectada():
    rotas = _matriz()['rotas']
    sem_linha = {nome: texto for nome, texto in rotas.items() if nome != 'fazendas_listar'}
    assert _problemas_das_rotas(sem_linha) == ['rota sem linha: fazendas_listar']
    assert _problemas_das_rotas({**rotas, 'rota_que_nao_existe': 'x'}) == ['linha sem rota: rota_que_nao_existe']
    assert _problemas_das_rotas({**rotas, 'sair': ' '}) == ['rota sem texto: sair']


def test_a_matriz_cobre_toda_funcao_publica_dos_modulos_de_servico_e_todas_importam():
    assert _problemas_das_funcoes(_matriz()['funcoes']) == []


def test_funcao_sem_linha_inexistente_ou_sem_texto_e_detectada():
    funcoes = _matriz()['funcoes']
    sem_linha = {nome: texto for nome, texto in funcoes.items() if nome != 'territorio.cadastro.criar_fazenda'}
    assert _problemas_das_funcoes(sem_linha) == ['função pública sem linha: territorio.cadastro.criar_fazenda']
    fantasma = 'permissao.convite.funcao_que_nao_existe'
    assert _problemas_das_funcoes({**funcoes, fantasma: 'x'}) == [f'função citada que não importa: {fantasma}']
    assert _problemas_das_funcoes({**funcoes, 'comum.sintetico.cpf_sintetico': ''}) == ['função sem texto: comum.sintetico.cpf_sintetico']


def test_modulo_inexistente_na_matriz_levanta_erro_de_importacao():
    with pytest.raises(ModuleNotFoundError):
        _importa('modulo_que_nao_existe.funcao')


def test_os_modulos_de_servico_descobertos_incluem_os_que_a_matriz_ja_citava():
    descobertos = set(_modulos_de_servico())
    assert {'identidade.cpf', 'permissao.contexto', 'territorio.cadastro'} <= descobertos
    assert 'identidade.api' not in descobertos


@pytest.mark.django_db
def test_a_matriz_cobre_todas_as_acoes_do_catalogo_sem_linha_sobrando():
    assert _problemas_das_acoes(_matriz()['acoes']) == []


@pytest.mark.django_db
def test_acao_sem_linha_ou_linha_sem_acao_ou_sem_texto_e_detectada():
    acoes = _matriz()['acoes']
    sem_linha = {nome: texto for nome, texto in acoes.items() if nome != 'ver'}
    assert _problemas_das_acoes(sem_linha) == ['ação do catálogo sem linha: ver']
    assert _problemas_das_acoes({**acoes, 'acao_que_nao_existe': 'x'}) == ['linha sem ação no catálogo: acao_que_nao_existe']
    assert _problemas_das_acoes({**acoes, 'ver': ''}) == ['ação sem texto: ver']
