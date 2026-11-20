"""Compose azul-verde e PgBouncer (spec 009, R1, R6, R18, A9): o config expandido pelo próprio `docker compose`.

Não sobe contêiner: `docker compose config` só lê os arquivos (expande âncora, `!reset`, merge e profile). Os valores são
sintéticos e vêm do ambiente deste processo, nunca de `.env`.
"""

import functools
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from django.conf import settings

RAIZ = Path(settings.DIRETORIO_BASE)
PGBOUNCER = RAIZ / 'pgbouncer'
ALVO_DE_DEV = './nginx/alvo'
VALORES_SINTETICOS = {
    'PHATI_CHAVE_SECRETA': 'sintetica-chave-secreta',
    'PHATI_CHAVE_CPF': 'sintetica-chave-cpf',
    'PHATI_SEGREDO_RLS': 'sintetica-segredo-rls',
    'PHATI_BANCO_SUPER_SENHA': 'sintetica-super',
    'PHATI_BANCO_DONO_USUARIO': 'dono',
    'PHATI_BANCO_DONO_SENHA': 'sintetica-dono',
    'PHATI_BANCO_APP_USUARIO': 'app',
    'PHATI_BANCO_APP_SENHA': 'sintetica-app',
    'PHATI_TUNEL_TOKEN': 'sintetico-tunel',
    'PHATI_ALVO_DIR': ALVO_DE_DEV,
}
IMPLANTACAO = ('-f', 'compose.yaml', '-f', 'compose.implantacao.yaml')
DEV = ('-f', 'compose.yaml')


def _config(flags, ambiente=None):
    """Roda `docker compose <flags> config --format json` e devolve (rc, saída JSON ou stderr)."""
    if shutil.which('docker') is None:
        raise AssertionError('docker ausente no PATH: o teste de compose precisa do binário (sem ele não há config)')
    env = {**os.environ, **VALORES_SINTETICOS, **(ambiente or {})}
    rodado = subprocess.run(
        ['docker', 'compose', *flags, 'config', '--format', 'json'],
        cwd=RAIZ, env=env, capture_output=True, text=True, encoding='utf-8', check=False,
    )
    return rodado.returncode, rodado.stdout, rodado.stderr


@functools.cache
def _implantacao():
    rc, saida, erro = _config(IMPLANTACAO)
    assert rc == 0, f'config de implantação falhou (rc={rc}): {erro}'
    return json.loads(saida)['services']


@functools.cache
def _dev():
    rc, saida, erro = _config(DEV)
    assert rc == 0, f'config de dev falhou (rc={rc}): {erro}'
    return json.loads(saida)['services']


def _volumes(servico):
    return {volume['target']: volume for volume in servico.get('volumes', [])}


def _ambiente(servico):
    return servico.get('environment', {})


# Caminho feliz da implantação.

def test_implantacao_sobe_as_duas_pilhas_o_pgbouncer_e_o_nginx():
    servicos = _implantacao()
    for nome in ('app_azul', 'app_verde', 'pgb_ns', 'pgb1', 'pgb2', 'pgb_auth', 'nginx', 'banco', 'migracao'):
        assert nome in servicos, nome


def test_as_duas_pilhas_do_app_tem_a_mesma_imagem_e_o_mesmo_ambiente():
    azul, verde = _implantacao()['app_azul'], _implantacao()['app_verde']
    assert azul['build'] == verde['build']
    assert _ambiente(azul) == _ambiente(verde)
    assert _ambiente(azul)['PHATI_BANCO_HOST'] == 'pgb_ns'
    assert _ambiente(azul)['PHATI_BANCO_PORTA'] == '6432'
    assert _ambiente(verde)['PHATI_BANCO_HOST'] == 'pgb_ns'


def test_migracao_e_estaticos_vao_direto_ao_banco_e_o_app_nao():
    servicos = _implantacao()
    for nome in ('migracao', 'estaticos_azul', 'estaticos_verde'):
        assert _ambiente(servicos[nome])['PHATI_BANCO_HOST'] == 'banco', nome
        assert _ambiente(servicos[nome])['PHATI_BANCO_PORTA'] == '5432', nome


