"""R4, A1: `acesso.entrar` é o corpo único da entrada, chamado pela API e pela tela."""

import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory

from identidade import acesso, senha, sessao
from identidade.models import Pessoa
from identidade.testes.conftest import CPF, CPF_LIMPO, SENHA

pytestmark = pytest.mark.django_db


def _requisicao():
    requisicao = RequestFactory().post('/entrar')
    requisicao.session = SessionStore()
    return requisicao


def test_cpf_certo_abre_a_sessao_e_pede_o_cookie_csrf(pessoa):
    requisicao = _requisicao()
    assert acesso.entrar(requisicao, CPF, SENHA) == (pessoa, None)
    assert requisicao.session['_auth_user_id'] == str(pessoa.pk)
    assert requisicao.META['CSRF_COOKIE_NEEDS_UPDATE']  # `get_token` marca o cookie para a resposta


def test_cpf_com_e_sem_pontuacao_entram_na_mesma_pessoa(pessoa):
    com_pontos, sem_pontos = acesso.entrar(_requisicao(), CPF, SENHA), acesso.entrar(_requisicao(), CPF_LIMPO, SENHA)
    assert com_pontos == sem_pontos == (pessoa, None)


def test_com_dispositivo_emite_o_acesso_do_aplicativo_e_nao_abre_sessao(pessoa):
    requisicao = _requisicao()
    entrada = acesso.entrar(requisicao, CPF, SENHA, 'celular')
    assert entrada is not None
    assert entrada[0] == pessoa
    assert entrada[1]
    assert '_auth_user_id' not in requisicao.session
    assert 'CSRF_COOKIE_NEEDS_UPDATE' not in requisicao.META


@pytest.mark.parametrize('cpf', ['529.982.247-25', '111.111.111-11', 'lixo', ''])
def test_cpf_inexistente_ou_de_digito_invalido_devolve_none(pessoa, cpf):
    requisicao = _requisicao()
    assert acesso.entrar(requisicao, cpf, SENHA) is None
    assert '_auth_user_id' not in requisicao.session


def test_senha_errada_devolve_none_e_sem_sessao(pessoa):
    requisicao = _requisicao()
    assert acesso.entrar(requisicao, CPF, 'errada-errada-errada') is None
    assert '_auth_user_id' not in requisicao.session


def test_conta_bloqueada_devolve_none_mesmo_com_a_senha_certa(pessoa):
    for _ in range(5):
        acesso.entrar(_requisicao(), CPF, 'errada-errada-errada')
    assert acesso.entrar(_requisicao(), CPF, SENHA) is None


def test_senha_temporaria_consumida_nao_se_perde_se_a_sessao_nao_abre(pessoa, monkeypatch):
    temporaria = senha.emitir_senha_temporaria(pessoa)

    def falhar(requisicao, quem):
        raise RuntimeError('sessão indisponível')

    monkeypatch.setattr(sessao, 'iniciar_sessao', falhar)
    with pytest.raises(RuntimeError):
        acesso.entrar(_requisicao(), CPF, temporaria)
    monkeypatch.undo()
    assert acesso.entrar(_requisicao(), CPF, temporaria) == (Pessoa.objects.get(pk=pessoa.pk), None)
