import pytest
from django.db import ProgrammingError, connections, transaction

from permissao.models import Permissao

pytestmark = pytest.mark.django_db

NAO_DELEGAVEIS = {'aprovar_geometria', 'tornar_revisao_vigente', 'criar_empresa'}


def test_catalogo_tem_27_acoes():
    assert Permissao.objects.count() == 27


def test_so_tres_acoes_sao_nao_delegaveis():
    assert set(Permissao.objects.filter(delegavel=False).values_list('codigo', flat=True)) == NAO_DELEGAVEIS


@pytest.mark.django_db(databases=['default', 'app'])
def test_papel_app_le_o_catalogo_mas_nao_escreve():
    with connections['app'].cursor() as consulta:
        consulta.execute('SELECT count(*) FROM permissao')
        assert consulta.fetchone() == (27,)
        for escrita in ("INSERT INTO permissao VALUES ('x', 'x', true)", 'UPDATE permissao SET delegavel = true', 'DELETE FROM permissao'):
            # savepoint: a falha aborta a transação do teste e a próxima escrita precisa rodar.
            with pytest.raises(ProgrammingError, match='permission denied'), transaction.atomic(using='app'):
                consulta.execute(escrita)
