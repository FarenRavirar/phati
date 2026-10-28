"""A3, A4 (R3, R4): validação da senha, Argon2id, senha temporária de uso único."""

import logging
import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.contrib.auth.hashers import identify_hasher
from django.core.exceptions import ValidationError
from django.utils import timezone

from identidade import senha
from identidade.models import Pessoa
from identidade.sessao import emitir_acesso, renovar_acesso
from identidade.testes.conftest import CPF_LIMPO, SENHA

# Entradas literais da lista de comuns do Django com 15+ caracteres: só a regra da lista pode recusá-las.
COMUNS = ['1q2w3e4r5t6y7u8i9o0p', '123456789123456789']


def _codigo(texto, pessoa=None, cpf=None):
    with pytest.raises(ValidationError) as erro:
        senha.validar_senha(texto, pessoa, cpf)
    return erro.value.code


def test_quatorze_recusa_quinze_aceita():
    assert _codigo('Qz9!kd-Wm4xTr2') == 'senha_curta'  # 14
    senha.validar_senha('Qz9!kd-Wm4xTr2a')  # 15


@pytest.mark.parametrize('tamanho', [64, 65, 128])
def test_aceita_ate_128(tamanho):
    senha.validar_senha(('Qz9!kd-Wm4' * 13)[:tamanho])


def test_recusa_acima_de_128_sem_truncar():
    assert _codigo('Qz9!kd-Wm4' * 13 + 'x') == 'senha_longa'  # 131


@pytest.mark.parametrize('comum', COMUNS)
def test_recusa_senha_da_lista_de_comuns(comum):
    assert _codigo(comum) == 'senha_comum'


def test_recusa_palavras_do_contexto(pessoa):
    assert _codigo('zz' + CPF_LIMPO + 'zzzz', pessoa, CPF_LIMPO) == 'senha_contexto'
    assert _codigo('zz123.456.789-09zzzz', pessoa, CPF_LIMPO) == 'senha_contexto'
    assert _codigo('minha-PHATI-secreta-1', pessoa, CPF_LIMPO) == 'senha_contexto'
    assert _codigo('a-Maria-quer-cafe-1', pessoa, CPF_LIMPO) == 'senha_contexto'
    assert _codigo('a-SILVA-quer-cafe-12', pessoa, CPF_LIMPO) == 'senha_contexto'


def test_aceita_unicode_e_espaco():
    senha.validar_senha('água com açúcar e café!')


def test_validador_nao_faz_chamada_de_rede():
    fonte = Path(senha.__file__).read_text(encoding='utf-8')
    assert not re.search(r'\b(requests|urllib|http\.client|socket|httpx|aiohttp)\b', fonte)


def test_hash_e_argon2id_com_os_parametros_do_owasp(pessoa):
    assert pessoa.password.startswith('argon2$argon2id$')
    assert 'm=19456,t=2,p=1' in pessoa.password
    assert isinstance(identify_hasher(pessoa.password), senha.HasherArgon2)


def test_senha_temporaria_tem_16_simbolos_do_alfabeto_de_32(pessoa):
    assert len(set(senha.ALFABETO_TEMPORARIA)) == 32
    temporaria = senha.emitir_senha_temporaria(pessoa)
    assert len(temporaria) == 16 and set(temporaria) <= set(senha.ALFABETO_TEMPORARIA)


def test_senha_temporaria_vale_72h_exige_troca_e_so_o_hash_fica(pessoa, mailoutbox, caplog):
    caplog.set_level(logging.DEBUG)
    antes = timezone.now()
    temporaria = senha.emitir_senha_temporaria(pessoa)
    pessoa.refresh_from_db()
    assert pessoa.deve_trocar_senha
    assert timedelta(hours=72) <= pessoa.senha_temporaria_ate - antes < timedelta(hours=72, seconds=5)
    assert pessoa.check_password(temporaria)
    assert Pessoa.objects.filter(password__contains=temporaria).count() == 0
    assert temporaria not in caplog.text
    assert len(mailoutbox) == 1 and temporaria in mailoutbox[0].body and mailoutbox[0].to == [pessoa.email]


def test_trocar_senha_exige_a_atual_valida_a_nova_e_avisa(pessoa, mailoutbox):
    with pytest.raises(ValidationError) as erro:
        senha.trocar_senha(pessoa, 'errada-errada-errada', 'outra-senha-bem-longa')
    assert erro.value.code == 'senha_atual_incorreta'
    with pytest.raises(ValidationError) as erro:
        senha.trocar_senha(pessoa, SENHA, 'curta')
    assert erro.value.code == 'senha_curta'
    assert mailoutbox == []
    senha.trocar_senha(pessoa, SENHA, 'outra-senha-bem-longa')
    pessoa.refresh_from_db()
    assert pessoa.check_password('outra-senha-bem-longa') and not pessoa.deve_trocar_senha
    assert len(mailoutbox) == 1


def test_trocar_senha_revoga_os_acessos_do_aplicativo(pessoa):
    segredo = emitir_acesso(pessoa, 'celular')
    senha.trocar_senha(pessoa, SENHA, 'outra-senha-bem-longa')
    assert renovar_acesso(segredo) is None
