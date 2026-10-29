"""Redefinição de senha por link (R5; plan.md §Autenticação).

Só o SHA-256 do segredo fica no banco. O link vale 10 minutos, é de uso único, preso ao pedido, com 5 tentativas.
Nunca abre sessão e nunca bloqueia nem conta falha na conta. O link usa `settings.URL_BASE`, jamais o cabeçalho Host.
"""

import secrets
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from comum.auditoria import auditar
from identidade import cpf, email, senha, sessao
from identidade.models import PedidoRedefinicao, Pessoa
from permissao.pode import administrador_da_empresa, memoria_de

VALIDADE = timedelta(minutes=10)
TENTATIVAS_POR_PEDIDO = 5
# Achado do Qodo (PR #9): sem intervalo, quem digita o CPF alheio enche a caixa e derruba o link já recebido.
INTERVALO_ENTRE_PEDIDOS = timedelta(minutes=1)


def pode_iniciar_redefinicao(solicitante, alvo):
    """R5: a própria pessoa, o Administrador da plataforma e o Administrador da empresa de origem de `alvo` ou de
    empresa onde `alvo` tem concessão ativa (colaborador externo). Técnico e empresa sem vínculo não."""
    if solicitante.pk == alvo.pk or solicitante.administrador_plataforma:
        return True
    # Pelas concessões que `pode()` já usa (função do banco): sob RLS o pedido não tem escopo para listá-las por ORM.
    empresas = {vinculo.concessao.empresa_id for vinculo in memoria_de(alvo).vinculos}
    if alvo.empresa_origem_id is not None:
        empresas.add(alvo.empresa_origem_id)
    return any(administrador_da_empresa(solicitante, empresa_id) for empresa_id in empresas)


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
        # Trava a pessoa: dois pedidos simultâneos se serializam e só o último link fica de pé. O e-mail sai
        # depois do commit (`email.py`): rollback não envia link de pedido que não existe, e falha do SMTP não
        # chega à resposta, que seria um oráculo de CPF cadastrado.
        # `no_key`: `solicitado_por` aponta para outra pessoa e a FK pede KEY SHARE; FOR UPDATE daria deadlock com
        # duas redefinições cruzadas (mesma classe do achado do Codex no PR #11).
        Pessoa.objects.select_for_update(no_key=True).get(pk=alvo.pk)
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
        # Sem `solicitante` o pedido é anônimo (sem sessão): atribuí-lo ao alvo culparia a vítima.
        auditar('redefinicao_pedida', solicitante, alvo, alvo.empresa_origem_id)
        email.enviar_link_de_redefinicao(alvo, segredo)
    return None


def confirmar_redefinicao(segredo, senha_nova):
    """Grava a senha nova. Link inexistente, vencido, usado ou esgotado levanta `link_invalido`; senha recusada
    levanta o código da regra e gasta uma das 5 tentativas do pedido."""
    agora = timezone.now()
    erro = None
    hash_segredo = sessao.hash_do_segredo(segredo)
    with transaction.atomic():
        # Trava a pessoa antes do pedido, a ordem de senha.definir_senha: o inverso daria deadlock entre uma
        # confirmação e uma troca de senha simultâneas (achado do Greptile, PR #9).
        pessoa_id = PedidoRedefinicao.objects.filter(hash_segredo=hash_segredo).values_list('pessoa_id', flat=True).first()
        if pessoa_id is None:
            raise ValidationError('Link inválido ou vencido.', code='link_invalido')
        pessoa = Pessoa.objects.select_for_update().get(pk=pessoa_id)
        pedido = PedidoRedefinicao.objects.select_for_update().filter(hash_segredo=hash_segredo).first()
        if pedido is None or pedido.usado_em is not None or pedido.expira_em <= agora or pedido.tentativas >= TENTATIVAS_POR_PEDIDO:
            raise ValidationError('Link inválido ou vencido.', code='link_invalido')
        pedido.tentativas += 1
        try:
            senha.definir_senha(pessoa, senha_nova)
        except ValidationError as recusa:
            erro = recusa
        else:
            pedido.usado_em = agora
            # Confirmação anônima, como o pedido: quem tem o link não abre sessão, então o autor fica vazio.
            auditar('redefinicao_confirmada', None, pessoa, pessoa.empresa_origem_id)
        pedido.save(update_fields=['tentativas', 'usado_em'])
    if erro is not None:
        raise erro
    email.enviar_aviso_de_troca(pessoa)
