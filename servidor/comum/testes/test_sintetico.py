"""R20 (T1.0): o CPF sintético é válido, único e aceito pela validação do produto."""

import pytest

from comum.sintetico import cpf_sintetico
from identidade.cpf import normalizar_cpf


def test_cpf_sintetico_e_aceito_por_normalizar_cpf():
    assert normalizar_cpf(cpf_sintetico(1)) == cpf_sintetico(1)


def test_cpf_sintetico_e_unico_em_mil_chamadas():
    cpfs = [cpf_sintetico(numero) for numero in range(1, 1001)]
    assert len(set(cpfs)) == 1000
    assert all(normalizar_cpf(cpf) == cpf for cpf in cpfs)


def test_cpf_sintetico_e_deterministico():
    assert cpf_sintetico(7) == '91358024723'  # valor fixo: mudar a fórmula quebra seeds já gerados


@pytest.mark.parametrize('sequencia', [0, 10**9, 999999991, 999999919])
def test_cpf_sintetico_recusa_sequencia_fora_da_faixa_ou_de_digitos_repetidos(sequencia):
    with pytest.raises(ValueError):
        cpf_sintetico(sequencia)


def test_cpf_sintetico_aceita_o_limite_superior_da_faixa():
    assert normalizar_cpf(cpf_sintetico(10**9 - 2)) == cpf_sintetico(10**9 - 2)
