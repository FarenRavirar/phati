"""Rótulo e resumo em português de cada ação auditada (005 R5): o único lugar que dá texto ao registro.

O resumo recebe só os `detalhes` do evento e devolve uma frase curta; nunca o JSON cru e nunca CPF, e-mail, senha nem
token (R4). Ação de `ACOES` sem linha aqui reprova `test_auditoria_rotulos.py`; ação desconhecida, num registro
antigo, cai em `rotulo_e_resumo` com o nome da ação e resumo vazio.
"""

from datetime import datetime

from comum.auditoria import ACOES

_SEM_RESUMO = ''
# Filtros que `auditoria_consultada` guarda e a tela repete: só estas chaves, e `acao` só se for nome de `ACOES`.
_FILTROS = ('desde', 'ate', 'acao', 'pessoa_id', 'alvo_pessoa_id', 'empresa_id')


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


def _atributo_ocultado(detalhes):
    # R14: só o nome do atributo; o valor e qualquer dado pessoal que estejam no detalhe não aparecem.
    return f'Atributo "{_valor(detalhes, "nome_atributo")}" ocultado.'


def _camada_publicada(detalhes):
    return f'Camada "{_valor(detalhes, "nome_camada")}", versão {_valor(detalhes, "versao")}, em análise.'


def _bloqueio(detalhes):
    return f'Bloqueada por {_valor(detalhes, "segundos")} segundos.' if 'segundos' in detalhes else _SEM_RESUMO


def _cargo(detalhes):
    permissoes = detalhes.get('permissoes')
    quantas = f' com {len(permissoes)} permissões' if isinstance(permissoes, list) else ''
    return f'Cargo "{_valor(detalhes, "nome")}"{quantas}.'


def _concessao(detalhes):
    if detalhes.get('sub_area_id'):
        onde = 'sub-área'
    elif detalhes.get('fazenda_id'):
        onde = 'fazenda'
    else:
        onde = 'empresa'
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


def _e_data_com_fuso(valor):
    """O que a rota grava é `AwareDatetime.isoformat()`: data e hora com fuso. Dígitos soltos (CPF, telefone) não passam."""
    if not isinstance(valor, str) or len(valor) > 40:
        return False
    try:
        return datetime.fromisoformat(valor).tzinfo is not None
    except ValueError:
        return False


def _filtro_seguro(chave, valor):
    """O valor que a tela pode mostrar do filtro, ou vazio: só número inteiro, data em texto curto e nome de ação conhecido.
    Registro antigo ou de outra origem com texto livre, objeto ou segredo no filtro não chega à tela (Sourcery, PR #55)."""
    if chave == 'acao':
        return valor if isinstance(valor, str) and valor in ACOES else ''  # lista/dict não são hasheáveis: `in` levantaria
    if chave in ('desde', 'ate'):
        return valor if _e_data_com_fuso(valor) else ''
    return str(valor) if isinstance(valor, int) and not isinstance(valor, bool) else ''


def _consulta(detalhes):
    mostrados = {chave: _filtro_seguro(chave, detalhes.get(chave)) for chave in _FILTROS}
    partes = [f'{chave}={valor}' for chave, valor in mostrados.items() if valor]
    return 'Filtros: ' + ', '.join(partes) + '.' if partes else 'Sem filtros.'


def _titularidade(detalhes):
    return 'Titularidade da empresa transferida.' if detalhes.get('para') is not None else _SEM_RESUMO


# ação → (rótulo, função do resumo). Uma linha por ação de `comum.auditoria.ACOES`.
ROTULOS = {
    'empresa_criada': ('Empresa criada', _vazio),
    'fazenda_criada': ('Fazenda criada', _vazio),
    'sub_area_criada': ('Sub-área criada', _vazio),
    'pessoa_criada': ('Pessoa criada', _vazio),
    'camada_publicada': ('Camada publicada', _camada_publicada),
    'sistema_confirmado': ('Sistema de referência confirmado', _vazio),
    'no_trocado': ('Nó trocado', _vazio),
    'atributo_ocultado': ('Atributo ocultado', _atributo_ocultado),
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
