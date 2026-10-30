"""R20 (T1.0): o CPF sintético é válido, único e aceito pela validação do produto."""

from comum.sintetico import cpf_sintetico
from identidade.cpf import normalizar_cpf


def test_cpf_sintetico_e_aceito_por_normalizar_cpf():
    assert normalizar_cpf(cpf_sintetico(1)) == cpf_sintetico(1)


def test_cpf_sintetico_e_unico_em_mil_chamadas():
    cpfs = [cpf_sintetico(numero) for numero in range(1, 1001)]
    assert len(set(cpfs)) == 1000
    assert all(normalizar_cpf(cpf) == cpf for cpf in cpfs)


def test_cpf_sintetico_com_a_mesma_sequencia_repete_o_valor():
    assert cpf_sintetico(7) == cpf_sintetico(7)
