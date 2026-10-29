"""Serviço único de auditoria (R16): toda ação administrativa relevante chama `auditar()` na mesma transação da ação."""

from comum.models import EventoAuditoria

# Ações auditadas (R16). Uma lista fechada: nome novo é decisão consciente, e o teste confere o uso.
ACOES = frozenset({
    'empresa_criada', 'fazenda_criada', 'sub_area_criada', 'pessoa_criada',
    'concessao_criada', 'concessao_revogada', 'titularidade_transferida',
    'redefinicao_pedida', 'redefinicao_confirmada', 'conta_bloqueada', 'acesso_reutilizado',
    'cargo_alterado',
})


def auditar(acao, pessoa=None, alvo=None, empresa_id=None, detalhes=None):
    """Grava o evento. `alvo` é o objeto afetado (tipo e id viram colunas); `detalhes` só com dado não secreto.

    Chame dentro da `transaction.atomic()` da ação: o evento e a ação valem juntos ou nenhum dos dois.
    """
    if acao not in ACOES:
        raise ValueError(f'Ação de auditoria desconhecida: {acao}')
    return EventoAuditoria.objects.create(
        pessoa_id=pessoa.pk if pessoa is not None else None,
        acao=acao,
        alvo_tipo=type(alvo).__name__ if alvo is not None else '',
        alvo_id=alvo.pk if alvo is not None else None,
        empresa_id=empresa_id,
        detalhes=detalhes or {},
    )
