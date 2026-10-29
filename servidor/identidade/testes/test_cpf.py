"""A1 (R1): CPF normalizado, validado, buscável sem expor o CPF."""

import pytest
from django.core.exceptions import ValidationError

from identidade import cpf

VALIDO = '12345678909'


@pytest.mark.parametrize('entrada', ['123.456.789-09', '12345678909', ' 123.456.789-09 '])
def test_normaliza_para_onze_digitos(entrada):
    assert cpf.normalizar_cpf(entrada) == VALIDO


@pytest.mark.parametrize('entrada', ['111.111.111-11', '12345678900', '1234567890', '123456789012', 'abcdefghijk', ''])
def test_recusa_cpf_invalido(entrada):
    with pytest.raises(ValidationError) as erro:
        cpf.normalizar_cpf(entrada)
    assert erro.value.code == 'cpf_invalido'


@pytest.mark.parametrize('entrada', ['١٢٣٤٥٦٧٨٩٠٩', '0٠0٠0٠0٠0٠0'])
def test_recusa_digitos_que_nao_sao_ascii(entrada):
    # Achado do Codex (PR #9): `\d` e `int()` aceitam dígitos Unicode; o mesmo CPF geraria HMACs diferentes.
    with pytest.raises(ValidationError) as erro:
        cpf.normalizar_cpf(entrada)
    assert erro.value.code == 'cpf_invalido'


def test_entrada_que_nao_e_texto_e_recusada_sem_excecao_inesperada():
    # Achado do Qodo (PR #9): `None.strip()` levantava AttributeError e derrubava o login.
    with pytest.raises(ValidationError) as erro:
        cpf.normalizar_cpf(None)
    assert erro.value.code == 'cpf_invalido'


def test_primeiro_digito_verificador_errado_e_recusado():
    # 12345678919: o primeiro dígito deveria ser 0; o segundo, recalculado, também não fecha.
    with pytest.raises(ValidationError):
        cpf.normalizar_cpf('12345678919')


def test_busca_e_estavel_e_nao_contem_o_cpf():
    primeira, segunda = cpf.chave_de_busca(VALIDO), cpf.chave_de_busca(VALIDO)
    assert primeira == segunda
    assert cpf.chave_de_busca(VALIDO) != cpf.chave_de_busca('52998224725')
    assert VALIDO not in cpf.chave_de_busca(VALIDO)
    assert len(cpf.chave_de_busca(VALIDO)) == 64


def test_cifra_ida_e_volta_e_nao_contem_o_cpf():
    cifrado = cpf.cifrar(VALIDO)
    assert VALIDO not in cifrado
    assert cpf.decifrar(cifrado) == VALIDO
    # Fernet inclui nonce: duas cifras do mesmo CPF diferem.
    assert cpf.cifrar(VALIDO) != cifrado


def test_subchaves_de_busca_e_de_cifra_sao_distintas():
    assert cpf._subchave(b'phati/cpf/busca') != cpf._subchave(b'phati/cpf/cifra')
