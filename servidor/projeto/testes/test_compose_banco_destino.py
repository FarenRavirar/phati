"""Compose: os serviços que falam direto com o banco seguem o banco ativo (spec 009, R15, T5.4c).

Migração, estáticos e os one-shots de banco recebem o host por `${PHATI_BANCO_DESTINO:-banco}`: depois da troca, `banco_novo`;
sem a variável, `banco`. O app continua atrás do PgBouncer (`pgb_ns`), que já segue o mesmo destino.

Não sobe contêiner: `docker compose config` só lê os arquivos. Os valores são sintéticos e vêm do ambiente deste processo.
"""

import functools
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

RAIZ = Path(settings.DIRETORIO_BASE)
IMPLANTACAO = ('-f', 'compose.yaml', '-f', 'compose.implantacao.yaml')
# Mesmos valores sintéticos de test_compose_bluegreen.py (cada teste de compose precisa de todos os `:?`).
VALORES_SINTETICOS = {
    'PHATI_CHAVE_SECRETA': 'sintetica-chave-secreta',
    'PHATI_CHAVE_CPF': 'sintetica-chave-cpf',
    'PHATI_SEGREDO_RLS': 'sintetica-segredo-rls',
    'PHATI_BANCO_SUPER_SENHA': 'sintetica-super',
    'PHATI_BANCO_DONO_USUARIO': 'dono',
    'PHATI_BANCO_DONO_SENHA': 'sintetica-dono',
    'PHATI_BANCO_APP_USUARIO': 'app',
    'PHATI_BANCO_APP_SENHA': 'sintetica-app',
    'PHATI_BANCO_REPLICADOR_SENHA': 'sintetica-replicador',
    'PHATI_TUNEL_TOKEN': 'sintetico-tunel',
    'PHATI_ALVO_DIR': './nginx/alvo',
}
# Serviço -> chave de ambiente que leva o host do banco (todas com `${PHATI_BANCO_DESTINO:-banco}` no compose).
QUEM_FALA_COM_O_BANCO = {
    'migracao': 'PHATI_BANCO_HOST',
    'estaticos_azul': 'PHATI_BANCO_HOST',
    'estaticos_verde': 'PHATI_BANCO_HOST',
    'banco_extensoes': 'PGHOST',
    'pgb_auth': 'PGHOST',
}


def _config(ambiente=None):
    if shutil.which('docker') is None:
        raise AssertionError('docker ausente no PATH: o teste de compose precisa do binário (sem ele não há config)')
    # Valor None tira a variável do ambiente (ausente, não só vazia).
    env = {k: v for k, v in {**os.environ, **VALORES_SINTETICOS, **(ambiente or {})}.items() if v is not None}
    # `--env-file` vazio antes de `-f`: a interpolação não lê o `servidor/.env` local.
    with tempfile.TemporaryDirectory() as temporario:
        vazio = Path(temporario) / 'vazio.env'
        vazio.write_text('', encoding='utf-8')
        rodado = subprocess.run(
            ['docker', 'compose', '--env-file', str(vazio), *IMPLANTACAO, 'config', '--format', 'json'],
            cwd=RAIZ, env=env, capture_output=True, text=True, encoding='utf-8', check=False,
        )
    return rodado.returncode, rodado.stdout, rodado.stderr


def _servicos(ambiente=None):
    rc, saida, erro = _config(ambiente)
    assert rc == 0, f'config de implantação falhou (rc={rc}): {erro}'
    return json.loads(saida)['services']


@functools.cache
def _padrao():
    return _servicos({'PHATI_BANCO_DESTINO': None})


def _host(servicos, nome):
    return servicos[nome]['environment'][QUEM_FALA_COM_O_BANCO[nome]]


# Caminho feliz.

def test_sem_a_variavel_os_consumidores_do_banco_apontam_para_banco():
    servicos = _padrao()
    for nome in QUEM_FALA_COM_O_BANCO:
        assert _host(servicos, nome) == 'banco', nome


def test_com_destino_banco_novo_os_consumidores_do_banco_apontam_para_banco_novo():
    servicos = _servicos({'PHATI_BANCO_DESTINO': 'banco_novo'})
    for nome in QUEM_FALA_COM_O_BANCO:
        assert _host(servicos, nome) == 'banco_novo', nome


def test_destino_vazio_cai_no_padrao_banco():
    servicos = _servicos({'PHATI_BANCO_DESTINO': ''})
    for nome in QUEM_FALA_COM_O_BANCO:
        assert _host(servicos, nome) == 'banco', nome


# Caso negativo: o que não pode mudar com o destino.

def test_com_destino_banco_novo_o_app_segue_atras_do_pgbouncer_e_o_servico_banco_fica():
    servicos = _servicos({'PHATI_BANCO_DESTINO': 'banco_novo'})
    assert servicos['app_azul']['environment']['PHATI_BANCO_HOST'] == 'pgb_ns'
    assert servicos['app_azul']['environment']['PHATI_BANCO_PORTA'] == '6432'
    assert 'banco' in servicos
