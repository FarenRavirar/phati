import os
import shutil
import subprocess
from pathlib import Path

from django.conf import settings

SCRIPT = Path(settings.DIRETORIO_BASE) / 'banco' / 'atualizar-postgis.sh'
SH = shutil.which('sh') or 'sh'


def _rodar(tmp_path, monkeypatch, *, falha_em=None, nome=None):
    """Roda o script com um `psql` de mentira no PATH que anota os argumentos; `falha_em` é o banco que devolve erro."""
    anotado = tmp_path / 'chamadas.txt'
    dublê = tmp_path / 'bin' / 'psql'
    dublê.parent.mkdir(exist_ok=True)
    dublê.write_text(
        '#!/bin/sh\n'
        f'echo "$*" >> "{anotado.as_posix()}"\n'
        f'[ "$5" = "{falha_em or "__nenhum__"}" ] && exit 3\n'
        'exit 0\n',
        encoding='utf-8',
    )
    dublê.chmod(0o755)
    ambiente = {**os.environ, 'PATH': f'{dublê.parent}{os.pathsep}{os.environ["PATH"]}'}
    ambiente.pop('PHATI_BANCO_NOME', None)
    if nome is not None:
        ambiente['PHATI_BANCO_NOME'] = nome
    resultado = subprocess.run([SH, str(SCRIPT)], env=ambiente, capture_output=True, text=True, check=False)
    chamadas = anotado.read_text(encoding='utf-8').splitlines() if anotado.exists() else []
    return resultado, chamadas


def test_cria_postgis_em_template1_e_no_banco_da_aplicacao(tmp_path, monkeypatch):
    resultado, chamadas = _rodar(tmp_path, monkeypatch, nome='phati_x')
    assert resultado.returncode == 0, resultado.stderr
    assert len(chamadas) == 2
    assert '-d template1' in chamadas[0]
    assert '-d phati_x' in chamadas[1]
    assert all('ON_ERROR_STOP=1' in c for c in chamadas)
    assert all('CREATE EXTENSION IF NOT EXISTS postgis;' in c for c in chamadas)


def test_banco_padrao_e_phati_quando_a_variavel_nao_existe(tmp_path, monkeypatch):
    resultado, chamadas = _rodar(tmp_path, monkeypatch)
    assert resultado.returncode == 0, resultado.stderr
    assert '-d phati' in chamadas[1]


def test_segunda_execucao_faz_as_mesmas_chamadas_e_termina_bem(tmp_path, monkeypatch):
    primeira, _ = _rodar(tmp_path, monkeypatch)
    segunda, chamadas = _rodar(tmp_path, monkeypatch)
    assert primeira.returncode == segunda.returncode == 0
    assert len(chamadas) == 4


def test_falha_do_psql_para_o_script_e_nao_segue_para_o_banco_da_aplicacao(tmp_path, monkeypatch):
    resultado, chamadas = _rodar(tmp_path, monkeypatch, falha_em='template1')
    assert resultado.returncode != 0
    assert len(chamadas) == 1
