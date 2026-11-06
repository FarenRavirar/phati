"""Janelas de uso do Google (004b R13, R14, A10): porcentagem sem divisão por zero, renovação e origem rotulada."""

from datetime import datetime, timezone

import pytest

from projeto import uso_google
from projeto.uso_google import Janela, PACIFICO

AGORA = datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)  # 12:00 no Pacífico


class FonteFixa:
    origem = 'Cloud Monitoring (teste)'

    def __init__(self, usados):
        self.usados = usados
        self.chamadas = []

    def contar(self, inicio, fim):
        self.chamadas.append((inicio, fim))
        return self.usados


def _janela(usados, total):
    return Janela('x', usados, total, AGORA, 'origem')


def test_porcentagem_com_total_zero_nao_divide_por_zero():
    assert _janela(10, 0).porcentagem is None


def test_porcentagem_com_uso_maior_que_o_total_passa_de_cem():
    assert _janela(150, 100).porcentagem == 150.0


def test_uso_zero_medido_e_diferente_de_nao_medido():
    assert _janela(0, 100).porcentagem == 0.0
    assert _janela(None, 100).porcentagem is None


def test_renovacao_diaria_e_meia_noite_do_pacifico_do_dia_seguinte():
    inicio, renovacao = uso_google.inicio_e_renovacao_diaria(AGORA)
    assert inicio == datetime(2026, 11, 6, tzinfo=PACIFICO)
    assert renovacao == datetime(2026, 11, 7, tzinfo=PACIFICO)


def test_renovacao_mensal_e_dia_um_a_meia_noite_do_pacifico():
    inicio, renovacao = uso_google.inicio_e_renovacao_mensal(AGORA)
    assert inicio == datetime(2026, 11, 1, tzinfo=PACIFICO)
    assert renovacao == datetime(2026, 12, 1, tzinfo=PACIFICO)


def test_janela_renovada_a_virada_do_mes_e_do_ano():
    # 2026-12-31 23:30 no Pacífico = 2027-01-01 07:30 UTC
    _, renovacao = uso_google.inicio_e_renovacao_mensal(datetime(2027, 1, 1, 7, 30, tzinfo=timezone.utc))
    assert renovacao == datetime(2027, 1, 1, tzinfo=PACIFICO)


def test_dia_no_pacifico_nao_e_o_dia_em_utc():
    # 2026-11-07 03:00 UTC ainda é 06/11 19:00 no Pacífico: a janela diária é a de 06/11
    inicio, _ = uso_google.inicio_e_renovacao_diaria(datetime(2026, 11, 7, 3, 0, tzinfo=timezone.utc))
    assert inicio == datetime(2026, 11, 6, tzinfo=PACIFICO)


def test_janelas_com_fonte_rotulam_a_origem_e_consultam_cada_janela():
    fonte = FonteFixa(42)
    diaria, mensal = uso_google.janelas(AGORA, 15000, 100000, fonte)
    assert (diaria.usados, diaria.total, diaria.origem) == (42, 15000, 'Cloud Monitoring (teste)')
    assert (mensal.usados, mensal.total) == (42, 100000)
    assert fonte.chamadas[0][0] == uso_google.inicio_e_renovacao_diaria(AGORA)[0]
    assert fonte.chamadas[1][0] == uso_google.inicio_e_renovacao_mensal(AGORA)[0]


def test_sem_fonte_o_uso_fica_nao_medido_e_nunca_zero():
    for janela in uso_google.janelas(AGORA, 15000, 100000, None):
        assert (janela.usados, janela.origem, janela.porcentagem) == (None, uso_google.NAO_MEDIDO, None)


def test_fonte_sem_nenhum_ponto_vira_nao_medido_e_nao_zero():
    class SemPonto:
        origem = 'Cloud Monitoring (teste)'

        def contar(self, _inicio, _fim):
            return None

    diaria, mensal = uso_google.janelas(AGORA, 15000, 100000, SemPonto())
    assert (diaria.usados, diaria.origem, diaria.porcentagem) == (None, uso_google.NAO_MEDIDO, None)
    assert (mensal.usados, mensal.origem) == (None, uso_google.NAO_MEDIDO)


def test_fonte_com_zero_medido_mostra_zero_e_a_origem():
    diaria, _ = uso_google.janelas(AGORA, 15000, 100000, FonteFixa(0))
    assert (diaria.usados, diaria.origem, diaria.porcentagem) == (0, 'Cloud Monitoring (teste)', 0.0)


def test_fonte_que_falha_vira_nao_medido_e_registra_a_causa(caplog):
    class Quebrada:
        origem = 'Cloud Monitoring (teste)'

        def contar(self, inicio, fim):
            raise TimeoutError('sem rede')

    with caplog.at_level('ERROR'):
        diaria, _ = uso_google.janelas(AGORA, 15000, 100000, Quebrada())
    assert (diaria.usados, diaria.origem) == (None, uso_google.NAO_MEDIDO)
    assert 'sem rede' in caplog.text


@pytest.mark.parametrize('total', [0, 1])
def test_janelas_aceitam_total_pequeno(total):
    diaria, mensal = uso_google.janelas(AGORA, total, total, FonteFixa(5))
    assert (diaria.total, mensal.total) == (total, total)
    assert (diaria.usados, mensal.usados) == (5, 5)
