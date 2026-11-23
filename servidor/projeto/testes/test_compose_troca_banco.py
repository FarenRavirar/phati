"""Compose da troca de banco (spec 009, R15, T5.2): `wal_level` no `banco` e o serviço `banco_novo` sob profile.

Não sobe contêiner: `docker compose config` só lê os arquivos. Os valores são sintéticos e vêm do ambiente deste processo.
"""

import functools
import json
import os
import shutil
import subprocess
from pathlib import Path

from django.conf import settings

RAIZ = Path(settings.DIRETORIO_BASE)
BASE = ('-f', 'compose.yaml', '-f', 'compose.implantacao.yaml')
COM_PROFILE = ('--profile', 'troca-banco', *BASE)
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
COMANDO_WAL = ['postgres', '-c', 'wal_level=logical', '-c', 'max_replication_slots=10', '-c', 'max_wal_senders=10']


def _config(flags, ambiente=None):
    if shutil.which('docker') is None:
        raise AssertionError('docker ausente no PATH: o teste de compose precisa do binário (sem ele não há config)')
    # Valor None tira a variável do ambiente (ausente, não só vazia).
    env = {k: v for k, v in {**os.environ, **VALORES_SINTETICOS, **(ambiente or {})}.items() if v is not None}
    rodado = subprocess.run(
        ['docker', 'compose', *flags, 'config', '--format', 'json'],
        cwd=RAIZ, env=env, capture_output=True, text=True, encoding='utf-8', check=False,
    )
    return rodado.returncode, rodado.stdout, rodado.stderr


@functools.cache
def _sem_profile():
    rc, saida, erro = _config(BASE)
    assert rc == 0, f'config sem profile falhou (rc={rc}): {erro}'
    return json.loads(saida)


@functools.cache
def _com_profile():
    rc, saida, erro = _config(COM_PROFILE)
    assert rc == 0, f'config com profile falhou (rc={rc}): {erro}'
    return json.loads(saida)


# Caminho feliz.

def test_banco_sobe_com_wal_level_logical_e_limites_de_replicacao():
    assert _sem_profile()['services']['banco']['command'] == COMANDO_WAL


def test_banco_novo_nao_aparece_sem_o_profile():
    assert 'banco_novo' not in _sem_profile()['services']


def test_banco_novo_aparece_com_o_profile_troca_banco():
    servico = _com_profile()['services']['banco_novo']
    assert servico['profiles'] == ['troca-banco']


def test_banco_novo_tem_comando_wal_restart_e_healthcheck_do_banco():
    servicos = _com_profile()['services']
    assert servicos['banco_novo']['command'] == COMANDO_WAL
    assert servicos['banco_novo']['restart'] == 'unless-stopped'
    assert servicos['banco_novo']['healthcheck'] == servicos['banco']['healthcheck']


def test_banco_novo_usa_a_mesma_rede_do_banco():
    servicos = _com_profile()['services']
    assert servicos['banco_novo']['networks'] == servicos['banco']['networks']


def test_banco_novo_tem_volume_proprio_declarado_no_topo():
    dados = _com_profile()
    volume = {v['target']: v['source'] for v in dados['services']['banco_novo']['volumes'] if v['type'] == 'volume'}
    assert volume['/var/lib/postgresql'] == 'dados_banco_novo'
    assert 'dados_banco_novo' in dados['volumes']


def test_banco_novo_nao_publica_porta():
    assert not _com_profile()['services']['banco_novo'].get('ports')


def test_banco_novo_recebe_as_mesmas_variaveis_do_banco_por_referencia():
    # Com outro valor no ambiente, os dois mudam juntos: prova que é referência, não literal copiado.
    rc, saida, erro = _config(COM_PROFILE, {'PHATI_BANCO_SUPER_SENHA': 'outro-super'})
    assert rc == 0, erro
    servicos = json.loads(saida)['services']
    assert servicos['banco_novo']['environment'] == servicos['banco']['environment']
    assert servicos['banco_novo']['environment']['POSTGRES_PASSWORD'] == 'outro-super'


# Caso infeliz: o que não pode acontecer.

def test_banco_novo_sem_senha_de_super_recusa_subir():
    rc, _, erro = _config(COM_PROFILE, {'PHATI_BANCO_SUPER_SENHA': ''})
    assert rc != 0
    assert 'PHATI_BANCO_SUPER_SENHA' in erro


def test_banco_sobe_sem_senha_do_replicador_e_a_variavel_vai_vazia():
    # Com `:?` no `banco`, o compose recusaria subir QUALQUER serviço na VM sem a variável (quebra o implantar.sh).
    # Vazia, o papeis.sql só pula o papel `replicador`; quem exige a senha é o `preparar` da troca.
    rc, saida, erro = _config(BASE, {'PHATI_BANCO_REPLICADOR_SENHA': ''})
    assert rc == 0, erro
    assert json.loads(saida)['services']['banco']['environment']['PHATI_BANCO_REPLICADOR_SENHA'] == ''


def test_banco_sobe_sem_a_variavel_do_replicador_no_ambiente():
    # Variável ausente (não só vazia) também não derruba o `config`: o `:-` cobre os dois casos.
    rc, _, erro = _config(BASE, {'PHATI_BANCO_REPLICADOR_SENHA': None})
    assert rc == 0, erro


def test_banco_declara_a_senha_do_replicador_do_ambiente():
    # Mutação "tirar do banco": o banco_novo ainda recusa, então só esta checagem pega a falta no `banco`.
    assert 'PHATI_BANCO_REPLICADOR_SENHA' in _sem_profile()['services']['banco']['environment']


def test_banco_novo_nao_compartilha_volume_com_o_banco_atual():
    dados = _com_profile()
    origens_banco = {v['source'] for v in dados['services']['banco']['volumes'] if v['type'] == 'volume'}
    origens_novo = {v['source'] for v in dados['services']['banco_novo']['volumes'] if v['type'] == 'volume'}
    assert origens_banco.isdisjoint(origens_novo)
