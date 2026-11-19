import re
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


VOLUME_CAMADAS = 'camadas:${PHATI_CAMADAS_DIR:-/camadas}'


def _linhas_do_servico(nome):
    # Sem PyYAML no venv: recorta o bloco do serviço em `services:` (chave de 2 espaços) até a próxima chave do mesmo nível.
    linhas = COMPOSE.splitlines()
    inicio = linhas.index(f'  {nome}:')
    fim = next((i for i in range(inicio + 1, len(linhas)) if re.match(r'  [a-z_]+:\s*$|\S', linhas[i])), len(linhas))
    return linhas[inicio + 1:fim]


def _volumes_do_servico(nome):
    return [m.group(1) for m in (re.match(r'      - (\S+)', linha) for linha in _linhas_do_servico(nome)) if m]


def test_compose_define_a_variavel_de_camadas_no_ambiente_do_app():
    assert 'PHATI_CAMADAS_DIR: ${PHATI_CAMADAS_DIR:-/camadas}' in COMPOSE


def test_app_monta_o_volume_das_camadas():
    # Mutação: tirar só a montagem do `app` falha aqui, mesmo com `camadas_dono` ainda montando o volume.
    assert VOLUME_CAMADAS in _volumes_do_servico('app')


def test_app_espera_o_dono_do_volume_das_camadas():
    assert '      camadas_dono: {condition: service_completed_successfully}' in _linhas_do_servico('app')


def test_camadas_dono_monta_o_volume_e_acerta_o_dono_como_pacotes():
    assert VOLUME_CAMADAS in _volumes_do_servico('camadas_dono')
    assert '    command: chown 10001 ${PHATI_CAMADAS_DIR:-/camadas}' in _linhas_do_servico('camadas_dono')


def test_nginx_nao_monta_o_volume_das_camadas():
    # Caso negativo: disco privado, sem rota pública; o proxy não enxerga os originais.
    assert not any(volume.startswith('camadas:') for volume in _volumes_do_servico('nginx'))


def test_dockerfile_prepara_camadas_com_dono_aplicacao():
    assert 'mkdir /pacotes /camadas && chown aplicacao /pacotes /camadas' in DOCKERFILE
