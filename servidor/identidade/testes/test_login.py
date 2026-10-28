"""A2, A4 (R2, R4): login por CPF, bloqueio por conta, senha temporária de uso único."""

import statistics
import time
from datetime import timedelta

import pytest
from django.utils import timezone

from identidade import login, senha
from identidade.models import Pessoa
from identidade.testes.conftest import CPF, CPF_LIMPO, SENHA

pytestmark = pytest.mark.django_db

ERRADA = 'errada-errada-errada'


def _agora_em(monkeypatch, instante):
    monkeypatch.setattr(timezone, 'now', lambda: instante)


def test_senha_certa_autentica_com_ou_sem_pontuacao(pessoa):
    assert login.autenticar(CPF, SENHA) == pessoa
    assert login.autenticar(CPF_LIMPO, SENHA) == pessoa


@pytest.mark.parametrize('cpf', ['999.999.999-99', '111.111.111-11', 'lixo', ''])
def test_cpf_inexistente_ou_invalido_nega(pessoa, cpf):
    assert login.autenticar(cpf, SENHA) is None


def test_senha_errada_nega_e_conta_falha(pessoa):
    assert login.autenticar(CPF, ERRADA) is None
    pessoa.refresh_from_db()
    assert pessoa.falhas_consecutivas == 1


def test_tempo_de_cpf_inexistente_e_de_senha_errada_se_parece(pessoa):
    # R-8: mediana de 15 rodadas e razão com folga. Sem o hash falso, o inexistente cairia a ~0 (razão << 0,5).
    def mediana(cpf):
        medidas = []
        for _ in range(15):
            inicio = time.perf_counter()
            login.autenticar(cpf, ERRADA)
            medidas.append(time.perf_counter() - inicio)
            pessoa.falhas_consecutivas = 0
            pessoa.bloqueada_ate = None
            pessoa.save()
        return statistics.median(medidas)

    inexistente, errada = mediana('999.999.999-99'), mediana(CPF)
    assert min(inexistente, errada) / max(inexistente, errada) > 0.5


@pytest.mark.parametrize(('falhas', 'segundos'), [(5, 30), (6, 60), (7, 120), (9, 480), (10, 900), (20, 900)])
def test_bloqueio_dobra_ate_o_teto(falhas, segundos):
    assert login._bloqueio_em_segundos(falhas) == segundos


def test_cinco_falhas_bloqueiam_ate_a_senha_certa_e_so_libera_depois(pessoa, monkeypatch):
    t0 = timezone.now()
    _agora_em(monkeypatch, t0)
    for _ in range(5):
        assert login.autenticar(CPF, ERRADA) is None
    pessoa.refresh_from_db()
    assert pessoa.bloqueada_ate == t0 + timedelta(seconds=30)
    _agora_em(monkeypatch, t0 + timedelta(seconds=29))
    assert login.autenticar(CPF, SENHA) is None
    assert login.autenticar(CPF, ERRADA) is None  # durante o bloqueio não conta nem prolonga
    pessoa.refresh_from_db()
    assert pessoa.falhas_consecutivas == 5 and pessoa.bloqueada_ate == t0 + timedelta(seconds=30)
    _agora_em(monkeypatch, t0 + timedelta(seconds=31))
    assert login.autenticar(CPF, SENHA) == pessoa
    pessoa.refresh_from_db()
    assert pessoa.falhas_consecutivas == 0 and pessoa.bloqueada_ate is None


def test_falha_apos_o_bloqueio_dobra_a_duracao(pessoa, monkeypatch):
    t0 = timezone.now()
    _agora_em(monkeypatch, t0)
    for _ in range(5):
        login.autenticar(CPF, ERRADA)
    _agora_em(monkeypatch, t0 + timedelta(seconds=31))
    login.autenticar(CPF, ERRADA)
    pessoa.refresh_from_db()
    assert pessoa.bloqueada_ate == t0 + timedelta(seconds=31 + 60)


def test_bloqueio_e_da_conta_e_nao_afeta_outra_pessoa(pessoa):
    outra = Pessoa.objects.criar(nome='Joana Souza', email='j@exemplo.test', cpf='529.982.247-25')
    outra.set_password(SENHA)
    outra.save()
    for _ in range(5):
        login.autenticar(CPF, ERRADA)
    assert login.autenticar('529.982.247-25', SENHA) == outra


def test_senha_temporaria_funciona_uma_vez(pessoa):
    temporaria = senha.emitir_senha_temporaria(pessoa)
    entrou = login.autenticar(CPF, temporaria)
    assert entrou == pessoa and entrou is not None and entrou.deve_trocar_senha
    assert login.autenticar(CPF, temporaria) is None


def test_senha_temporaria_vence_em_72h(pessoa, monkeypatch):
    t0 = timezone.now()
    _agora_em(monkeypatch, t0)
    temporaria = senha.emitir_senha_temporaria(pessoa)
    _agora_em(monkeypatch, t0 + timedelta(hours=72, seconds=1))
    assert login.autenticar(CPF, temporaria) is None


def test_senha_temporaria_vale_perto_do_fim_do_prazo(pessoa, monkeypatch):
    t0 = timezone.now()
    _agora_em(monkeypatch, t0)
    temporaria = senha.emitir_senha_temporaria(pessoa)
    _agora_em(monkeypatch, t0 + timedelta(hours=71, minutes=59))
    assert login.autenticar(CPF, temporaria) == pessoa


def test_depois_da_troca_a_senha_nova_entra_sem_exigir_troca(pessoa):
    temporaria = senha.emitir_senha_temporaria(pessoa)
    entrou = login.autenticar(CPF, temporaria)
    senha.definir_senha(entrou, 'outra-senha-bem-longa')
    de_novo = login.autenticar(CPF, 'outra-senha-bem-longa')
    assert de_novo == pessoa and de_novo is not None and not de_novo.deve_trocar_senha
