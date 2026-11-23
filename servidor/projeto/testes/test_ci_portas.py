"""Passo de portas do CI (spec 009 T4.2, spec 006 A1): a implantação não publica porta em nenhum serviço.

O passo "Implantação não publica porta em nenhum serviço" do `.github/workflows/ci.yml` roda `docker compose config`
com os dois arquivos da implantação e falha se achar porta publicada. Os testes executam o trecho `run` desse passo
num shell, com um `docker` de mentira no PATH, e conferem o rc; o passo não sobe contêiner.
"""

import json
import os
import re
import shlex
import subprocess
import textwrap
from pathlib import Path

import pytest
from django.conf import settings

from projeto.testes.test_compose_bluegreen import IMPLANTACAO, _config

RAIZ = Path(settings.DIRETORIO_BASE)
CI = (RAIZ.parent / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')

# O padrão do runner do GitHub é `bash -eo pipefail`; `-e` sozinho cobre o caso em que o passo não depende desse padrão.
OPCOES_DE_SHELL = {'padrao_do_runner': ['--noprofile', '--norc', '-eo', 'pipefail'], 'so_errexit': ['-e']}
pytest_param_shells = pytest.mark.parametrize('shell', list(OPCOES_DE_SHELL))


def _passo_de_portas(ci):
    """Bloco do passo de portas dentro do ci.yml, ou None se o passo não existe."""
    bloco = re.search(r'^      - name: Implantação não publica porta.*?(?=^      - |\Z)', ci, re.M | re.S)
    return bloco.group(0) if bloco else None


def _script_do_passo(ci):
    """Corpo do `run: |` do passo de portas, sem a indentação do YAML."""
    passo = _passo_de_portas(ci)
    assert passo is not None, 'passo de portas ausente no ci.yml'
    linhas = passo.split('\n')
    assert '        run: |' in linhas, 'passo de portas sem `run: |`'
    corpo = []
    for linha in linhas[linhas.index('        run: |') + 1 :]:
        if linha.strip() and not linha.startswith('          '):
            break
        corpo.append(linha)
    return textwrap.dedent('\n'.join(corpo))


def _roda_passo(tmp_path, saida, rc=0, shell='padrao_do_runner'):
    """Roda o `run` do passo com um `docker` de mentira que imprime `saida` e sai com `rc`."""
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    (tmp_path / 'saida.json').write_text(saida, encoding='utf-8')
    docker = bin_dir / 'docker'
    docker.write_text(
        '#!/bin/sh\n'
        f'printf "%s\\n" "$@" > {shlex.quote(str(tmp_path / "args"))}\n'
        f'cat {shlex.quote(str(tmp_path / "saida.json"))}\n'
        f'exit {rc}\n',
        encoding='utf-8',
    )
    docker.chmod(0o755)
    ambiente = {
        **os.environ,
        'PATH': f'{bin_dir}{os.pathsep}{os.environ["PATH"]}',
        'PHATI_TUNEL_TOKEN': 'token-de-teste',
        'PHATI_ALVO_DIR': './nginx/alvo',
    }
    return subprocess.run(
        ['bash', *OPCOES_DE_SHELL[shell], '-c', _script_do_passo(CI)],
        cwd=tmp_path,
        env=ambiente,
        capture_output=True,
        text=True,
        check=False,
    )


def _publicados(servicos):
    """Nomes dos serviços com `ports` não vazio no config expandido (mesma regra do passo do ci.yml)."""
    return [nome for nome, servico in servicos.items() if servico.get('ports')]


def test_ci_tem_o_passo_de_portas():
    # Existência estática mínima; o comportamento do passo é conferido executando o `run` nos testes abaixo.
    assert _passo_de_portas(CI) is not None, 'passo de portas ausente no ci.yml'


@pytest_param_shells
def test_passo_roda_config_com_os_dois_arquivos(tmp_path, shell):
    proc = _roda_passo(tmp_path, json.dumps({'services': {}}), shell=shell)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    args = (tmp_path / 'args').read_text(encoding='utf-8').splitlines()
    assert 'compose.yaml' in args and 'compose.implantacao.yaml' in args, args
    assert 'config' in args, args


@pytest_param_shells
def test_sem_porta_publicada_passa(tmp_path, shell):
    servicos = {'app_azul': {'image': 'phati'}, 'banco': {'ports': None}}
    proc = _roda_passo(tmp_path, json.dumps({'services': servicos}), shell=shell)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest_param_shells
def test_ports_vazio_nao_conta_como_porta_publicada(tmp_path, shell):
    # Borda: `ports: []` não publica nada; o passo não pode falhar por isso.
    servicos = {'app_azul': {'ports': []}}
    proc = _roda_passo(tmp_path, json.dumps({'services': servicos}), shell=shell)
    assert proc.returncode == 0, proc.stdout + proc.stderr


@pytest_param_shells
def test_porta_publicada_falha_e_nomeia_o_servico(tmp_path, shell):
    servicos = {'app_azul': {'ports': [{'published': '8000', 'target': 8000}]}, 'banco': {'image': 'pg'}}
    proc = _roda_passo(tmp_path, json.dumps({'services': servicos}), shell=shell)
    assert proc.returncode != 0
    assert 'publicam porta: app_azul' in proc.stdout, proc.stdout


@pytest_param_shells
@pytest.mark.parametrize(
    ('saida', 'rc'),
    [('', 1), ('', 0), ('nao-e-json', 0)],
    ids=['compose_falha', 'saida_vazia', 'saida_nao_json'],
)
def test_compose_sem_config_falha(tmp_path, shell, saida, rc):
    # Caso negativo: sem o JSON do `config` o passo não pode passar com a lista de portas vazia.
    proc = _roda_passo(tmp_path, saida, rc=rc, shell=shell)
    assert proc.returncode != 0, f'rc={proc.returncode} stdout={proc.stdout!r} stderr={proc.stderr!r}'


def test_detector_acha_servico_com_porta_publicada():
    # Caso negativo do detector: um serviço com `ports` tem que aparecer na lista.
    servicos = {'app_azul': {'ports': [{'published': '8000', 'target': 8000}]}, 'banco': {}}
    assert _publicados(servicos) == ['app_azul']


def test_detector_ignora_ports_vazio_e_nulo():
    assert _publicados({'app_azul': {'ports': []}, 'banco': {'ports': None}}) == []


def test_config_da_implantacao_nao_publica_porta_em_nenhum_servico():
    rc, saida, erro = _config(IMPLANTACAO)
    assert rc == 0, erro
    assert _publicados(json.loads(saida)['services']) == []
    assert '"published"' not in saida
