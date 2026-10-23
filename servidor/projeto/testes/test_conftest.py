import pytest
from django.db import connections

# Os dois testes dependem da ordem do arquivo: o primeiro abre a conexão do papel `app`;
# a fixture de `servidor/conftest.py` deve fechá-la ao fim dele, e o segundo confere.
usa_app = pytest.mark.django_db(databases=['default', 'app'])


@usa_app
def test_abre_a_conexao_do_papel_app():
    with connections['app'].cursor() as consulta:
        consulta.execute('SELECT 1')
    assert connections['app'].connection is not None


@pytest.mark.django_db  # sem o alias `app`: o teste não reabre a conexão antes de conferir
def test_fixture_fechou_a_conexao_do_teste_anterior():
    assert connections['app'].connection is None
