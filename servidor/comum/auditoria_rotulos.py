"""Rótulo e resumo em português de cada ação auditada (005 R5): o único lugar que dá texto ao registro.

O resumo recebe só os `detalhes` do evento e devolve uma frase curta; nunca o JSON cru e nunca CPF, e-mail, senha nem
token (R4). Ação de `ACOES` sem linha aqui reprova `test_auditoria_rotulos.py`; ação desconhecida, num registro
antigo, cai em `rotulo_e_resumo` com o nome da ação e resumo vazio.
"""

_SEM_RESUMO = ''


def _vazio(_):
    return _SEM_RESUMO


def _valor(detalhes, chave):
    """Texto do campo, ou vazio se ausente: dado ausente não vira zero nem 'None' na tela."""
    valor = detalhes.get(chave)
    return '' if valor is None else str(valor)


def _renomeado(detalhes):
    return f'De "{_valor(detalhes, "nome_antigo")}" para "{_valor(detalhes, "nome_novo")}".'


def _nivel(detalhes):
    nivel, antigo, novo = _valor(detalhes, 'nivel'), _valor(detalhes, 'nome_antigo'), _valor(detalhes, 'nome_novo')
    if antigo and novo:
        return f'Nível {nivel}: de "{antigo}" para "{novo}".'
    if novo:
        return f'Nível {nivel} definido como "{novo}".'
    return f'Nível {nivel} removido (era "{antigo}").'


def _bloqueio(detalhes):
    return f'Bloqueada por {_valor(detalhes, "segundos")} segundos.' if 'segundos' in detalhes else _SEM_RESUMO


def _cargo(detalhes):
    permissoes = detalhes.get('permissoes')
    quantas = f' com {len(permissoes)} permissões' if isinstance(permissoes, list) else ''
    return f'Cargo "{_valor(detalhes, "nome")}"{quantas}.'


def _concessao(detalhes):
    onde = 'sub-área' if detalhes.get('sub_area_id') else 'fazenda' if detalhes.get('fazenda_id') else 'empresa'
    return f'Acesso na {onde}.'


def _convite(detalhes):
    return 'Convite reenviado.' if detalhes.get('reenvio') else _SEM_RESUMO


def _cancelado(detalhes):
    return 'Substituído por um convite igual.' if detalhes.get('substituido') else _SEM_RESUMO


def _arquivamento(detalhes):
    invalidados = detalhes.get('convites_invalidados')
    return f'{len(invalidados)} convites invalidados.' if invalidados else _SEM_RESUMO


def _pacote(detalhes):
    return f'Versão {_valor(detalhes, "versao")}, origem {_valor(detalhes, "origem")}.'


def _consulta(detalhes):
    partes = [f'{chave}={valor}' for chave, valor in sorted(detalhes.items()) if valor not in (None, '')]
    return 'Filtros: ' + ', '.join(partes) + '.' if partes else 'Sem filtros.'


def _titularidade(detalhes):
    return 'Titularidade da empresa transferida.' if detalhes.get('para') is not None else _SEM_RESUMO


# ação → (rótulo, função do resumo). Uma linha por ação de `comum.auditoria.ACOES`.
ROTULOS = {
    'empresa_criada': ('Empresa criada', _vazio),
    'fazenda_criada': ('Fazenda criada', _vazio),
    'sub_area_criada': ('Sub-área criada', _vazio),
    'pessoa_criada': ('Pessoa criada', _vazio),
    'concessao_criada': ('Acesso concedido', _concessao),
    'concessao_revogada': ('Acesso revogado', _vazio),
    'titularidade_transferida': ('Titularidade transferida', _titularidade),
    'redefinicao_pedida': ('Redefinição de senha pedida', _vazio),
    'redefinicao_confirmada': ('Redefinição de senha confirmada', _vazio),
    'conta_bloqueada': ('Conta bloqueada', _bloqueio),
    'acesso_reutilizado': ('Token de acesso reutilizado', _vazio),
    'cargo_alterado': ('Cargo criado ou alterado', _cargo),
    'convite_criado': ('Convite criado', _convite),
    'convite_aceito': ('Convite aceito', _vazio),
    'convite_recusado': ('Convite recusado', _vazio),
    'convite_cancelado': ('Convite cancelado', _cancelado),
    'empresa_renomeada': ('Empresa renomeada', _renomeado),
    'fazenda_renomeada': ('Fazenda renomeada', _renomeado),
    'sub_area_renomeada': ('Sub-área renomeada', _renomeado),
    'territorio_arquivado': ('Arquivado', _arquivamento),
    'territorio_desarquivado': ('Desarquivado', _vazio),
    'nivel_definido': ('Nível da divisão definido', _nivel),
    'pacote_gerado': ('Pacote offline gerado', _pacote),
    'auditoria_consultada': ('Auditoria consultada', _consulta),
}


def rotulo_e_resumo(acao, detalhes):
    """(rótulo, resumo) da ação. Ação fora de `ROTULOS`: o nome da ação e resumo vazio, nunca o JSON nem erro."""
    if acao not in ROTULOS:
        return acao, _SEM_RESUMO
    rotulo, resumir = ROTULOS[acao]
    return rotulo, resumir(detalhes if isinstance(detalhes, dict) else {})
