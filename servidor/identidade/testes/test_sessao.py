"""A14 (R15): sessão de navegador e acesso rotativo do aplicativo, nas funções de serviço.

Os atributos do cookie na resposta HTTP fecham na Fase 5; aqui vale a configuração.
"""

from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user
from django.contrib.sessions.backends.db import SessionStore
from django.db import connection
from django.test.utils import CaptureQueriesContext
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


def test_acesso_do_aplicativo_rotaciona_e_o_anterior_deixa_de_autenticar(pessoa):
    primeiro = sessao.emitir_acesso(pessoa, 'celular')
    renovado = sessao.renovar_acesso(primeiro)
    assert renovado is not None
    dono, segundo = renovado
    assert dono == pessoa
    assert segundo != primeiro
    assert sessao.pessoa_do_acesso(primeiro) is None
    assert sessao.pessoa_do_acesso(segundo) is not None
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


def test_emissao_trava_a_pessoa_para_a_troca_de_senha_nao_deixar_acesso_vivo(pessoa):
    # Achado do Qodo (PR #9): acesso criado durante a troca de senha escapava da revogação.
    with CaptureQueriesContext(connection) as consultas:
        sessao.emitir_acesso(pessoa, 'celular')
    assert any('FOR UPDATE' in c['sql'] and '"pessoa"' in c['sql'] for c in consultas)


def test_renovacao_trava_a_pessoa_antes_do_acesso(pessoa):
    # Achado do Greptile (PR #9): mesma ordem de travas da troca de senha (pessoa, depois acessos).
    segredo = sessao.emitir_acesso(pessoa, 'celular')
    with CaptureQueriesContext(connection) as consultas:
        sessao.renovar_acesso(segredo)
    travas = [c['sql'] for c in consultas if 'FOR UPDATE' in c['sql']]
    assert '"pessoa"' in travas[0]
    assert '"acesso_aplicativo"' in travas[1]


def test_revogacao_trava_a_pessoa_antes_dos_acessos(pessoa):
    # Achado do CodeRabbit (PR #9): a revogação avulsa seguia sem trava.
    sessao.emitir_acesso(pessoa, 'celular')
    with CaptureQueriesContext(connection) as consultas:
        sessao.revogar_acessos(pessoa)
    travas = [c['sql'] for c in consultas if 'FOR UPDATE' in c['sql']]
    assert len(travas) == 1
    assert '"pessoa"' in travas[0]


def test_acesso_revogado_nao_renova(pessoa):
    segredo = sessao.emitir_acesso(pessoa, 'celular')
    sessao.revogar_acessos(pessoa)
    assert sessao.renovar_acesso(segredo) is None


def test_revogar_acesso_depois_da_renovacao_encerra_a_sequencia_inteira(pessoa):
    # Achado do Greptile (PR #14): o `sair` autenticou o segredo antes de uma renovação; o UPDATE só do hash
    # recebido não tocava nenhuma linha e o segredo novo seguia válido.
    primeiro = sessao.emitir_acesso(pessoa, 'celular')
    renovado = sessao.renovar_acesso(primeiro)
    assert renovado is not None
    sessao.revogar_acesso(primeiro)
    assert sessao.pessoa_do_acesso(renovado[1]) is None


def test_revogar_acesso_nao_encerra_outro_dispositivo_nem_outra_entrada_do_mesmo(pessoa, monkeypatch):
    t0 = timezone.now()
    _agora_em(monkeypatch, t0)
    celular = sessao.emitir_acesso(pessoa, 'celular')
    tablet = sessao.emitir_acesso(pessoa, 'tablet')
    # A sequência é (pessoa, dispositivo, `entrada_em`): o relógio do Windows tem passo grosso e duas entradas no mesmo
    # passo pareceriam uma só, então o teste separa os instantes.
    _agora_em(monkeypatch, t0 + timedelta(seconds=1))
    outra_entrada = sessao.emitir_acesso(pessoa, 'celular')
    sessao.revogar_acesso(celular)
    assert sessao.pessoa_do_acesso(celular) is None
    assert sessao.pessoa_do_acesso(tablet) is not None
    assert sessao.pessoa_do_acesso(outra_entrada) is not None


def test_revogar_acesso_com_segredo_desconhecido_nao_faz_nada(pessoa):
    segredo = sessao.emitir_acesso(pessoa, 'celular')
    sessao.revogar_acesso('segredo-que-nao-existe')
    assert sessao.pessoa_do_acesso(segredo) is not None


def test_acesso_de_quem_ainda_deve_trocar_a_senha_nao_renova(pessoa):
    # Achado do Sourcery (PR #14): o acesso da primeira entrada só serve para trocar a senha.
    segredo = sessao.emitir_acesso(pessoa, 'celular')
    pessoa.deve_trocar_senha = True
    pessoa.save(update_fields=['deve_trocar_senha'])
    assert sessao.renovar_acesso(segredo) is None
    assert sessao.pessoa_do_acesso(segredo) is not None


def _rotacionar(pessoa, monkeypatch):
    t0 = timezone.now()
    _agora_em(monkeypatch, t0)
    primeiro = sessao.emitir_acesso(pessoa, 'celular')
    renovado = sessao.renovar_acesso(primeiro)
    assert renovado is not None
    return t0, primeiro, renovado[1]


def test_segredo_trocado_renova_de_novo_dentro_da_janela_e_os_dois_novos_valem(pessoa, monkeypatch):
    # T5.5e: resposta perdida, o aplicativo repete o segredo antigo. Okta e Auth0 fazem igual.
    t0, primeiro, segundo = _rotacionar(pessoa, monkeypatch)
    _agora_em(monkeypatch, t0 + timedelta(seconds=10))
    repetido = sessao.renovar_acesso(primeiro)
    assert repetido is not None
    assert repetido[1] not in (primeiro, segundo)
    assert sessao.pessoa_do_acesso(segundo) is not None
    assert sessao.pessoa_do_acesso(repetido[1]) is not None


def test_reuso_depois_da_janela_revoga_a_sequencia_inteira_e_audita(pessoa, monkeypatch):
    from comum.models import EventoAuditoria

    t0, primeiro, segundo = _rotacionar(pessoa, monkeypatch)
    _agora_em(monkeypatch, t0 + timedelta(seconds=settings.ACESSO_APLICATIVO_JANELA_SEGUNDOS))
    assert sessao.renovar_acesso(primeiro) is None
    assert sessao.pessoa_do_acesso(segundo) is None
    assert list(EventoAuditoria.objects.values_list('acao', flat=True)) == ['acesso_reutilizado']


def test_reuso_depois_de_sair_nao_ressuscita_a_sequencia_nem_audita(pessoa, monkeypatch):
    from comum.models import EventoAuditoria

    t0, primeiro, segundo = _rotacionar(pessoa, monkeypatch)
    sessao.revogar_acesso(segundo)
    _agora_em(monkeypatch, t0 + timedelta(seconds=5))
    assert sessao.renovar_acesso(primeiro) is None
    _agora_em(monkeypatch, t0 + timedelta(minutes=5))
    assert sessao.renovar_acesso(primeiro) is None
    assert EventoAuditoria.objects.count() == 0


def test_reuso_depois_da_troca_de_senha_nao_ressuscita_a_sequencia(pessoa, monkeypatch):
    t0, primeiro, segundo = _rotacionar(pessoa, monkeypatch)
    sessao.revogar_acessos(pessoa)
    _agora_em(monkeypatch, t0 + timedelta(seconds=5))
    assert sessao.renovar_acesso(primeiro) is None
    assert sessao.pessoa_do_acesso(segundo) is None
