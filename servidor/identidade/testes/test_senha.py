"""A3, A4 (R3, R4): validação da senha, Argon2id, senha temporária de uso único."""

import logging
import re
import threading
from datetime import timedelta
from pathlib import Path

import pytest
from django.contrib.auth.hashers import identify_hasher
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from identidade import senha
from identidade.models import AcessoAplicativo, Pessoa
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
    assert isinstance(identify_hasher(pessoa.password), senha.GeradorHashArgon2)


def test_senha_temporaria_tem_16_simbolos_do_alfabeto_de_32(pessoa):
    assert len(set(senha.ALFABETO_TEMPORARIA)) == 32
    temporaria = senha.emitir_senha_temporaria(pessoa)
    assert len(temporaria) == 16
    assert set(temporaria) <= set(senha.ALFABETO_TEMPORARIA)


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
    assert len(mailoutbox) == 1
    assert temporaria in mailoutbox[0].body
    assert mailoutbox[0].to == [pessoa.email]


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
    assert pessoa.check_password('outra-senha-bem-longa')
    assert not pessoa.deve_trocar_senha
    assert len(mailoutbox) == 1


def test_trocar_senha_revoga_os_acessos_do_aplicativo(pessoa):
    segredo = emitir_acesso(pessoa, 'celular')
    senha.trocar_senha(pessoa, SENHA, 'outra-senha-bem-longa')
    assert renovar_acesso(segredo) is None


def test_falha_do_smtp_nao_desfaz_a_senha_temporaria_que_volta_a_quem_criou(pessoa, monkeypatch):
    # Achado do Qodo (PR #9) tratado em T5.5a 4 e 5: a senha temporária volta ao Administrador que a emitiu,
    # então a falha do e-mail (pós-commit, só log) não deixa a pessoa sem acesso.
    def falha(*_):
        raise OSError('smtp fora')

    monkeypatch.setattr(senha.email.EmailMessage, 'send', falha)
    temporaria = senha.emitir_senha_temporaria(pessoa)
    pessoa.refresh_from_db()
    assert pessoa.check_password(temporaria)
    assert pessoa.deve_trocar_senha


def test_troca_e_emissao_travam_a_pessoa(pessoa):
    # Achado do Qodo (PR #9): conferir a senha atual e gravar a nova sem trava deixava duas trocas passarem.
    with CaptureQueriesContext(connection) as consultas:
        senha.trocar_senha(pessoa, SENHA, 'outra-senha-bem-longa')
        senha.emitir_senha_temporaria(pessoa)
    travas = [c for c in consultas if 'FOR UPDATE' in c['sql'] and '"pessoa"' in c['sql']]
    assert len(travas) >= 3


def test_definir_senha_nao_sobrescreve_campos_alheios(pessoa):
    # A gravação é por `update_fields`: o que outra transação mudou na pessoa (nome) sobrevive.
    Pessoa.objects.filter(pk=pessoa.pk).update(nome='Maria Nova')
    pessoa.nome = 'Maria da Silva'
    senha.definir_senha(pessoa, 'outra-senha-bem-longa')
    assert Pessoa.objects.get(pk=pessoa.pk).nome == 'Maria Nova'


@pytest.mark.django_db(transaction=True)
def test_duas_trocas_com_a_mesma_senha_atual_so_uma_vale(pessoa):
    # Achado do Qodo (PR #9): sem a trava, as duas passavam e a última gravação apagava a primeira.
    resultados = []
    largada = threading.Barrier(2)

    def trocar(nova):
        largada.wait()
        try:
            senha.trocar_senha(Pessoa.objects.get(pk=pessoa.pk), SENHA, nova)
            resultados.append('ok')
        except ValidationError as erro:
            resultados.append(erro.code)
        finally:
            connection.close()

    fios = [threading.Thread(target=trocar, args=(nova,)) for nova in ('primeira-senha-bem-longa', 'segunda-senha-bem-longa')]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join()
    assert sorted(resultados) == ['ok', 'senha_atual_incorreta']


@pytest.mark.django_db(transaction=True)
def test_troca_de_senha_e_renovacao_de_acesso_nao_deixam_acesso_vivo(pessoa):
    # Achados do Greptile, Qodo e Sourcery (PR #9): a renovação concorrente não pode criar acesso por fora da revogação.
    segredo = emitir_acesso(pessoa, 'celular')
    novos = []
    largada = threading.Barrier(2)

    def renovar():
        largada.wait()
        try:
            novos.append(renovar_acesso(segredo))
        finally:
            connection.close()

    def trocar():
        largada.wait()
        try:
            senha.trocar_senha(Pessoa.objects.get(pk=pessoa.pk), SENHA, 'outra-senha-bem-longa')
        finally:
            connection.close()

    fios = [threading.Thread(target=f) for f in (renovar, trocar)]
    for fio in fios:
        fio.start()
    for fio in fios:
        fio.join()
    assert AcessoAplicativo.objects.filter(pessoa=pessoa, revogado_em__isnull=True).count() == 0
