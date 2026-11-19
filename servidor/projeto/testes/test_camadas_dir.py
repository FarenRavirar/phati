import runpy
from pathlib import Path

from django.conf import settings

CAMINHO = Path(settings.DIRETORIO_BASE) / 'projeto' / 'settings.py'
RAIZ = Path(settings.DIRETORIO_BASE)
COMPOSE = (RAIZ / 'compose.yaml').read_text(encoding='utf-8')
DOCKERFILE = (RAIZ / 'Dockerfile').read_text(encoding='utf-8')


def test_camadas_dir_padrao_e_caminho_privado_no_molde_de_pacotes(monkeypatch):
    # D114 (c): disco privado no molde de PACOTES_DIR (variável, padrão em /camadas).
    monkeypatch.delenv('PHATI_CAMADAS_DIR', raising=False)
    assert runpy.run_path(str(CAMINHO))['CAMADAS_DIR'] == Path('/camadas')


def test_camadas_dir_lido_da_variavel_de_ambiente(monkeypatch):
    monkeypatch.setenv('PHATI_CAMADAS_DIR', '/dados/camadas')
    assert runpy.run_path(str(CAMINHO))['CAMADAS_DIR'] == Path('/dados/camadas')


def test_camadas_dir_variavel_vazia_cai_no_padrao(monkeypatch):
    # Caminho infeliz: variável presente mas vazia não pode virar caminho vazio (o disco ficaria na raiz relativa).
    monkeypatch.setenv('PHATI_CAMADAS_DIR', '')
    assert runpy.run_path(str(CAMINHO))['CAMADAS_DIR'] == Path('/camadas')


def test_compose_monta_volume_privado_e_acerta_dono_como_pacotes():
    assert 'PHATI_CAMADAS_DIR: ${PHATI_CAMADAS_DIR:-/camadas}' in COMPOSE
    assert 'camadas:${PHATI_CAMADAS_DIR:-/camadas}' in COMPOSE
    assert 'camadas_dono:' in COMPOSE
    assert 'command: chown 10001 ${PHATI_CAMADAS_DIR:-/camadas}' in COMPOSE
    assert 'camadas_dono: {condition: service_completed_successfully}' in COMPOSE


def test_dockerfile_prepara_camadas_com_dono_aplicacao():
    assert 'mkdir /pacotes /camadas && chown aplicacao /pacotes /camadas' in DOCKERFILE
