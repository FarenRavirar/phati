"""Matriz backend ↔ frontend (R21, A16): toda rota de `/api/v1/` tem tela ou justificativa, e toda função citada existe."""

import importlib
import json
from pathlib import Path

import pytest
from django.urls import URLPattern

from projeto.api import api

MATRIZ = Path(__file__).resolve().parent.parent / 'cobertura_front.json'


def _matriz():
    return json.loads(MATRIZ.read_text(encoding='utf-8'))


def _rotas_da_api():
    return {padrao.name for padrao in api.urls[0] if isinstance(padrao, URLPattern) and padrao.name and padrao.name != 'api-root'}


def _importa(caminho):
    modulo, _, nome = caminho.rpartition('.')
    return getattr(importlib.import_module(modulo), nome, None)


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


def test_toda_acao_tem_estado():
    acoes = _matriz()['acoes']
    assert acoes and all(estado.strip() for estado in acoes.values())
