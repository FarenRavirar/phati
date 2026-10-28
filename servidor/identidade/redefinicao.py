"""Redefinição de senha por link (R5; plan.md §Autenticação).

Só o SHA-256 do segredo fica no banco. O link vale 10 minutos, é de uso único, preso ao pedido, com 5 tentativas.
Nunca abre sessão e nunca bloqueia nem conta falha na conta. O link usa `settings.URL_BASE`, jamais o cabeçalho Host.
"""

import secrets
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from identidade import cpf, email, senha, sessao
from identidade.models import PedidoRedefinicao, Pessoa

VALIDADE = timedelta(minutes=10)
TENTATIVAS_POR_PEDIDO = 5
# Achado do Qodo (PR #9): sem intervalo, quem digita o CPF alheio enche a caixa e derruba o link já recebido.
INTERVALO_ENTRE_PEDIDOS = timedelta(minutes=1)


def pode_iniciar_redefinicao(solicitante, alvo):
    # shortcut: falta o Administrador de empresa com origem ou concessão ativa sobre `alvo` (T3.4a), que depende de
    # cargo e concessão da Fase 3; até lá só a própria pessoa e o Administrador da plataforma.
    return solicitante.pk == alvo.pk or solicitante.administrador_plataforma


def pedir_redefinicao(cpf_texto, solicitante=None):
    """Registra o pedido e envia o link. Sem `solicitante`, a própria pessoa pede (sem sessão).

    Devolve sempre `None`: CPF inexistente, pedido negado e pedido aceito são indistinguíveis para quem chama.
    """
    try:
        busca = cpf.chave_de_busca(cpf.normalizar_cpf(cpf_texto))
    except ValidationError:
        return None
    alvo = Pessoa.objects.filter(cpf_busca=busca).first()
    if alvo is None or (solicitante is not None and not pode_iniciar_redefinicao(solicitante, alvo)):
        return None
    agora = timezone.now()
    segredo = secrets.token_urlsafe(16)
    with transaction.atomic():
        # Trava a pessoa: dois pedidos simultâneos se serializam e só o último link fica de pé. O envio fica
        # dentro da transação: se o SMTP falhar, o link anterior continua valendo (achados do Qodo, PR #9).
        Pessoa.objects.select_for_update().get(pk=alvo.pk)
        # A criação do pedido é `expira_em - VALIDADE`; pedido recente, mesmo já usado, segura o novo.
        if PedidoRedefinicao.objects.filter(pessoa=alvo, expira_em__gt=agora + VALIDADE - INTERVALO_ENTRE_PEDIDOS).exists():
            return None
        # Retenção (achado do Qodo, PR #9): pedido vencido não serve a mais nada; sai na próxima solicitação da pessoa.
        PedidoRedefinicao.objects.filter(pessoa=alvo, expira_em__lte=agora).delete()
        PedidoRedefinicao.objects.filter(pessoa=alvo, usado_em__isnull=True).update(usado_em=agora)
        PedidoRedefinicao.objects.create(
            pessoa=alvo,
            hash_segredo=sessao.hash_do_segredo(segredo),
            solicitado_por=solicitante or alvo,
            expira_em=agora + VALIDADE,
        )
        email.enviar_link_de_redefinicao(alvo, segredo)
    return None


def confirmar_redefinicao(segredo, senha_nova):
    """Grava a senha nova. Link inexistente, vencido, usado ou esgotado levanta `link_invalido`; senha recusada
    levanta o código da regra e gasta uma das 5 tentativas do pedido."""
    agora = timezone.now()
    erro = None
    with transaction.atomic():
        pedido = (
            PedidoRedefinicao.objects.select_for_update()
            .select_related('pessoa')
            .filter(hash_segredo=sessao.hash_do_segredo(segredo))
            .first()
        )
        if pedido is None or pedido.usado_em is not None or pedido.expira_em <= agora or pedido.tentativas >= TENTATIVAS_POR_PEDIDO:
            raise ValidationError('Link inválido ou vencido.', code='link_invalido')
        pedido.tentativas += 1
        try:
            senha.definir_senha(pedido.pessoa, senha_nova)
        except ValidationError as recusa:
            erro = recusa
        else:
            pedido.usado_em = agora
        pedido.save(update_fields=['tentativas', 'usado_em'])
    if erro is not None:
        raise erro
    email.enviar_aviso_de_troca(pedido.pessoa)
