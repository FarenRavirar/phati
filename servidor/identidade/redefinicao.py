"""Redefinição de senha por link (R5; plan.md §Autenticação).

Só o SHA-256 do segredo fica no banco. O link vale 10 minutos, é de uso único, preso ao pedido, com 5 tentativas.
Nunca abre sessão e nunca bloqueia nem conta falha na conta. O link usa `settings.URL_BASE`, jamais o cabeçalho Host.
"""

import logging
import secrets
import threading
from datetime import timedelta
from functools import partial

from django.core.exceptions import ValidationError
from django.db import connections, transaction
from django.utils import timezone

from comum.auditoria import auditar
from identidade import cpf, email, senha, sessao
from identidade.models import PedidoRedefinicao, Pessoa
from permissao.pode import administrador_da_empresa, memoria_de, pode
from territorio.models import Empresa

registro = logging.getLogger(__name__)

VALIDADE = timedelta(minutes=10)
TENTATIVAS_POR_PEDIDO = 5
# Achado do Qodo (PR #9): sem intervalo, quem digita o CPF alheio enche a caixa e derruba o link já recebido.
INTERVALO_ENTRE_PEDIDOS = timedelta(minutes=1)
# Pedidos que a própria pessoa (ou ninguém, pela rota pública) faz por hora: quem sabe o CPF de outra pessoa não consegue
# derrubar o link dela a cada minuto nem encher a caixa (OWASP Forgot Password Cheat Sheet: limite por conta).
TETO_POR_HORA = 5
JANELA_DO_TETO = timedelta(hours=1)


def empresa_de_atuacao(alvo, solicitante):
    """Primeira empresa (por id), entre a de origem de `alvo` e as das concessões dele, onde `solicitante` tem
    `redefinir_senha`; `None` se nenhuma. A regra final continua em `pode_iniciar_redefinicao`. Escolher só a de menor
    id negava o Administrador de uma empresa que não fosse a primeira (Sourcery, PR #16)."""
    ids = {vinculo.concessao.empresa_id for vinculo in memoria_de(alvo).vinculos}
    if alvo.empresa_origem_id is not None:
        ids.add(alvo.empresa_origem_id)
    return next(
        (empresa for empresa in Empresa.objects.filter(pk__in=ids).order_by('pk') if pode(solicitante, 'redefinir_senha', empresa)),
        None,
    )


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
        # Teto por hora só para o pedido da própria pessoa; o do Administrador (autenticado) não entra na conta.
        proprios = PedidoRedefinicao.objects.filter(pessoa=alvo, solicitado_por=alvo, expira_em__gt=agora + VALIDADE - JANELA_DO_TETO)
        if (solicitante is None or solicitante.pk == alvo.pk) and proprios.count() >= TETO_POR_HORA:
            return None
        # Retenção (achado do Qodo, PR #9): o pedido fica até sair da janela do teto, que precisa dele para contar; sai
        # na próxima solicitação da pessoa.
        PedidoRedefinicao.objects.filter(pessoa=alvo, expira_em__lte=agora + VALIDADE - JANELA_DO_TETO).delete()
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


def _pedir_na_fila(cpf_texto):
    try:
        pedir_redefinicao(cpf_texto)
    except Exception:  # a resposta já saiu; sem log o pedido perdido some em silêncio. O CPF não vai ao log.
        registro.exception('falha ao registrar pedido de redefinição')
    finally:
        # Só a thread da fila fecha as conexões que abriu; no teste a chamada é direta e a conexão é a do teste.
        if threading.current_thread().name.startswith('email'):
            connections.close_all()


def pedir_redefinicao_anonimo(cpf_texto):
    """Pedido sem sessão (tela e API pública): a resposta sai antes do trabalho, que roda na fila do e-mail.

    CPF inexistente, pedido barrado pelo intervalo e pedido gravado têm custos diferentes (medido: 4,1 ms contra
    11,7 ms); com o trabalho fora da resposta, o tempo dela não revela qual caso ocorreu (OWASP Forgot Password Cheat
    Sheet: tempo uniforme, por chamada assíncrona). Pedido de Administrador (com `solicitante`) segue em `pedir_redefinicao`.
    """
    email._despachar(partial(_pedir_na_fila, cpf_texto))


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
