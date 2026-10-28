"""A14 (R15): sessão de navegador e acesso rotativo do aplicativo, nas funções de serviço.

Os atributos do cookie na resposta HTTP fecham na Fase 5; aqui vale a configuração.
"""

from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory
from django.utils import timezone

from identidade import senha, sessao
from identidade.models import AcessoAplicativo
from identidade.testes.conftest import SENHA

pytestmark = pytest.mark.django_db


def _requisicao():
    requisicao = RequestFactory().get('/')
    requisicao.session = SessionStore()
    return requisicao


def _agora_em(monkeypatch, instante):
    monkeypatch.setattr(timezone, 'now', lambda: instante)


def test_cookie_de_sessao_tem_httponly_secure_e_samesite_lax():
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SECURE is True
    assert settings.SESSION_COOKIE_SAMESITE == 'Lax'


def test_trocar_a_senha_derruba_a_sessao_aberta(pessoa):
    requisicao = _requisicao()
    sessao.iniciar_sessao(requisicao, pessoa)
    assert get_user(requisicao) == pessoa
    senha.trocar_senha(pessoa, SENHA, 'outra-senha-bem-longa')
    assert not get_user(requisicao).is_authenticated


def test_sessao_ociosa_por_30_min_cai(pessoa, monkeypatch):
    t0 = timezone.now()
    _agora_em(monkeypatch, t0)
    requisicao = _requisicao()
    sessao.iniciar_sessao(requisicao, pessoa)
    _agora_em(monkeypatch, t0 + timedelta(minutes=29))
    assert sessao.sessao_vigente(requisicao)
    _agora_em(monkeypatch, t0 + timedelta(minutes=29 + 30))
    assert not sessao.sessao_vigente(requisicao)
    assert not get_user(requisicao).is_authenticated


def test_sessao_ativa_cai_ao_completar_12h(pessoa, monkeypatch):
    t0 = timezone.now()
    _agora_em(monkeypatch, t0)
    requisicao = _requisicao()
    sessao.iniciar_sessao(requisicao, pessoa)
    for minutos in range(20, 12 * 60, 20):
        _agora_em(monkeypatch, t0 + timedelta(minutes=minutos))
        assert sessao.sessao_vigente(requisicao)
    _agora_em(monkeypatch, t0 + timedelta(hours=12))
    assert not sessao.sessao_vigente(requisicao)


def test_sessao_sem_marcas_nao_e_vigente():
    assert not sessao.sessao_vigente(_requisicao())


def test_acesso_do_aplicativo_rotaciona_e_o_anterior_deixa_de_valer(pessoa):
    primeiro = sessao.emitir_acesso(pessoa, 'celular')
    renovado = sessao.renovar_acesso(primeiro)
    assert renovado is not None
    dono, segundo = renovado
    assert dono == pessoa and segundo != primeiro
    assert sessao.renovar_acesso(primeiro) is None
    assert sessao.renovar_acesso(segundo) is not None


def test_so_o_hash_do_segredo_fica_no_banco(pessoa):
    segredo = sessao.emitir_acesso(pessoa, 'celular')
    acesso = AcessoAplicativo.objects.get()
    assert acesso.hash_segredo == sessao.hash_do_segredo(segredo) != segredo
    assert AcessoAplicativo.objects.filter(hash_segredo=segredo).count() == 0


def test_segredo_inexistente_nao_renova():
    assert sessao.renovar_acesso('nunca-emitido') is None


def test_acesso_vence_em_30_dias_e_a_renovacao_nao_passa_do_teto(pessoa, monkeypatch):
    t0 = timezone.now()
    _agora_em(monkeypatch, t0)
    segredo = sessao.emitir_acesso(pessoa, 'celular')
    _agora_em(monkeypatch, t0 + timedelta(days=29))
    renovado = sessao.renovar_acesso(segredo)
    assert renovado is not None
    assert AcessoAplicativo.objects.get(revogado_em__isnull=True).expira_em == t0 + timedelta(days=30)
    _agora_em(monkeypatch, t0 + timedelta(days=30, seconds=1))
    assert sessao.renovar_acesso(renovado[1]) is None


def test_acesso_revogado_nao_renova(pessoa):
    segredo = sessao.emitir_acesso(pessoa, 'celular')
    sessao.revogar_acessos(pessoa)
    assert sessao.renovar_acesso(segredo) is None
