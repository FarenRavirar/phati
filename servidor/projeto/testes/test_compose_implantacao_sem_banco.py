"""Implantação sem `banco` em `depends_on` (spec 009, R15, T5.4d).

Em `compose.yaml`, migracao, banco_extensoes e pgb_auth dependem de `banco`, e o compose sobe o `banco` mesmo com
`PHATI_BANCO_DESTINO=banco_novo`. O `compose.implantacao.yaml` tira essa dependência, porque o `implantar.sh` sobe o banco
ativo antes de qualquer `run`; o dev segue com ela.

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
DEV = ('-f', 'compose.yaml')
BANCOS = {'banco', 'banco_novo'}
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


def _config(flags, ambiente=None):
    if shutil.which('docker') is None:
        raise AssertionError('docker ausente no PATH: o teste de compose precisa do binário (sem ele não há config)')
    # Valor None tira a variável do ambiente (ausente, não só vazia).
    env = {k: v for k, v in {**os.environ, **VALORES_SINTETICOS, **(ambiente or {})}.items() if v is not None}
    # `--env-file` vazio antes de `-f`: a interpolação não lê o `servidor/.env` local.
    with tempfile.TemporaryDirectory() as temporario:
        vazio = Path(temporario) / 'vazio.env'
        vazio.write_text('', encoding='utf-8')
        rodado = subprocess.run(
            ['docker', 'compose', '--env-file', str(vazio), *flags, 'config', '--format', 'json'],
            cwd=RAIZ, env=env, capture_output=True, text=True, encoding='utf-8', check=False,
        )
    return rodado.returncode, rodado.stdout, rodado.stderr


def _servicos(flags, ambiente=None):
    rc, saida, erro = _config(flags, ambiente)
    assert rc == 0, f'config falhou (rc={rc}): {erro}'
    return json.loads(saida)['services']


def _dependem_de_banco(servicos):
    """Serviços que listam `banco` ou `banco_novo` em `depends_on`."""
    return sorted(nome for nome, servico in servicos.items() if BANCOS & set(servico.get('depends_on', {})))


@functools.cache
def _implantacao():
    return _servicos(IMPLANTACAO)


# Caminho feliz.

def test_nenhum_servico_de_implantacao_depende_do_banco():
    assert _dependem_de_banco(_implantacao()) == []


def test_com_destino_banco_novo_nenhum_servico_de_implantacao_depende_de_banco():
    assert _dependem_de_banco(_servicos(IMPLANTACAO, {'PHATI_BANCO_DESTINO': 'banco_novo'})) == []


def test_migracao_mantem_so_a_dependencia_do_postgis():
    depends = _implantacao()['migracao']['depends_on']
    assert set(depends) == {'banco_extensoes'}
    assert depends['banco_extensoes']['condition'] == 'service_completed_successfully'


def test_dev_sozinho_mantem_o_depends_on_do_banco():
    # Caso negativo da remoção: o compose.yaml de dev segue com a dependência (CI e `run --no-deps` dependem dela).
    assert set(_dependem_de_banco(_servicos(DEV))) == {'banco_extensoes', 'migracao', 'pgb_auth'}


# Caso infeliz: a dependência de volta reprova a checagem.

def test_override_que_volta_o_banco_e_detectado(tmp_path):
    # Mutação: a dependência de `banco` volta em `migracao` por um terceiro arquivo; a checagem tem que apontá-la.
    volta = tmp_path / 'volta.yaml'
    volta.write_text(
        'services:\n  migracao:\n    depends_on:\n      banco: {condition: service_healthy}\n',
        encoding='utf-8',
    )
    servicos = _servicos((*IMPLANTACAO, '-f', str(volta)))
    assert 'migracao' in _dependem_de_banco(servicos)
