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


def test_fixture_do_painel_aberto_tira_so_a_trava_de_plataforma(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel, painel_aberto_a_gestores):
    # A fixture existe para os testes dos admins por escopo (R21): quem gere a empresa passa a abrir o painel só aqui.
    administrador = fabrica_pessoa('Gestor')
    conceder_direto(administrador, cenario.cargos_x['administrador'], cenario.x)
    assert entrar_no_painel(administrador).get('/painel/').status_code == 200
    tecnico = fabrica_pessoa('Tecnico')
    conceder_direto(tecnico, cenario.cargos_x['tecnico'], cenario.f1)
    assert entrar_no_painel(tecnico).get('/painel/').status_code == 302  # a trava de ação de gestão segue valendo
