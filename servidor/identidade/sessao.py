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

from identidade.models import AcessoAplicativo, Pessoa


def hash_do_segredo(segredo):
    return hashlib.sha256(segredo.encode()).hexdigest()


def iniciar_sessao(requisicao, pessoa):
    login(requisicao, pessoa, backend='django.contrib.auth.backends.ModelBackend')
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


def renovar_acesso(segredo):
    """Troca o segredo por um novo e invalida o antigo. Devolve `(pessoa, segredo_novo)` ou `None`."""
    agora = timezone.now()
    hash_segredo = hash_do_segredo(segredo)
    with transaction.atomic():
        # Ordem de travas igual à de senha.definir_senha (pessoa, depois acessos): sem deadlock, e a troca de
        # senha que revoga os acessos não deixa a renovação criar um novo por fora (achado do Greptile, PR #9).
        pessoa_id = AcessoAplicativo.objects.filter(hash_segredo=hash_segredo).values_list('pessoa_id', flat=True).first()
        if pessoa_id is None:
            return None
        pessoa = Pessoa.objects.select_for_update().get(pk=pessoa_id)
        acesso = (
            AcessoAplicativo.objects.select_for_update()
            .filter(hash_segredo=hash_segredo, revogado_em__isnull=True, expira_em__gt=agora)
            .first()
        )
        if acesso is None:
            return None
        acesso.revogado_em = agora
        acesso.save(update_fields=['revogado_em'])
        return pessoa, _emitir(pessoa, acesso.dispositivo, agora, acesso.entrada_em)


def revogar_acessos(pessoa):
    # Sozinha, a revogação também trava a pessoa antes dos acessos, a ordem de emitir e renovar (achado do
    # CodeRabbit, PR #9); dentro de definir_senha a trava já existe e esta é reentrante.
    with transaction.atomic():
        Pessoa.objects.select_for_update().get(pk=pessoa.pk)
        AcessoAplicativo.objects.filter(pessoa=pessoa, revogado_em__isnull=True).update(revogado_em=timezone.now())
