"""Compose da troca de banco (spec 009, R15, T5.2, S2a): a implantação não declara `wal_level`; o override lógico o declara,
e o serviço `banco_novo` fica sob profile.

Não sobe contêiner: `docker compose config` só lê os arquivos. Os valores são sintéticos e vêm do ambiente deste processo.
"""

import functools
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest import mock

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
    # COMPOSE_PROFILES do ambiente do processo sairia: só `COM_PROFILE` liga o banco_novo nestes testes.
    base = {k: v for k, v in os.environ.items() if k != 'COMPOSE_PROFILES'}
    env = {k: v for k, v in {**base, **VALORES_SINTETICOS, **(ambiente or {})}.items() if v is not None}
    # `--env-file` vazio antes de `-f`: a interpolação não lê o `servidor/.env` local.
    with tempfile.TemporaryDirectory() as temporario:
        vazio = Path(temporario) / 'vazio.env'
        vazio.write_text('', encoding='utf-8')
        rodado = subprocess.run(
            ['docker', 'compose', '--env-file', str(vazio), *flags, 'config', '--format', 'json'],
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

def test_banco_da_implantacao_usa_o_wal_padrao_sem_command():
    # S2a: sem `command`, o banco não é recriado por wal_level no deploy e o standby físico nasce com a origem.
    # `compose config` emite `command: null` quando a implantação não define o comando: conta como ausente.
    assert _sem_profile()['services']['banco'].get('command') is None


def test_banco_novo_nao_aparece_sem_o_profile():
    assert 'banco_novo' not in _sem_profile()['services']


def test_compose_profiles_do_ambiente_nao_liga_o_banco_novo():
    # Mutação "não tirar COMPOSE_PROFILES do ambiente-base": o compose lê a variável e o banco_novo aparece sem COM_PROFILE.
    with mock.patch.dict(os.environ, {'COMPOSE_PROFILES': 'troca-banco'}):
        rc, saida, erro = _config(BASE)
    assert rc == 0, erro
    assert 'banco_novo' not in json.loads(saida)['services']


def test_banco_novo_aparece_com_o_profile_troca_banco():
    servico = _com_profile()['services']['banco_novo']
    assert servico['profiles'] == ['troca-banco']


def test_banco_novo_tem_restart_e_healthcheck_do_banco():
    servicos = _com_profile()['services']
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


# Override da troca lógica (S2a): `compose.troca-logica.yaml` é somado só pelo trocar-banco.sh no modo lógico.

def _com_override(profile=True, ambiente=None):
    flags = (*(COM_PROFILE if profile else BASE), '-f', 'compose.troca-logica.yaml')
    rc, saida, erro = _config(flags, ambiente)
    assert rc == 0, f'config com override falhou (rc={rc}): {erro}'
    return json.loads(saida)


def test_override_da_wal_logical_ao_banco_e_ao_banco_novo():
    servicos = _com_override()['services']
    assert servicos['banco']['command'] == COMANDO_WAL
    assert servicos['banco_novo']['command'] == COMANDO_WAL


def test_override_nao_tira_healthcheck_nem_restart_do_banco():
    servicos = _com_override()['services']
    base = _sem_profile()['services']['banco']
    assert servicos['banco']['healthcheck'] == base['healthcheck']
    assert servicos['banco']['restart'] == base['restart']


def test_override_sem_profile_nao_faz_aparecer_o_banco_novo():
    # O profile vem do compose.implantacao.yaml; o override não pode tirá-lo.
    servicos = _com_override(profile=False)['services']
    assert 'banco_novo' not in servicos
    assert servicos['banco']['command'] == COMANDO_WAL


# Caso infeliz: a implantação física não pode voltar a ter wal_level (mutação: pôr `command` de volta no compose).

def test_implantacao_nao_declara_wal_level_no_banco_nem_no_banco_novo():
    assert 'wal_level' not in json.dumps(_sem_profile()['services']['banco'])
    assert 'wal_level' not in json.dumps(_com_profile()['services']['banco_novo'])
