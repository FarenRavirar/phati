import base64
import re
import runpy
from pathlib import Path

import pytest
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
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


def test_healthcheck_do_banco_espera_o_servidor_tcp():
    # Achado do CodeRabbit (PR #1): sem `-h`, o pg_isready aceita o servidor temporário do initdb (só socket).
    compose = (CAMINHO.parents[1] / 'compose.yaml').read_text(encoding='utf-8')
    assert 'pg_isready -h 127.0.0.1' in compose


def test_smtp_tem_prazo_para_nao_prender_o_processo():
    # Achado do Qodo (PR #9): sem timeout, um SMTP mudo bloqueia o pedido de redefinição sem fim.
    # O pytest-django troca MAILERS por um backend em memória; por isso lê-se o arquivo, como nos testes acima.
    opcoes = runpy.run_path(str(CAMINHO))['MAILERS']['default']['OPTIONS']
    assert 0 < opcoes['timeout'] <= 30


@pytest.mark.parametrize('invalida', ['', 'curta', 'AAAA' * 8, 'A' * 43, 'não-ascii-é' * 4])
def test_chave_do_cpf_fora_do_formato_derruba_o_servidor(monkeypatch, invalida):
    # Achado do CodeRabbit (PR #9): chave truncada ou com lixo trocaria o HMAC e perderia os CPFs já cadastrados.
    monkeypatch.setenv('PHATI_CHAVE_CPF', invalida)
    with pytest.raises(ImproperlyConfigured):
        runpy.run_path(str(CAMINHO))


def test_chave_do_cpf_ausente_derruba_o_servidor(monkeypatch):
    monkeypatch.delenv('PHATI_CHAVE_CPF')
    with pytest.raises(ImproperlyConfigured):
        runpy.run_path(str(CAMINHO))


def test_chave_do_cpf_de_32_bytes_e_aceita(monkeypatch):
    bruta = bytes(range(32))
    monkeypatch.setenv('PHATI_CHAVE_CPF', base64.urlsafe_b64encode(bruta).decode())
    assert runpy.run_path(str(CAMINHO))['CHAVE_CPF'] == bruta


def test_chave_do_cpf_com_caractere_estranho_derruba_o_servidor(monkeypatch):
    # A decodificação tolerante do Python descarta o "!" e devolveria os mesmos 32 bytes; a forma canônica barra.
    monkeypatch.setenv('PHATI_CHAVE_CPF', base64.urlsafe_b64encode(bytes(range(32))).decode() + '!')
    with pytest.raises(ImproperlyConfigured):
        runpy.run_path(str(CAMINHO))


@pytest.mark.parametrize('invalido', ['', 'curta', 'AAAA' * 8, 'A' * 43])
def test_segredo_da_rls_fora_do_formato_derruba_o_servidor(monkeypatch, invalido):
    # Segredo errado trocaria a assinatura do contexto de RLS: o banco negaria todo acesso sem aviso.
    monkeypatch.setenv('PHATI_SEGREDO_RLS', invalido)
    with pytest.raises(ImproperlyConfigured, match='PHATI_SEGREDO_RLS'):
        runpy.run_path(str(CAMINHO))


def test_segredo_da_rls_ausente_derruba_o_servidor(monkeypatch):
    monkeypatch.delenv('PHATI_SEGREDO_RLS')
    with pytest.raises(ImproperlyConfigured, match='PHATI_SEGREDO_RLS'):
        runpy.run_path(str(CAMINHO))


def test_segredo_da_rls_de_32_bytes_e_aceito(monkeypatch):
    bruto = bytes(range(32, 64))
    monkeypatch.setenv('PHATI_SEGREDO_RLS', base64.urlsafe_b64encode(bruto).decode())
    assert runpy.run_path(str(CAMINHO))['SEGREDO_RLS'] == bruto


def test_variaveis_de_email_chegam_ao_smtp_com_a_porta_inteira(monkeypatch):
    # Achado do CodeRabbit (PR #9): nada provava que o ambiente configura o SMTP.
    monkeypatch.setenv('PHATI_EMAIL_HOST', 'smtp.exemplo.test')
    monkeypatch.setenv('PHATI_EMAIL_PORTA', '2525')
    monkeypatch.setenv('PHATI_EMAIL_USUARIO', 'usuario-de-teste')
    monkeypatch.setenv('PHATI_EMAIL_SENHA', 'valor-de-teste')
    monkeypatch.setenv('PHATI_EMAIL_REMETENTE', 'remetente@exemplo.test')
    configuracao = runpy.run_path(str(CAMINHO))
    opcoes = configuracao['MAILERS']['default']['OPTIONS']
    assert opcoes['host'] == 'smtp.exemplo.test'
    assert opcoes['port'] == 2525
    assert opcoes['username'] == 'usuario-de-teste'
    assert opcoes['password'] == 'valor-de-teste'
    assert configuracao['DEFAULT_FROM_EMAIL'] == 'remetente@exemplo.test'
