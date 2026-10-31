"""Matriz backend ↔ frontend (R21, A16): rota, função de serviço e ação do catálogo têm tela ou justificativa.

A matriz é comparada com o código, não só relida: rota, função pública dos módulos de serviço ou ação do catálogo
sem linha faz o teste falhar, e função citada que não importa mais também (achado do Qodo e do Greptile, PR #22).
"""

import importlib
import inspect
import json
from pathlib import Path

import pytest
from django.urls import URLPattern

from permissao.models import Permissao
from projeto.api import api

MATRIZ = Path(__file__).resolve().parent.parent / 'cobertura_front.json'


def _matriz():
    return json.loads(MATRIZ.read_text(encoding='utf-8'))


def _rotas_da_api():
    return {padrao.name for padrao in api.urls[0] if isinstance(padrao, URLPattern) and padrao.name and padrao.name != 'api-root'}


def _importa(caminho):
    modulo, _, nome = caminho.rpartition('.')
    return getattr(importlib.import_module(modulo), nome, None)


def _funcoes_publicas(modulos):
    """`modulo.funcao` de cada função definida (não importada) em `modulos`, sem as que começam por `_`."""
    achadas = set()
    for nome_do_modulo in modulos:
        modulo = importlib.import_module(nome_do_modulo)
        for nome, funcao in inspect.getmembers(modulo, inspect.isfunction):
            if funcao.__module__ == nome_do_modulo and not nome.startswith('_'):
                achadas.add(f'{nome_do_modulo}.{nome}')
    return achadas


def test_toda_rota_da_api_tem_linha_com_texto():
    matriz = _matriz()['rotas']
    sem_linha = _rotas_da_api() - set(matriz)
    assert not sem_linha, f'rota sem linha na matriz: {sorted(sem_linha)}'
    assert all(texto.strip() for texto in matriz.values())


def test_rota_nova_sem_linha_e_detectada():
    matriz = _matriz()['rotas']
    matriz.pop('fazendas_listar')
    assert _rotas_da_api() - set(matriz) == {'fazendas_listar'}


def test_toda_funcao_citada_importa():
    citadas = _matriz()['funcoes']
    assert citadas
    nao_importam = [caminho for caminho in citadas if _importa(caminho) is None]
    assert not nao_importam, f'função citada que não importa: {nao_importam}'


def test_funcao_inexistente_e_detectada():
    assert _importa('permissao.convite.funcao_que_nao_existe') is None
    with pytest.raises(ModuleNotFoundError):
        _importa('modulo_que_nao_existe.funcao')


def test_toda_funcao_publica_dos_modulos_de_servico_tem_linha_com_texto():
    matriz = _matriz()
    sem_linha = _funcoes_publicas(matriz['modulos']) - set(matriz['funcoes'])
    assert not sem_linha, f'função pública sem linha na matriz: {sorted(sem_linha)}'
    assert all(texto.strip() for texto in matriz['funcoes'].values())


def test_funcao_publica_nova_sem_linha_e_detectada():
    matriz = _matriz()
    matriz['funcoes'].pop('territorio.cadastro.criar_fazenda')
    assert _funcoes_publicas(matriz['modulos']) - set(matriz['funcoes']) == {'territorio.cadastro.criar_fazenda'}


@pytest.mark.django_db
def test_toda_acao_do_catalogo_tem_linha_com_texto_e_nenhuma_linha_sobra():
    acoes = _matriz()['acoes']
    catalogo = set(Permissao.objects.values_list('codigo', flat=True))
    assert catalogo - set(acoes) == set()
    assert set(acoes) - catalogo == set()
    assert all(estado.strip() for estado in acoes.values())


@pytest.mark.django_db
def test_acao_nova_no_catalogo_sem_linha_e_detectada():
    acoes = _matriz()['acoes']
    acoes.pop('ver')
    catalogo = set(Permissao.objects.values_list('codigo', flat=True))
    assert catalogo - set(acoes) == {'ver'}
