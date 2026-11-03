"""Contador de uso de atalho (003 R26, A16): só ação e contagem, só a própria pessoa lê, falha não propaga e apagar a pessoa
apaga as linhas."""

import logging

import pytest
from django.db import connection, connections, transaction

from permissao.contexto import fixar_identidade
from permissao.models import UsoAcao
from permissao.pode import com_permissao
from permissao.uso import definir_estado, registrar_uso, usos_da_pessoa

pytestmark = pytest.mark.django_db(transaction=True, databases=['default', 'app'])


def _quebrar(*_args, **_kwargs):
    raise RuntimeError('banco fora')


def _linhas_como_app(pessoa_assinada, pessoa_lida):
    """Linhas de `pessoa_lida` que o papel `app` enxerga com a identidade de `pessoa_assinada` (None: sem assinatura)."""
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        if pessoa_assinada is not None:
            fixar_identidade(consulta, pessoa_assinada.pk)
        consulta.execute('SELECT acao, contagem FROM uso_acao WHERE pessoa_id = %s', [pessoa_lida.pk])
        return consulta.fetchall()


def test_registrar_uso_cria_e_soma(fabrica_pessoa):
    pessoa = fabrica_pessoa('Quem usa')
    for _ in range(3):
        registrar_uso(pessoa, 'convidar_pessoa')
    registrar_uso(pessoa, 'gerenciar_cargo')
    usos = usos_da_pessoa(pessoa)
    assert {acao: uso.contagem for acao, uso in usos.items()} == {'convidar_pessoa': 3, 'gerenciar_cargo': 1}
    assert usos['convidar_pessoa'].ultimo_uso is not None


def test_a_tabela_nao_guarda_alvo():
    with connection.cursor() as consulta:
        colunas = {c.name for c in connection.introspection.get_table_description(consulta, 'uso_acao')}
    assert colunas == {'id', 'pessoa_id', 'acao', 'contagem', 'ultimo_uso', 'fixado', 'oculto'}


def test_falha_ao_contar_nao_propaga_e_fica_no_log(fabrica_pessoa, monkeypatch, caplog):
    pessoa = fabrica_pessoa('Quem usa')
    monkeypatch.setattr(UsoAcao.objects, 'filter', _quebrar)
    with caplog.at_level(logging.ERROR, logger='permissao.uso'):
        registrar_uso(pessoa, 'convidar_pessoa')  # não levanta
    assert 'Falha ao registrar uso da ação convidar_pessoa' in caplog.text


def test_falha_ao_ler_devolve_vazio(fabrica_pessoa, monkeypatch):
    pessoa = fabrica_pessoa('Quem usa')
    monkeypatch.setattr(UsoAcao.objects, 'filter', _quebrar)
    assert usos_da_pessoa(pessoa) == {}


def test_falha_ao_contar_dentro_de_transacao_nao_estraga_a_do_chamador(fabrica_pessoa, monkeypatch):
    pessoa = fabrica_pessoa('Quem usa')
    with transaction.atomic():
        with monkeypatch.context() as quebrado:
            quebrado.setattr(UsoAcao.objects, 'filter', _quebrar)
            registrar_uso(pessoa, 'convidar_pessoa')
        registrar_uso(pessoa, 'convidar_pessoa')  # a transação do chamador segue utilizável
    assert usos_da_pessoa(pessoa)['convidar_pessoa'].contagem == 1


def test_fixar_e_ocultar_gravam_na_linha_da_pessoa(fabrica_pessoa):
    pessoa = fabrica_pessoa('Quem escolhe')
    definir_estado(pessoa, 'gerenciar_cargo', fixado=True)
    definir_estado(pessoa, 'criar_fazenda', oculto=True)
    usos = usos_da_pessoa(pessoa)
    assert (usos['gerenciar_cargo'].fixado, usos['gerenciar_cargo'].oculto) == (True, False)
    assert (usos['criar_fazenda'].fixado, usos['criar_fazenda'].oculto) == (False, True)
    assert usos['gerenciar_cargo'].contagem == 0  # escolher não conta como uso


def test_so_a_propria_pessoa_le_o_uso(fabrica_pessoa):
    dona, outra = fabrica_pessoa('Dona'), fabrica_pessoa('Outra')
    registrar_uso(dona, 'convidar_pessoa')
    assert _linhas_como_app(dona, dona) == [('convidar_pessoa', 1)]
    assert _linhas_como_app(outra, dona) == []  # identidade de outra pessoa
    assert _linhas_como_app(None, dona) == []  # sem identidade assinada
    with connection.cursor() as dono_das_tabelas:  # o zero acima não é tabela vazia
        dono_das_tabelas.execute('SELECT count(*) FROM uso_acao')
        assert dono_das_tabelas.fetchone()[0] == 1


def test_identidade_de_outra_pessoa_nao_altera_nem_apaga_o_uso(fabrica_pessoa):
    dona, outra = fabrica_pessoa('Dona'), fabrica_pessoa('Outra')
    registrar_uso(dona, 'convidar_pessoa')
    with transaction.atomic(using='app'), connections['app'].cursor() as consulta:
        fixar_identidade(consulta, outra.pk)
        consulta.execute('UPDATE uso_acao SET contagem = 99 WHERE pessoa_id = %s', [dona.pk])
        assert consulta.rowcount == 0
        consulta.execute('DELETE FROM uso_acao WHERE pessoa_id = %s', [dona.pk])
        assert consulta.rowcount == 0
    assert usos_da_pessoa(dona)['convidar_pessoa'].contagem == 1


def test_apagar_a_pessoa_apaga_o_uso(fabrica_pessoa):
    pessoa = fabrica_pessoa('Sai da casa')
    registrar_uso(pessoa, 'convidar_pessoa')
    pessoa.delete()
    with connection.cursor() as consulta:
        consulta.execute('SELECT count(*) FROM uso_acao')
        assert consulta.fetchone()[0] == 0




@pytest.mark.usefixtures('como_app')
def test_apagar_a_pessoa_como_papel_app_apaga_o_uso_apesar_da_rls(fabrica_pessoa):
    pessoa = fabrica_pessoa('Sai da casa')
    registrar_uso(pessoa, 'convidar_pessoa')
    pessoa.delete()
    with connections['app'].cursor() as consulta, transaction.atomic(using='app'):
        consulta.execute('SELECT count(*) FROM pessoa WHERE id = %s', [pessoa.pk])
        assert consulta.fetchone()[0] == 0
    with connection.cursor() as dono:
        dono.execute('SELECT count(*) FROM uso_acao')
        assert dono.fetchone()[0] == 0
