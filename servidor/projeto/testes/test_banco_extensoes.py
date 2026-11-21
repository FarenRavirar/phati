import re
from pathlib import Path

from django.conf import settings

COMPOSE = (Path(settings.DIRETORIO_BASE) / 'compose.yaml').read_text(encoding='utf-8')


def _bloco(nome):
    # Sem PyYAML no venv: recorta a chave de 2 espaços em `services:` até a próxima do mesmo nível.
    linhas = COMPOSE.splitlines()
    inicio = linhas.index(f'  {nome}:')
    fim = next((i for i in range(inicio + 1, len(linhas)) if re.match(r'  [a-z_]+:\s*$|\S', linhas[i])), len(linhas))
    return '\n'.join(linhas[inicio:fim])


def _ambiente_compartilhado():
    linhas = COMPOSE.splitlines()
    inicio = linhas.index('x-ambiente-app: &ambiente_app')
    fim = next(i for i in range(inicio + 1, len(linhas)) if linhas[i] == '')
    return '\n'.join(linhas[inicio:fim])


def test_banco_extensoes_roda_o_script_com_superusuario_e_espera_o_banco():
    bloco = _bloco('banco_extensoes')
    assert 'entrypoint: ["sh", "/atualizar-postgis.sh"]' in bloco
    assert 'PGPASSWORD: ${PHATI_BANCO_SUPER_SENHA:?}' in bloco
    assert './banco/atualizar-postgis.sh:/atualizar-postgis.sh:ro' in bloco
    assert 'banco: {condition: service_healthy}' in bloco


def test_migracao_so_roda_depois_das_extensoes():
    assert 'banco_extensoes: {condition: service_completed_successfully}' in _bloco('migracao')


def test_superusuario_nao_chega_ao_app_nem_a_migracao():
    # Caso negativo: a senha do superusuário fica só no serviço de extensões.
    assert 'PHATI_BANCO_SUPER_SENHA' not in _ambiente_compartilhado()
    assert 'PHATI_BANCO_SUPER_SENHA' not in _bloco('migracao')
    assert 'PHATI_BANCO_SUPER_SENHA' not in _bloco('app_azul')
    assert 'PHATI_BANCO_SUPER_SENHA' not in _bloco('app_verde')
