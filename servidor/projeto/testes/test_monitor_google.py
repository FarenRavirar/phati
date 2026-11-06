"""Tela do monitor do Google (004b R13, R14, A10): só o Administrador da plataforma; o resto recebe 404 por URL direta."""

import pytest
from django.test import Client

from projeto import monitor_google
from projeto.monitoramento_google import CloudMonitoring

CAMINHO = '/monitor-google'


class FonteFixa:
    origem = 'Cloud Monitoring (teste)'

    def contar(self, inicio, fim):
        return 4321


@pytest.fixture
def plataforma_logada(conta):
    conta.pessoa.administrador_plataforma = True
    conta.pessoa.save(update_fields=['administrador_plataforma'])
    return conta


def test_deslogado_e_levado_a_entrada():
    resposta = Client().get(CAMINHO)
    assert resposta.status_code == 302
    assert resposta['Location'].startswith('/entrar')


def test_pessoa_sem_concessao_recebe_404(cliente_logado):
    assert cliente_logado.get(CAMINHO).status_code == 404


def test_administrador_de_empresa_curador_tecnico_e_usuario_recebem_404(cliente_logado, conta, cenario, conceder_direto):
    for base in ('administrador', 'curador', 'tecnico', 'usuario'):
        concessao = conceder_direto(conta.pessoa, cenario.cargos_x[base], cenario.x)
        assert (base, cliente_logado.get(CAMINHO).status_code) == (base, 404)
        concessao.delete()


def test_so_get(cliente_logado, plataforma_logada):
    assert cliente_logado.post(CAMINHO).status_code == 405


def test_plataforma_sem_fonte_ve_nao_medido_nas_duas_janelas(cliente_logado, plataforma_logada):
    resposta = cliente_logado.get(CAMINHO)
    html = resposta.content.decode()
    assert resposta.status_code == 200
    assert 'Diária (cota do projeto)' in html
    assert 'Mensal (franquia grátis)' in html
    assert html.count('não medido') >= 6  # usados, porcentagem e origem, nas duas janelas
    assert '15.000' in html
    assert '100.000' in html
    assert 'Pacífico' in html
    assert 'no-store' in resposta['Cache-Control']


def test_plataforma_com_fonte_ve_usados_porcentagem_e_origem(cliente_logado, plataforma_logada, monkeypatch):
    monkeypatch.setattr(monitor_google, '_fonte', lambda: FonteFixa())
    html = cliente_logado.get(CAMINHO).content.decode()
    assert '4.321' in html
    assert '28,8%' in html  # 4321 / 15000
    assert '4,3%' in html  # 4321 / 100000
    assert 'Cloud Monitoring (teste)' in html


def test_total_zero_nao_quebra_a_tela(cliente_logado, plataforma_logada, monkeypatch, settings):
    settings.MAPA_GOOGLE_COTA_DIARIA = 0
    monkeypatch.setattr(monitor_google, '_fonte', lambda: FonteFixa())
    assert cliente_logado.get(CAMINHO).status_code == 200


def test_fonte_so_existe_com_credencial_configurada(settings):
    settings.GOOGLE_MONITORING_CREDENCIAL = ''
    assert monitor_google._fonte() is None
    settings.GOOGLE_MONITORING_CREDENCIAL = '/nao/existe.json'
    assert isinstance(monitor_google._fonte(), CloudMonitoring)


def test_credencial_ilegivel_mostra_nao_medido_e_nao_derruba_a_tela(cliente_logado, plataforma_logada, settings):
    settings.GOOGLE_MONITORING_CREDENCIAL = '/nao/existe.json'
    resposta = cliente_logado.get(CAMINHO)
    assert resposta.status_code == 200
    assert resposta.content.decode().count('não medido') >= 6


def test_fonte_repassa_o_projeto_monitorado_so_quando_configurado(settings):
    settings.GOOGLE_MONITORING_CREDENCIAL = '/nao/existe.json'
    settings.GOOGLE_PROJETO_MONITORADO = ''
    sem_projeto = monitor_google._fonte()
    assert sem_projeto is not None
    assert sem_projeto._projeto is None
    settings.GOOGLE_PROJETO_MONITORADO = 'projeto-cobrado'
    com_projeto = monitor_google._fonte()
    assert com_projeto is not None
    assert com_projeto._projeto == 'projeto-cobrado'
