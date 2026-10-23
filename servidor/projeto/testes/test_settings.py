import re
import runpy
from pathlib import Path

import pytest
from django.conf import settings
from django.db import ProgrammingError, connections

CAMINHO = Path(settings.DIRETORIO_BASE) / 'projeto' / 'settings.py'

# `app` lê o que o dono migrou e já foi confirmado no banco de teste; sem dado novo, sem `transaction=True`.
usa_app = pytest.mark.django_db(databases=['default', 'app'])


def test_chave_secreta_ausente_falha_alto(monkeypatch):
    monkeypatch.delenv('PHATI_CHAVE_SECRETA')
    with pytest.raises(KeyError):
        runpy.run_path(str(CAMINHO))


def test_processo_web_sem_senha_do_dono_usa_o_papel_app_como_padrao(monkeypatch):
    monkeypatch.delenv('PHATI_BANCO_DONO_SENHA')
    bancos = runpy.run_path(str(CAMINHO))['DATABASES']
    assert bancos['default']['USER'] == bancos['app']['USER']
    assert bancos['default']['PASSWORD'] == bancos['app']['PASSWORD']


def test_dois_papeis_distintos():
    assert settings.DATABASES['default']['USER'] != settings.DATABASES['app']['USER']


def _um(alias, sql):
    with connections[alias].cursor() as consulta:
        consulta.execute(sql)
        return consulta.fetchone()


@usa_app
def test_papel_app_nao_e_super_nem_ignora_rls_nem_cria():
    sql = 'SELECT rolsuper, rolbypassrls, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname = current_user'
    assert _um('app', sql) == (False, False, False, False)


@usa_app
def test_papel_app_nao_e_dono_e_papel_dono_e():
    donas = "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tableowner = current_user"
    assert _um('app', donas) == (0,)
    assert _um('default', donas)[0] > 0


@usa_app
def test_papel_app_le_tabela_do_dono_mas_nao_cria_tabela():
    assert _um('app', 'SELECT count(*) FROM permissao') == (27,)
    with pytest.raises(ProgrammingError, match='permission denied'), connections['app'].cursor() as consulta:
        consulta.execute('CREATE TABLE intrusa (id int)')


def test_compose_repassa_toda_variavel_que_o_settings_le():
    # Achado do Codex (PR #1): variável do shell só chega ao contêiner se o compose a listar.
    lidas = set(re.findall(r'PHATI_[A-Z_]+', CAMINHO.read_text(encoding='utf-8')))
    listadas = set(re.findall(r'PHATI_[A-Z_]+', (CAMINHO.parents[1] / 'compose.yaml').read_text(encoding='utf-8')))
    assert lidas - listadas == set()
