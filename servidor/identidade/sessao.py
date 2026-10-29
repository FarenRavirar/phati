"""Sessão de navegador e acesso do aplicativo (R15; plan.md §Autenticação).

Navegador: sessão do Django com ociosidade de 30 min e duração absoluta de 12 h. O hash de autenticação da sessão
deriva do hash da senha; trocar a senha invalida toda sessão aberta sem tocar na tabela de sessões.
Aplicativo: segredo opaco rotativo, só o SHA-256 no banco; 30 dias deslizantes com teto de 30 dias desde a entrada
(NIST SP 800-63B-4, AAL1).
"""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import login
from django.db import transaction
from django.utils import timezone

from comum.auditoria import auditar
from identidade.models import AcessoAplicativo, Pessoa


def hash_do_segredo(segredo):
    return hashlib.sha256(segredo.encode()).hexdigest()


def iniciar_sessao(requisicao, pessoa):
    login(requisicao, pessoa, backend='django.contrib.auth.backends.ModelBackend')
    carimbar(requisicao)


def carimbar(requisicao):
    """Marca entrada e última atividade da sessão (o painel entra por `login()` do Django e usa só isto)."""
    agora = timezone.now().timestamp()
    requisicao.session['entrada_em'] = agora
    requisicao.session['ultima_atividade'] = agora


def sessao_vigente(requisicao):
    """Confere ociosidade e duração absoluta; vencida, esvazia a sessão. Vigente, renova a atividade."""
    agora = timezone.now().timestamp()
    sessao = requisicao.session
    entrada, atividade = sessao.get('entrada_em'), sessao.get('ultima_atividade')
    if (
        entrada is None
        or atividade is None
        or agora - entrada >= settings.SESSION_COOKIE_AGE
        or agora - atividade >= settings.SESSAO_OCIOSIDADE_SEGUNDOS
    ):
        sessao.flush()
        return False
    sessao['ultima_atividade'] = agora
    return True


def _expira_em(agora, entrada_em):
    return min(agora + timedelta(days=settings.ACESSO_APLICATIVO_DIAS), entrada_em + timedelta(days=settings.ACESSO_APLICATIVO_DIAS))


def _emitir(pessoa, dispositivo, agora, entrada_em):
    segredo = secrets.token_urlsafe(32)
    AcessoAplicativo.objects.create(
        pessoa=pessoa,
        hash_segredo=hash_do_segredo(segredo),
        dispositivo=dispositivo,
        entrada_em=entrada_em,
        expira_em=_expira_em(agora, entrada_em),
    )
    return segredo


def emitir_acesso(pessoa, dispositivo):
    agora = timezone.now()
    with transaction.atomic():
        # Trava a pessoa: emitir acesso e trocar a senha se serializam, e a troca revoga o que acabou de nascer.
        Pessoa.objects.select_for_update().get(pk=pessoa.pk)
        return _emitir(pessoa, dispositivo, agora, agora)


def _sequencia(pessoa_id, acesso):
    """Acessos da mesma entrada: o que `renovar_acesso` emite herda dispositivo e `entrada_em`."""
    return AcessoAplicativo.objects.filter(pessoa_id=pessoa_id, dispositivo=acesso.dispositivo, entrada_em=acesso.entrada_em)


def renovar_acesso(segredo):
    """Troca o segredo por um novo. Devolve `(pessoa, segredo_novo)` ou `None`.

    O segredo trocado ainda renova durante `ACESSO_APLICATIVO_JANELA_SEGUNDOS`: a resposta pode ter se perdido e o
    aplicativo tenta de novo. Passada a janela, usá-lo é reuso (roubo ou cópia): a sequência inteira é revogada e o
    evento `acesso_reutilizado` fica gravado. Segredo revogado por sair ou por troca de senha nunca renova."""
    agora = timezone.now()
    hash_segredo = hash_do_segredo(segredo)
    with transaction.atomic():
        # Ordem de travas igual à de senha.definir_senha (pessoa, depois acessos): sem deadlock, e a troca de
        # senha que revoga os acessos não deixa a renovação criar um novo por fora (achado do Greptile, PR #9).
        pessoa_id = AcessoAplicativo.objects.filter(hash_segredo=hash_segredo).values_list('pessoa_id', flat=True).first()
        if pessoa_id is None:
            return None
        pessoa = Pessoa.objects.select_for_update().get(pk=pessoa_id)
        if pessoa.deve_trocar_senha:
            return None  # acesso de primeira entrada só serve para trocar a senha, não se prolonga (Sourcery, PR #14)
        acesso = AcessoAplicativo.objects.select_for_update().filter(hash_segredo=hash_segredo).first()
        if acesso is None or acesso.expira_em <= agora:
            return None
        if acesso.revogado_em is None:
            acesso.revogado_em = agora
            acesso.substituido_em = agora
            acesso.save(update_fields=['revogado_em', 'substituido_em'])
        else:
            vivos = _sequencia(pessoa_id, acesso).filter(revogado_em__isnull=True, expira_em__gt=agora)
            if acesso.substituido_em is None or not vivos.exists():
                return None  # encerrado por sair ou por troca de senha: não ressuscita
            if (agora - acesso.substituido_em).total_seconds() >= settings.ACESSO_APLICATIVO_JANELA_SEGUNDOS:
                vivos.update(revogado_em=agora)
                auditar('acesso_reutilizado', pessoa, pessoa, pessoa.empresa_origem_id)
                return None
        return pessoa, _emitir(pessoa, acesso.dispositivo, agora, acesso.entrada_em)


def pessoa_do_acesso(segredo):
    """Pessoa dona do acesso vigente, sem rotacionar o segredo. `None` para segredo desconhecido, revogado ou vencido."""
    acesso = (
        AcessoAplicativo.objects.select_related('pessoa')
        .filter(hash_segredo=hash_do_segredo(segredo), revogado_em__isnull=True, expira_em__gt=timezone.now())
        .first()
    )
    return acesso.pessoa if acesso else None


def revogar_acesso(segredo):
    """Encerra a sequência de renovações deste acesso (um dispositivo, uma entrada); `revogar_acessos` encerra todos da pessoa.

    Revogar só o hash recebido deixava o segredo novo de uma renovação concorrente valendo (achado do Greptile, PR #14):
    a renovação revoga o hash e emite outro, com o mesmo dispositivo e a mesma `entrada_em`. A trava da pessoa, na ordem
    de `renovar_acesso`, serializa as duas e o UPDATE alcança o segredo mais novo da sequência.
    """
    with transaction.atomic():
        sequencia = AcessoAplicativo.objects.filter(hash_segredo=hash_do_segredo(segredo)).values('pessoa_id', 'dispositivo', 'entrada_em').first()
        if sequencia is None:
            return
        Pessoa.objects.select_for_update().get(pk=sequencia['pessoa_id'])
        AcessoAplicativo.objects.filter(**sequencia, revogado_em__isnull=True).update(revogado_em=timezone.now())


def revogar_acessos(pessoa):
    # Sozinha, a revogação também trava a pessoa antes dos acessos, a ordem de emitir e renovar (achado do
    # CodeRabbit, PR #9); dentro de definir_senha a trava já existe e esta é reentrante.
    with transaction.atomic():
        Pessoa.objects.select_for_update().get(pk=pessoa.pk)
        AcessoAplicativo.objects.filter(pessoa=pessoa, revogado_em__isnull=True).update(revogado_em=timezone.now())
