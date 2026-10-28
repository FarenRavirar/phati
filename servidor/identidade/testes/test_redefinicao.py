"""A5, A14 (R5, R15): redefinição de senha por link.

O ramo do Administrador de empresa (origem ou concessão ativa) fecha na Fase 3 (T3.4a): depende de cargo e concessão.
"""

import re
from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user
from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import ValidationError
from django.test import RequestFactory
from django.utils import timezone

from identidade import login, redefinicao, sessao
from identidade.models import PedidoRedefinicao, Pessoa
from identidade.testes.conftest import CPF, SENHA

pytestmark = pytest.mark.django_db

NOVA = 'senha-nova-bem-comprida-1'


def _segredo(mailoutbox):
    achado = re.search(r'segredo=(\S+)', mailoutbox[-1].body)
    assert achado is not None
    return achado.group(1)


def _agora_em(monkeypatch, instante):
    monkeypatch.setattr(timezone, 'now', lambda: instante)


@pytest.fixture
def outra_pessoa(db):
    return Pessoa.objects.criar(nome='Joana Souza', email='joana@exemplo.test', cpf='529.982.247-25')


def test_a_propria_pessoa_pede_e_recebe_o_link_montado_com_url_base(pessoa, mailoutbox):
    assert redefinicao.pedir_redefinicao(CPF) is None
    pedido = PedidoRedefinicao.objects.get()
    assert pedido.pessoa == pedido.solicitado_por == pessoa
    assert mailoutbox[0].to == [pessoa.email]
    assert f'{settings.URL_BASE}/redefinir-senha?segredo=' in mailoutbox[0].body
    segredo = _segredo(mailoutbox)
    assert pedido.hash_segredo == sessao.hash_do_segredo(segredo) != segredo


def test_resposta_e_neutra_para_cpf_inexistente_invalido_e_existente(pessoa, mailoutbox):
    resultados = {repr(redefinicao.pedir_redefinicao(c)) for c in (CPF, '999.999.999-99', 'lixo')}
    assert resultados == {'None'}
    assert len(mailoutbox) == 1 and PedidoRedefinicao.objects.count() == 1


def test_tecnico_nao_pede_a_redefinicao_de_outra_pessoa(pessoa, outra_pessoa, mailoutbox):
    redefinicao.pedir_redefinicao(CPF, solicitante=outra_pessoa)
    assert PedidoRedefinicao.objects.count() == 0 and mailoutbox == []


def test_administrador_da_plataforma_inicia_e_fica_registrado(pessoa, outra_pessoa, mailoutbox):
    outra_pessoa.administrador_plataforma = True
    outra_pessoa.save()
    redefinicao.pedir_redefinicao(CPF, solicitante=outra_pessoa)
    pedido = PedidoRedefinicao.objects.get()
    assert pedido.pessoa == pessoa and pedido.solicitado_por == outra_pessoa
    assert len(mailoutbox) == 1 and mailoutbox[0].to == [pessoa.email]


def test_pedido_nao_conta_falha_nem_bloqueia(pessoa):
    pessoa.falhas_consecutivas = 2
    pessoa.save()
    for _ in range(10):
        redefinicao.pedir_redefinicao(CPF)
    pessoa.refresh_from_db()
    assert pessoa.falhas_consecutivas == 2 and pessoa.bloqueada_ate is None


def test_pedido_novo_invalida_o_anterior(pessoa, mailoutbox):
    redefinicao.pedir_redefinicao(CPF)
    antigo = _segredo(mailoutbox)
    redefinicao.pedir_redefinicao(CPF)
    with pytest.raises(ValidationError) as erro:
        redefinicao.confirmar_redefinicao(antigo, NOVA)
    assert erro.value.code == 'link_invalido'


def test_confirmar_troca_a_senha_uma_vez_e_nao_abre_sessao(pessoa, mailoutbox):
    redefinicao.pedir_redefinicao(CPF)
    segredo = _segredo(mailoutbox)
    assert redefinicao.confirmar_redefinicao(segredo, NOVA) is None
    assert login.autenticar(CPF, NOVA) == pessoa and login.autenticar(CPF, SENHA) is None
    assert len(mailoutbox) == 2 and 'alterada' in mailoutbox[1].body
    with pytest.raises(ValidationError) as erro:
        redefinicao.confirmar_redefinicao(segredo, NOVA)
    assert erro.value.code == 'link_invalido'


def test_link_vence_aos_10_minutos(pessoa, mailoutbox, monkeypatch):
    t0 = timezone.now()
    _agora_em(monkeypatch, t0)
    redefinicao.pedir_redefinicao(CPF)
    segredo = _segredo(mailoutbox)
    _agora_em(monkeypatch, t0 + timedelta(minutes=10))
    with pytest.raises(ValidationError) as erro:
        redefinicao.confirmar_redefinicao(segredo, NOVA)
    assert erro.value.code == 'link_invalido'
    _agora_em(monkeypatch, t0 + timedelta(minutes=9, seconds=59))
    redefinicao.confirmar_redefinicao(segredo, NOVA)


def test_segredo_de_um_pedido_nao_vale_para_outra_pessoa(pessoa, outra_pessoa, mailoutbox):
    redefinicao.pedir_redefinicao('529.982.247-25')
    segredo_da_joana = _segredo(mailoutbox)
    redefinicao.confirmar_redefinicao(segredo_da_joana, NOVA)
    pessoa.refresh_from_db()
    assert pessoa.check_password(SENHA) and not pessoa.check_password(NOVA)
    with pytest.raises(ValidationError):
        redefinicao.confirmar_redefinicao('segredo-inventado', NOVA)


def test_cinco_tentativas_por_pedido(pessoa, mailoutbox):
    redefinicao.pedir_redefinicao(CPF)
    segredo = _segredo(mailoutbox)
    for _ in range(5):
        with pytest.raises(ValidationError) as erro:
            redefinicao.confirmar_redefinicao(segredo, 'curta')
        assert erro.value.code == 'senha_curta'
    with pytest.raises(ValidationError) as erro:
        redefinicao.confirmar_redefinicao(segredo, NOVA)
    assert erro.value.code == 'link_invalido'
    pessoa.refresh_from_db()
    assert pessoa.check_password(SENHA)


def test_redefinicao_derruba_sessao_aberta_e_acesso_do_aplicativo(pessoa, mailoutbox):
    requisicao = RequestFactory().get('/')
    requisicao.session = SessionStore()
    sessao.iniciar_sessao(requisicao, pessoa)
    acesso = sessao.emitir_acesso(pessoa, 'celular')
    redefinicao.pedir_redefinicao(CPF)
    redefinicao.confirmar_redefinicao(_segredo(mailoutbox), NOVA)
    assert not get_user(requisicao).is_authenticated
    assert sessao.renovar_acesso(acesso) is None


def test_redefinicao_encerra_bloqueio_e_troca_obrigatoria(pessoa, mailoutbox):
    pessoa.falhas_consecutivas = 7
    pessoa.bloqueada_ate = timezone.now() + timedelta(minutes=5)
    pessoa.deve_trocar_senha = True
    pessoa.save()
    redefinicao.pedir_redefinicao(CPF)
    redefinicao.confirmar_redefinicao(_segredo(mailoutbox), NOVA)
    pessoa.refresh_from_db()
    assert (pessoa.falhas_consecutivas, pessoa.bloqueada_ate, pessoa.deve_trocar_senha) == (0, None, False)
