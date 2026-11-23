"""Estático de `banco/papeis.sql` (spec 009, R15, T5.3): papel `replicador` sem senha literal e concessões no `phati`.

A execução real num PostgreSQL descartável foi medida à parte (saída citada no relatório); aqui o texto é conferido.
"""

import re
from pathlib import Path

from django.conf import settings

PAPEIS = (Path(settings.DIRETORIO_BASE) / 'banco' / 'papeis.sql').read_text(encoding='utf-8')
LINHAS = PAPEIS.splitlines()


def _sem_comentarios(texto):
    return '\n'.join(linha for linha in texto.splitlines() if not linha.lstrip().startswith('--'))


def _tem_senha_literal(sql):
    # Senha escrita no texto: `PASSWORD '...'` ou `PASSWORD "..."`. `PASSWORD %L` (valor vindo do psql) não conta.
    return re.search(r"PASSWORD\s+['\"]", sql, re.IGNORECASE) is not None


def _pode_replicar(linha):
    # Papel só recebe replicação com o atributo REPLICATION (e LOGIN para conectar).
    tokens = linha.replace('(', ' ').split()
    return 'REPLICATION' in tokens and 'LOGIN' in tokens


def _linha_do_replicador():
    achadas = [linha for linha in LINHAS if 'CREATE ROLE replicador' in linha]
    assert len(achadas) == 1, achadas
    return achadas[0]


def test_papeis_cria_replicador_com_replication_e_login():
    assert _pode_replicar(_linha_do_replicador())


def test_replicador_recebe_senha_do_ambiente_e_nao_literal():
    linha = _linha_do_replicador()
    assert 'PASSWORD %L' in linha
    assert ":'senha_replicador'" in linha
    assert not _tem_senha_literal(_sem_comentarios(PAPEIS))


def test_replicador_concede_select_e_default_privileges_no_phati():
    sql = _sem_comentarios(PAPEIS)
    assert 'GRANT SELECT ON ALL TABLES IN SCHEMA public TO replicador;' in sql
    assert 'ALTER DEFAULT PRIVILEGES FOR ROLE :"usuario_dono" IN SCHEMA public GRANT SELECT ON TABLES TO replicador;' in sql


def test_concessoes_so_depois_de_conectar_no_banco_do_app():
    sql = _sem_comentarios(PAPEIS)
    conexao = sql.index('\\connect :"nome_banco"')
    assert conexao < sql.index('GRANT SELECT ON ALL TABLES')
    assert conexao < sql.index('ALTER DEFAULT PRIVILEGES')


def test_replicador_so_e_criado_com_senha_preenchida():
    # Senha vazia ou ausente: o papel não é criado e o init não falha (o `banco` do compose sobe sem a variável).
    sql = _sem_comentarios(PAPEIS)
    inicio = sql.index('\\if :tem_senha_replicador')
    assert inicio < sql.index('CREATE ROLE replicador') < sql.index('\\endif', inicio)
    assert "\\echo 'replicador não criado: PHATI_BANCO_REPLICADOR_SENHA vazia'" in sql


def test_concessoes_do_replicador_tambem_so_com_senha():
    sql = _sem_comentarios(PAPEIS)
    inicio = sql.index('\\if :tem_senha_replicador', sql.index('\\connect'))
    fim = sql.index('\\else', inicio)
    assert inicio < sql.index('GRANT SELECT ON ALL TABLES') < fim
    assert inicio < sql.index('ALTER DEFAULT PRIVILEGES') < fim


def test_papeis_e_banco_sao_idempotentes():
    # Rodar de novo num banco existente (homologação) não pode falhar: cada criação tem guarda.
    sql = _sem_comentarios(PAPEIS)
    criacoes = re.findall(r'CREATE (?:ROLE|DATABASE) .*', sql)
    assert len(criacoes) == 4
    guardadas = re.findall(r'\)\s*WHERE NOT EXISTS', sql)
    assert len(guardadas) == 4


def test_pg_hba_necessario_documentado_sem_ser_aplicado():
    # O pg_hba não é gerenciado pelo repositório: a linha fica só no comentário, não vira configuração.
    texto = PAPEIS
    assert 'host replication replicador 172.29.250.0/24 scram-sha-256' in texto
    assert 'host <banco> replicador 172.29.250.0/24 scram-sha-256' in texto


# Caso infeliz: o detector precisa reprovar o que deve reprovar, senão o teste acima não vale nada.

def test_senha_literal_no_sql_reprova():
    sql_ruim = "SELECT format('CREATE ROLE replicador LOGIN REPLICATION PASSWORD ''abc''') \\gexec\nCREATE ROLE x PASSWORD 'abc';"
    assert _tem_senha_literal(sql_ruim)


def test_papel_sem_replication_reprova_a_checagem_do_replicador():
    assert not _pode_replicar('CREATE ROLE replicador LOGIN NOREPLICATION PASSWORD %L')
    assert not _pode_replicar('CREATE ROLE replicador NOLOGIN REPLICATION PASSWORD %L')
