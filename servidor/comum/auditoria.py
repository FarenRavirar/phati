"""Serviço único de auditoria (R16): toda ação administrativa relevante chama `auditar()` na mesma transação da ação."""

from comum.models import EventoAuditoria

# Ações auditadas (R16). Uma lista fechada: nome novo é decisão consciente, e o teste confere o uso.
ACOES = frozenset({
    'empresa_criada', 'fazenda_criada', 'sub_area_criada', 'pessoa_criada',
    'concessao_criada', 'concessao_revogada', 'titularidade_transferida',
    'redefinicao_pedida', 'redefinicao_confirmada', 'conta_bloqueada', 'acesso_reutilizado',
    'cargo_alterado', 'convite_criado', 'convite_aceito', 'convite_recusado', 'convite_cancelado',
    'empresa_renomeada', 'fazenda_renomeada', 'sub_area_renomeada', 'territorio_arquivado', 'territorio_desarquivado',
    'nivel_definido', 'pacote_gerado', 'auditoria_consultada',
    # Catálogo de camadas (008 R14): nunca leva valor de atributo nem dado pessoal no detalhe.
    'camada_publicada', 'sistema_confirmado', 'no_trocado', 'atributo_ocultado',
})

# Chaves que cada ação do catálogo pode gravar no detalhe (008 R14). Chave fora da lista é descartada antes de gravar,
# então valor de atributo e CPF não chegam ao banco mesmo que o chamador os passe. Ação fora desta tabela grava o que recebe.
CAMPOS_PERMITIDOS = {
    'camada_publicada': frozenset({'nome_camada', 'versao'}),
    'sistema_confirmado': frozenset({'camada', 'versao', 'sistema'}),
    'no_trocado': frozenset({'camada', 'versao', 'no_anterior_id', 'no_novo_id'}),
    'atributo_ocultado': frozenset({'nome_atributo', 'versao', 'camada'}),
}


def auditar(acao, pessoa=None, alvo=None, empresa_id=None, detalhes=None):
    """Grava o evento. `alvo` é o objeto afetado (tipo e id viram colunas); `detalhes` só com dado não secreto.

    Chame dentro da `transaction.atomic()` da ação: o evento e a ação valem juntos ou nenhum dos dois.
    """
    if acao not in ACOES:
        raise ValueError(f'Ação de auditoria desconhecida: {acao}')
    detalhes = detalhes or {}
    if acao in CAMPOS_PERMITIDOS:
        detalhes = {chave: valor for chave, valor in detalhes.items() if chave in CAMPOS_PERMITIDOS[acao]}
    return EventoAuditoria.objects.create(
        pessoa_id=pessoa.pk if pessoa is not None else None,
        acao=acao,
        alvo_tipo=type(alvo).__name__ if alvo is not None else '',
        alvo_id=alvo.pk if alvo is not None else None,
        empresa_id=empresa_id,
        detalhes=detalhes,
    )
