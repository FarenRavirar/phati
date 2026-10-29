"""Contexto de RLS assinado (R12): o papel `app` não forja escopo nem identidade, só a aplicação assina.

Antes da assinatura, `SET app.plataforma = '1'` na sessão abria todas as linhas e `vinculos_da_pessoa` devolvia as
concessões de qualquer pessoa (achado do Sourcery na PR #13, medido). Os testes tentam cada forja como o papel `app`.
"""

import pytest
from django.db import ProgrammingError, connection, connections, transaction
from django.utils import timezone

from permissao.pode import com_permissao
from permissao.testes.test_rls import FIXAR, TABELAS, mundo  # noqa: F401

pytestmark = pytest.mark.django_db(transaction=True, databases=['default', 'app'])
VARIAVEIS = ('plataforma', 'empresas', 'empresas_de_fazendas', 'fazendas')
SEM_ASSINATURA = {'plataforma': '1', 'empresas': '1,2', 'empresas_de_fazendas': '1,2', 'fazendas': '1,2,3'}


def _contar(tabela, variaveis):
    """Linhas que o papel `app` vê em `tabela` com as variáveis dadas fixadas à mão, sem passar pela aplicação."""
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        for nome, valor in variaveis.items():
            consulta.execute(FIXAR, [f'app.{nome}', valor])
        consulta.execute(f'SELECT count(*) FROM {tabela}')
        return consulta.fetchone()[0]


@pytest.mark.parametrize('tabela', TABELAS)
def test_variaveis_fixadas_a_mao_sem_assinatura_nao_abrem_linha(mundo, tabela):
    with connection.cursor() as dono:
        dono.execute(f'SELECT count(*) FROM {tabela}')
        assert dono.fetchone()[0] > 0  # sem isso o zero do `app` poderia ser tabela vazia
    assert _contar(tabela, SEM_ASSINATURA) == 0


@pytest.mark.parametrize('tabela', TABELAS)
def test_assinatura_forjada_nao_abre_linha(mundo, tabela):
    assert _contar(tabela, {**SEM_ASSINATURA, 'assinatura': 'a' * 64}) == 0


def test_assinatura_de_outra_transacao_nao_vale(mundo):
    with com_permissao(mundo.dono_x, usando='app'), connections['app'].cursor() as consulta:
        consulta.execute('SELECT count(*) FROM empresa')
        assert consulta.fetchone()[0] == 1  # a transação legítima enxerga a empresa X
        consulta.execute(
            "SELECT current_setting('app.plataforma'), current_setting('app.empresas'),"
            " current_setting('app.empresas_de_fazendas'), current_setting('app.fazendas'),"
            " current_setting('app.assinatura')"
        )
        plataforma, empresas, de_fazendas, fazendas, assinatura = consulta.fetchone()
    copiado = {
        'plataforma': plataforma, 'empresas': empresas, 'empresas_de_fazendas': de_fazendas, 'fazendas': fazendas,
        'assinatura': assinatura,
    }
    assert _contar('empresa', copiado) == 0


def test_contexto_assinado_abre_so_o_que_foi_assinado(mundo):
    from permissao.contexto import fixar_contexto

    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        fixar_contexto(consulta, '', str(mundo.x.pk), '', '')
        consulta.execute('SELECT id FROM empresa')
        assert {linha[0] for linha in consulta.fetchall()} == {mundo.x.pk}
        # Alterar o escopo depois de assinado invalida a assinatura: nada abre.
        consulta.execute(FIXAR, ['app.empresas', f'{mundo.x.pk},{mundo.y.pk}'])
        consulta.execute('SELECT count(*) FROM empresa')
        assert consulta.fetchone()[0] == 0


def _vinculos(pessoa, assinar_como=None):
    from permissao.contexto import fixar_identidade

    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        if assinar_como is not None:
            fixar_identidade(consulta, assinar_como.pk)
        consulta.execute('SELECT concessao_id FROM vinculos_da_pessoa(%s, %s)', [pessoa.pk, timezone.now()])
        return consulta.fetchall()


def test_vinculos_da_pessoa_sem_identidade_assinada_devolve_nada(mundo):
    assert _vinculos(mundo.dono_x) == []


def test_vinculos_da_pessoa_de_outra_pessoa_devolve_nada(mundo):
    assert _vinculos(mundo.dono_x, assinar_como=mundo.dono_y) == []


def test_vinculos_da_propria_pessoa_assinada_devolve_as_concessoes(mundo):
    assert [linha[0] for linha in _vinculos(mundo.dono_x, assinar_como=mundo.dono_x)] == [mundo.de_x.pk]


def test_papel_app_nao_le_o_segredo_nem_o_grava(mundo):
    with connection.cursor() as dono:
        dono.execute('SELECT count(*) FROM rls_segredo')
        assert dono.fetchone()[0] == 1
    for comando in ('SELECT valor FROM rls_segredo', "UPDATE rls_segredo SET valor = 'x'::bytea"):
        with pytest.raises(ProgrammingError), transaction.atomic(using='app'), connections['app'].cursor() as consulta:
            consulta.execute(comando)


def test_papel_app_nao_executa_a_verificacao_de_identidade(mundo):
    with connection.cursor() as dono:
        dono.execute("SELECT has_function_privilege('app', 'app_identidade_ok(bigint)', 'EXECUTE')")
        assert dono.fetchone() == (False,)
        dono.execute("SELECT has_function_privilege('app', 'app_contexto_ok()', 'EXECUTE')")
        assert dono.fetchone() == (True,)  # as políticas rodam como o `app` e precisam chamá-la
