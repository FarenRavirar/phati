"""Entrypoint do PgBouncer (spec 009 R18): modelo por instância e passo `auth` do userlist, com `psql` e `pgbouncer` falsos.

Roda o `servidor/pgbouncer/entrypoint.sh` com `sh` (Git sh no Windows). Os binários reais não rodam aqui; o que se mede é
a lógica do script: validação de nomes, substituição no modelo e a recusa de verificador que não é SCRAM.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from django.conf import settings

PGBOUNCER = Path(settings.DIRETORIO_BASE) / 'pgbouncer'
ENTRYPOINT = PGBOUNCER / 'entrypoint.sh'
MODELO = PGBOUNCER / 'pgbouncer.ini'
VERIFICADOR = '"app" "SCRAM-SHA-256$4096:c2ludGV0aWNv$AAAAsintetico=:BBBBsintetico="'


def _sh():
    sh = shutil.which('sh')
    assert sh is not None, 'sh ausente no PATH: o teste do entrypoint precisa de um sh (Git for Windows traz um)'
    return sh


def _fake(diretorio, nome, corpo):
    arquivo = diretorio / nome
    arquivo.write_text('#!/bin/sh\n' + corpo, encoding='utf-8', newline='\n')
    arquivo.chmod(0o755)
    return arquivo.as_posix()


def _rodar(tmp_path, args=(), **ambiente):
    base = {
        'PATH': os.environ['PATH'],
        'PGB_RAIZ': (tmp_path / 'raiz').as_posix(),
        'PGB_CFG': (tmp_path / 'cfg').as_posix(),
        'PGB_MODELO': MODELO.as_posix(),
        'PGB_INSTANCIA': 'pgb1',
        'PHATI_BANCO_NOME': 'phati',
        'PHATI_BANCO_APP_USUARIO': 'app',
    }
    base.update(ambiente)
    return subprocess.run(
        [_sh(), ENTRYPOINT.as_posix(), *args], env=base, capture_output=True, text=True, encoding='utf-8', check=False, timeout=60,
    )


def _cat_como_pgbouncer(tmp_path):
    # `cat` no lugar do pgbouncer: a saída é o .ini que o entrypoint gerou, sem subir processo.
    return {'PGB_BIN': _fake(tmp_path, 'pgb_cat.sh', 'exec cat "$@"\n')}


def test_instancia_gera_o_ini_com_socket_e_banco_da_propria_instancia(tmp_path):
    (tmp_path / 'cfg').mkdir()
    r = _rodar(tmp_path, **_cat_como_pgbouncer(tmp_path))
    assert r.returncode == 0, r.stderr
    assert '@' not in r.stdout
    assert 'phati = host=banco port=5432 dbname=phati' in r.stdout
    assert 'unix_socket_dir = /tmp/pgb/pgb1' not in r.stdout  # o caminho é o da raiz de teste, não o de produção
    assert (tmp_path / 'raiz' / 'pgb1' / 'pgbouncer.ini').is_file()
    assert f"unix_socket_dir = {(tmp_path / 'raiz' / 'pgb1').as_posix()}" in r.stdout


def test_duas_instancias_tem_socket_e_log_separados(tmp_path):
    r2 = _rodar(tmp_path, PGB_INSTANCIA='pgb2', **_cat_como_pgbouncer(tmp_path))
    assert r2.returncode == 0, r2.stderr
    assert f"logfile = {(tmp_path / 'raiz' / 'pgb2' / 'pgb.log').as_posix()}" in r2.stdout


def test_restos_de_pid_e_socket_sao_removidos_antes_de_subir(tmp_path):
    # Restart na camada do contêiner deixa pid e socket velhos; sem remover, o novo processo não sobe.
    dir_pgb1 = tmp_path / 'raiz' / 'pgb1'
    dir_pgb1.mkdir(parents=True)
    (dir_pgb1 / 'pgb.pid').write_text('123\n', encoding='utf-8')
    (dir_pgb1 / '.s.PGSQL.6432').write_text('velho', encoding='utf-8')
    r = _rodar(tmp_path, **_cat_como_pgbouncer(tmp_path))
    assert r.returncode == 0, r.stderr
    assert not (dir_pgb1 / 'pgb.pid').exists()
    assert not (dir_pgb1 / '.s.PGSQL.6432').exists()
    assert (dir_pgb1 / 'pgbouncer.ini').is_file()


def test_instancia_com_caractere_fora_do_padrao_recusa_subir(tmp_path):
    # Caso negativo: o nome entra no .ini e no caminho do socket; `;` ou `/` poderiam mudar a config.
    r = _rodar(tmp_path, PGB_INSTANCIA='pgb1;x', **_cat_como_pgbouncer(tmp_path))
    assert r.returncode != 0
    assert 'PGB_INSTANCIA inválida' in r.stderr


def test_instancia_em_maiusculas_recusa_subir(tmp_path):
    # Caso negativo: maiúscula está fora do padrão `[a-z0-9_]`, então o validador do `case` tem de recusar.
    r = _rodar(tmp_path, PGB_INSTANCIA='PGB1', **_cat_como_pgbouncer(tmp_path))
    assert r.returncode != 0
    assert 'PGB_INSTANCIA inválida' in r.stderr


def test_nome_de_banco_com_caractere_fora_do_padrao_recusa_subir(tmp_path):
    r = _rodar(tmp_path, PHATI_BANCO_NOME='phati/../x', **_cat_como_pgbouncer(tmp_path))
    assert r.returncode != 0
    assert 'PHATI_BANCO_NOME inválido' in r.stderr


def test_auth_grava_o_userlist_com_o_verificador_scram(tmp_path):
    cfg = tmp_path / 'cfg'
    cfg.mkdir()
    psql = _fake(tmp_path, 'psql_ok.sh', f"cat >/dev/null\nprintf '%s\\n' '{VERIFICADOR}'\n")
    r = _rodar(tmp_path, args=('auth',), PGB_PSQL=psql)
    assert r.returncode == 0, r.stderr
    assert (cfg / 'userlist.txt').read_text(encoding='utf-8') == VERIFICADOR + '\n'
    assert not (cfg / 'userlist.tmp').exists()
    assert r.stdout == ''
    assert VERIFICADOR not in r.stderr  # o verificador não vai a log


def test_auth_recusa_papel_sem_senha_e_nao_grava(tmp_path):
    # Caso negativo: papel sem senha dá linha vazia; NULL virar userlist vazio falharia em silêncio.
    cfg = tmp_path / 'cfg'
    cfg.mkdir()
    psql = _fake(tmp_path, 'psql_vazio.sh', 'cat >/dev/null\nprintf "\\n"\n')
    r = _rodar(tmp_path, args=('auth',), PGB_PSQL=psql)
    assert r.returncode != 0
    assert not (cfg / 'userlist.txt').exists()
    assert not (cfg / 'userlist.tmp').exists()


def test_auth_recusa_senha_md5_que_nao_e_scram(tmp_path):
    cfg = tmp_path / 'cfg'
    cfg.mkdir()
    psql = _fake(tmp_path, 'psql_md5.sh', "cat >/dev/null\nprintf '%s\\n' '\"app\" \"md5abcdef0123456789\"'\n")
    r = _rodar(tmp_path, args=('auth',), PGB_PSQL=psql)
    assert r.returncode != 0
    assert 'SCRAM' in r.stderr
    assert not (cfg / 'userlist.txt').exists()


def test_auth_falha_do_psql_nao_deixa_arquivo_parcial(tmp_path):
    cfg = tmp_path / 'cfg'
    cfg.mkdir()
    psql = _fake(tmp_path, 'psql_falha.sh', 'cat >/dev/null\nprintf "%s\\n" "\\"app\\" \\"SCRAM-SHA-256$x$y\\""\nexit 2\n')
    r = _rodar(tmp_path, args=('auth',), PGB_PSQL=psql)
    assert r.returncode != 0
    assert 'a consulta ao banco falhou' in r.stderr
    assert not (cfg / 'userlist.txt').exists()
    assert not (cfg / 'userlist.tmp').exists()


def test_auth_recusa_usuario_do_app_fora_do_padrao(tmp_path):
    cfg = tmp_path / 'cfg'
    cfg.mkdir()
    r = _rodar(tmp_path, args=('auth',), PHATI_BANCO_APP_USUARIO="app'; drop", PGB_PSQL='/nao-existe')
    assert r.returncode != 0
    assert not (cfg / 'userlist.txt').exists()


def test_destino_ausente_gera_host_banco(tmp_path):
    (tmp_path / 'cfg').mkdir()
    r = _rodar(tmp_path, **_cat_como_pgbouncer(tmp_path))
    assert r.returncode == 0, r.stderr
    assert 'phati = host=banco port=5432 dbname=phati' in r.stdout
    assert '@' not in r.stdout


def test_destino_informado_vira_o_host_do_banco(tmp_path):
    (tmp_path / 'cfg').mkdir()
    r = _rodar(tmp_path, PHATI_BANCO_DESTINO='banco_novo', **_cat_como_pgbouncer(tmp_path))
    assert r.returncode == 0, r.stderr
    assert 'phati = host=banco_novo port=5432 dbname=phati' in r.stdout
    assert 'host=banco port' not in r.stdout


@pytest.mark.parametrize('destino', ['banco;x', 'banco x', '', '$(id)', 'banco\nx', 'banco@x', 'banco/x', '-banco', 'ban`co`'])
def test_destino_fora_do_padrao_recusa_subir_sem_arquivo_parcial(tmp_path, destino):
    # Caso negativo: o valor entra no .ini. A checagem roda antes de criar o diretório, então nada fica pela metade.
    r = _rodar(tmp_path, PHATI_BANCO_DESTINO=destino, **_cat_como_pgbouncer(tmp_path))
    assert r.returncode != 0
    assert 'PHATI_BANCO_DESTINO inválido' in r.stderr
    assert not (tmp_path / 'raiz').exists()


def _destino_gravado(tmp_path, texto):
    # `banco-destino` gravado pelo passo do `trocar-banco.sh` no volume `pgb_cfg` (montado em /cfg).
    (tmp_path / 'cfg').mkdir(exist_ok=True)
    (tmp_path / 'cfg' / 'banco-destino').write_text(texto, encoding='utf-8', newline='')


def test_arquivo_banco_destino_vence_a_variavel_de_ambiente(tmp_path):
    # Reprodução do achado P1: o ambiente do contêiner ainda diz `banco` depois da troca; o arquivo do volume manda.
    _destino_gravado(tmp_path, 'banco_novo\n')
    r = _rodar(tmp_path, PHATI_BANCO_DESTINO='banco', **_cat_como_pgbouncer(tmp_path))
    assert r.returncode == 0, r.stderr
    assert 'phati = host=banco_novo port=5432 dbname=phati' in r.stdout
    assert 'host=banco port' not in r.stdout


def test_reiniciar_com_ambiente_antigo_mantem_o_banco_novo(tmp_path):
    # Reinício = nova execução do entrypoint com o mesmo ambiente antigo (docker restart não troca env do contêiner).
    _destino_gravado(tmp_path, 'banco_novo\n')
    for _ in range(2):
        r = _rodar(tmp_path, PHATI_BANCO_DESTINO='banco', **_cat_como_pgbouncer(tmp_path))
        assert r.returncode == 0, r.stderr
        assert 'phati = host=banco_novo port=5432 dbname=phati' in r.stdout


def test_arquivo_ausente_usa_a_variavel_de_ambiente(tmp_path):
    (tmp_path / 'cfg').mkdir()
    r = _rodar(tmp_path, PHATI_BANCO_DESTINO='banco_novo', **_cat_como_pgbouncer(tmp_path))
    assert r.returncode == 0, r.stderr
    assert 'phati = host=banco_novo port=5432 dbname=phati' in r.stdout


def test_arquivo_vazio_e_ignorado_e_usa_a_variavel(tmp_path):
    _destino_gravado(tmp_path, '')
    r = _rodar(tmp_path, PHATI_BANCO_DESTINO='banco_novo', **_cat_como_pgbouncer(tmp_path))
    assert r.returncode == 0, r.stderr
    assert 'phati = host=banco_novo port=5432 dbname=phati' in r.stdout


@pytest.mark.parametrize(
    'conteudo',
    ['banco; rm -rf /\n', ' \n', 'banco\nbanco_novo\n', 'banco\n\n', '@\n', '/\n', 'banco\r\n', '\nbanco\n', 'banco x\n'],
)
def test_arquivo_banco_destino_hostil_recusa_subir_sem_ini_parcial(tmp_path, conteudo):
    # Caso negativo: o conteúdo do arquivo entra no .ini; mesma regra de host da variável, e mais de uma linha recusa.
    _destino_gravado(tmp_path, conteudo)
    r = _rodar(tmp_path, PHATI_BANCO_DESTINO='banco', **_cat_como_pgbouncer(tmp_path))
    assert r.returncode != 0
    assert 'banco-destino inválido' in r.stderr
    assert not (tmp_path / 'raiz').exists()


def _exige_login_retry(ini, valor='2'):
    # Linhas ativas (sem comentário `;`) do ini renderizado; o parâmetro tem de estar com o valor do ensaio (ver pgbouncer.ini).
    ativas = [linha.strip() for linha in ini.splitlines() if linha.strip() and not linha.lstrip().startswith(';')]
    assert f'server_login_retry = {valor}' in ativas, 'server_login_retry ausente ou com valor diferente de 2 no ini renderizado'


def test_ini_renderizado_tem_server_login_retry_curto(tmp_path):
    # Medido no ensaio (padrão 15 s = ~16 s de falha visível após o banco voltar); o valor 2 vem do pgbouncer.ini.
    (tmp_path / 'cfg').mkdir()
    r = _rodar(tmp_path, **_cat_como_pgbouncer(tmp_path))
    assert r.returncode == 0, r.stderr
    _exige_login_retry(r.stdout)


def test_ini_sem_server_login_retry_falha(tmp_path):
    # Caso negativo: sem a linha, o PgBouncer volta ao padrão de 15 s e a falha visível se repete.
    original = MODELO.read_text(encoding='utf-8')
    mutado = re.sub(r'^server_login_retry = .*\n', '', original, flags=re.M)
    assert mutado != original, 'mutação não aplicou: server_login_retry não está no modelo'
    (tmp_path / 'cfg').mkdir()
    modelo = tmp_path / 'modelo.ini'
    modelo.write_text(mutado, encoding='utf-8', newline='\n')
    r = _rodar(tmp_path, PGB_MODELO=modelo.as_posix(), **_cat_como_pgbouncer(tmp_path))
    assert r.returncode == 0, r.stderr
    with pytest.raises(AssertionError, match='server_login_retry'):
        _exige_login_retry(r.stdout)


def test_ini_com_server_login_retry_de_15_segundos_falha(tmp_path):
    # Caso negativo: valor 15 (padrão) no lugar de 2 é o defeito que o ensaio mediu.
    original = MODELO.read_text(encoding='utf-8')
    mutado = re.sub(r'^server_login_retry = 2$', 'server_login_retry = 15', original, flags=re.M)
    assert mutado != original, 'mutação não aplicou: linha server_login_retry = 2 ausente'
    (tmp_path / 'cfg').mkdir()
    modelo = tmp_path / 'modelo.ini'
    modelo.write_text(mutado, encoding='utf-8', newline='\n')
    r = _rodar(tmp_path, PGB_MODELO=modelo.as_posix(), **_cat_como_pgbouncer(tmp_path))
    assert r.returncode == 0, r.stderr
    with pytest.raises(AssertionError, match='server_login_retry'):
        _exige_login_retry(r.stdout)
