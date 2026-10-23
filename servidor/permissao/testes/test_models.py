import pytest

from permissao.models import Permissao

pytestmark = pytest.mark.django_db

NAO_DELEGAVEIS = {'aprovar_geometria', 'tornar_revisao_vigente', 'criar_empresa'}


def test_catalogo_tem_27_acoes():
    assert Permissao.objects.count() == 27


def test_so_tres_acoes_sao_nao_delegaveis():
    assert set(Permissao.objects.filter(delegavel=False).values_list('codigo', flat=True)) == NAO_DELEGAVEIS
