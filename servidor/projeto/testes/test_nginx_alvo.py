"""Troca de pilha no nginx (spec 009, R2, A1): destino em `alvo.conf`, resolvido em tempo de requisição.

Os testes de texto não sobem nada. `test_nginx_t_*` roda `nginx -t` num contêiner descartável (`--rm`, nome com prefixo
`phati009h-`) e precisa do daemon Docker e da imagem local: marcador `docker`, deselecionável com `-m "not docker"`.
"""

import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
from django.conf import settings

RAIZ = Path(settings.DIRETORIO_BASE)
NGINX = RAIZ / 'nginx'
IMAGEM_NGINX = 'nginx:1.31-alpine@sha256:785835ea65db4bba6f021acc0f3be91b0fef76a53fe41f8588c6698d2aed0606'


def _ativas(caminho):
    return [linha.strip() for linha in caminho.read_text(encoding='utf-8').splitlines() if not linha.strip().startswith('#')]


def _sets(caminho):
    return {m.group(1): m.group(2) for m in (re.match(r'set \$(\w+) (\S+);', linha) for linha in _ativas(caminho)) if m}


def test_default_conf_resolve_o_destino_pelo_docker_com_ttl_curto():
    ativas = _ativas(NGINX / 'default.conf')
    assert 'resolver 127.0.0.11 valid=1s;' in ativas


def test_default_conf_inclui_o_alvo_no_server_e_nao_tem_app_fixo():
    ativas = _ativas(NGINX / 'default.conf')
    assert 'include /etc/nginx/alvo/alvo.conf;' in ativas
    assert ativas.count('proxy_pass http://$alvo:8000;') == 2
    assert not any('proxy_pass http://app:' in linha for linha in ativas)


def test_static_le_a_pilha_do_alvo_e_nao_o_volume_unico():
    ativas = _ativas(NGINX / 'default.conf')
    assert 'alias /estaticos_$pilha/;' in ativas
    assert not any(linha == 'alias /estaticos/;' for linha in ativas)


def test_mime_mjs_continua_no_location_de_estaticos():
    # O comentário original sobre `.mjs` (PR #35) segue: o `types` acrescenta `mjs` à tabela do `mime.types`.
    ativas = _ativas(NGINX / 'default.conf')
    assert 'include mime.types;' in ativas
    assert 'types { text/javascript mjs; }' in ativas


def test_alvo_conf_define_o_serviço_e_a_pilha_coerentes():
    sets = _sets(NGINX / 'alvo' / 'alvo.conf')
    assert set(sets) == {'alvo', 'pilha'}
    assert sets['alvo'] == f"app_{sets['pilha']}"  # caso negativo: `app_verde` com `pilha azul` trocaria app e estáticos separados
    assert sets == {'alvo': 'app_azul', 'pilha': 'azul'}


def _nginx_t(conf_d, alvo):
    if shutil.which('docker') is None:
        raise AssertionError('docker ausente no PATH: rode com -m "not docker" se não houver daemon')
    nome = f'phati009h-nginx-{uuid.uuid4().hex[:8]}'
    comando = [
        'docker', 'run', '--rm', '--pull', 'never', '--name', nome,
        '--mount', f'type=bind,source={conf_d.as_posix()},target=/etc/nginx/conf.d,readonly',
        '--mount', f'type=bind,source={alvo.as_posix()},target=/etc/nginx/alvo,readonly',
        IMAGEM_NGINX, 'nginx', '-t',
    ]
    rodado = subprocess.run(comando, capture_output=True, text=True, encoding='utf-8', check=False, timeout=120)
    return rodado.returncode, rodado.stderr


@pytest.mark.docker
def test_nginx_t_aceita_a_config_com_o_alvo_montado_como_diretorio():
    # Monta o diretório `nginx/` como `conf.d` (igual ao compose): o `alvo/` aninhado não entra no `*.conf` do topo.
    rc, erro = _nginx_t(NGINX, NGINX / 'alvo')
    assert rc == 0, erro
    assert 'syntax is ok' in erro
    assert 'test is successful' in erro


@pytest.mark.docker
def test_nginx_t_recusa_a_config_quando_o_alvo_nao_existe(tmp_path):
    # Caso negativo: sem `alvo.conf` o `include` falha, e o reload não aceitaria o destino quebrado.
    rc, erro = _nginx_t(NGINX, tmp_path)
    assert rc != 0
    assert 'alvo.conf' in erro