def test_pgbouncers_dividem_a_rede_do_dono_pgb_ns():
    servicos = _implantacao()
    assert servicos['pgb1']['network_mode'] == 'service:pgb_ns'
    assert servicos['pgb2']['network_mode'] == 'service:pgb_ns'


def test_estaticos_de_cada_pilha_tem_volume_proprio_e_pacotes_camadas_sao_compartilhados():
    servicos = _implantacao()
    assert _volumes(servicos['estaticos_azul'])['/estaticos']['source'] == 'estaticos_azul'
    assert _volumes(servicos['estaticos_verde'])['/estaticos']['source'] == 'estaticos_verde'
    for pilha in ('app_azul', 'app_verde'):
        assert _volumes(servicos[pilha])['/pacotes']['source'] == 'pacotes', pilha
        assert _volumes(servicos[pilha])['/camadas']['source'] == 'camadas', pilha
    assert 'estaticos_verde' not in [v['source'] for v in _volumes(servicos['app_azul']).values()]


def test_nginx_monta_os_dois_estaticos_e_o_alvo_somente_leitura():
    nginx = _implantacao()['nginx']
    volumes = _volumes(nginx)
    for destino, origem in (('/estaticos_azul', 'estaticos_azul'), ('/estaticos_verde', 'estaticos_verde')):
        assert volumes[destino]['source'] == origem
        assert volumes[destino].get('read_only') is True, destino
    assert volumes['/etc/nginx/alvo'].get('read_only') is True


def test_nginx_monta_o_diretorio_nginx_como_conf_d_e_nao_o_arquivo_unico():
    # Bind de arquivo prende o inode: o `git checkout` troca o arquivo e o nginx segue com o antigo (spec 009, Arquitetura).
    for nome in ('nginx', 'nginx_dev'):
        servico = _implantacao()['nginx'] if nome == 'nginx' else _dev()['nginx']
        volumes = _volumes(servico)
        assert '/etc/nginx/conf.d/default.conf' not in volumes, nome
        assert volumes['/etc/nginx/conf.d']['source'].replace('\\', '/').endswith('/nginx'), nome
        assert volumes['/etc/nginx/conf.d'].get('read_only') is True, nome


def test_nginx_le_o_alvo_do_ambiente_da_vm_e_nao_o_do_repositorio():
    rc, saida, erro = _config(IMPLANTACAO, {'PHATI_ALVO_DIR': '/opt/phati/alvo'})
    assert rc == 0, erro
    volumes = _volumes(json.loads(saida)['services']['nginx'])
    assert volumes['/etc/nginx/alvo']['source'] == '/opt/phati/alvo'


def test_implantacao_nao_publica_porta_em_nenhum_servico():
    publicados = {nome for nome, servico in _implantacao().items() if servico.get('ports')}
    assert publicados == set()


def test_todos_os_servicos_de_implantacao_reiniciam_sozinhos():
    servicos = _implantacao()
    for nome in ('app_azul', 'app_verde', 'pgb_ns', 'pgb1', 'pgb2', 'banco', 'nginx', 'cloudflared'):
        assert servicos[nome]['restart'] == 'unless-stopped', nome


def test_app_verde_so_existe_na_implantacao_e_dev_sobe_so_o_azul():
    dev = _dev()
    assert 'app_verde' not in dev and 'estaticos_verde' not in dev
    assert 'app_azul' in dev
    assert dev['app_azul']['ports'][0]['published'] == '8000'
    assert 'app_verde' in _implantacao()


def test_porta_8000_so_no_azul_para_o_verde_nao_colidir():
    # Porta da 8000 só no azul: no verde, com o profile ligado, a mesma porta colidiria.
    assert not _implantacao()['app_verde'].get('ports')
    assert _implantacao()['app_azul'].get('ports') in (None, [])


# Caso infeliz: o que não pode acontecer.

def test_implantacao_sem_destino_do_alvo_recusa_subir():
    # Sem PHATI_ALVO_DIR o nginx cairia no `alvo.conf` do repositório (azul), mesmo com o verde no ar.
    rc, _, erro = _config(IMPLANTACAO, {'PHATI_ALVO_DIR': ''})
    assert rc != 0
    assert 'PHATI_ALVO_DIR' in erro


def test_pgb_e_pgbouncer_nao_recebem_a_senha_do_papel_app():
    for nome, servico in _implantacao().items():
        if nome.startswith('pgb'):
            assert 'PHATI_BANCO_APP_SENHA' not in _ambiente(servico), nome


def test_pgb_nao_montam_o_volume_dos_pacotes_nem_das_camadas():
    for nome, servico in _implantacao().items():
        if nome.startswith('pgb'):
            assert set(_volumes(servico)) <= {'/cfg'}, nome


def test_volume_de_cfg_do_pgbouncer_e_somente_leitura_nas_instancias():
    for nome in ('pgb1', 'pgb2'):
        assert _volumes(_implantacao()[nome])['/cfg']['read_only'] is True, nome
    assert _volumes(_implantacao()['pgb_auth'])['/cfg'].get('read_only') is not True


def test_pgb_sem_tmpfs_o_socket_fica_na_camada_do_contener():
    # Caso negativo: tmpfs em /run/pgb quebrou o restart (mkdir negado após `docker start`, medido). Volta se alguém reintroduzir.
    for nome in ('pgb1', 'pgb2'):
        assert '/run/pgb' not in _volumes(_implantacao()[nome]), nome
        assert not any(isinstance(v, dict) and v.get('tmpfs') for v in _volumes(_implantacao()[nome]).values()), nome


def test_healthcheck_pgb_e_liveness_do_socket_da_propria_instancia():
    # Liveness barato: confere o socket da própria instância, sem pg_isready (que loga `no such user: postgres`).
    assert _implantacao()['pgb1']['healthcheck']['test'] == ['CMD', 'test', '-S', '/tmp/pgb/pgb1/.s.PGSQL.6432']
    assert _implantacao()['pgb2']['healthcheck']['test'] == ['CMD', 'test', '-S', '/tmp/pgb/pgb2/.s.PGSQL.6432']


# Texto do PgBouncer: a config não pode afrouxar a autenticação nem o pool.

def _ini():
    chaves = {}
    for linha in (PGBOUNCER / 'pgbouncer.ini').read_text(encoding='utf-8').splitlines():
        if linha.startswith((';', '[')) or '=' not in linha:
            continue
        chave, valor = linha.split('=', 1)
        chaves[chave.strip()] = valor.strip()
    return chaves


def test_pgbouncer_ini_usa_scram_transaction_e_prepared_statements():
    ini = _ini()
    assert ini['auth_type'] == 'scram-sha-256'
    assert ini['pool_mode'] == 'transaction'
    assert int(ini['max_prepared_statements']) > 0
    assert ini['so_reuseport'] == '1'
    assert ini['listen_port'] == '6432'
    assert ini['auth_file'] == '/cfg/userlist.txt'


def test_pgbouncer_ini_nao_tem_trust_nem_senha_literal():
    # Caso negativo: `trust` deixaria entrar sem senha; senha ou verificador no arquivo versionado é vazamento.
    ativas = [linha for linha in (PGBOUNCER / 'pgbouncer.ini').read_text(encoding='utf-8').splitlines() if not linha.startswith(';')]
    texto = '\n'.join(ativas)
    assert 'trust' not in texto
    assert not re.search(r'(?i)password|senha', texto)


def test_pgbouncer_dir_nao_tem_verificador_nem_senha_literal():
    for arquivo in PGBOUNCER.iterdir():
        if arquivo.is_file():
            texto = arquivo.read_text(encoding='utf-8')
            assert 'SCRAM-SHA-256$' not in texto, arquivo.name
            assert not re.search(r'(?i)(senha|password)\s*[=:]\s*[^\s$]', texto), arquivo.name
