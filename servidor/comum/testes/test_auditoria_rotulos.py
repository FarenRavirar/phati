"""Rótulo e resumo de cada ação auditada (005 R5): toda ação de `ACOES` tem texto, e dado estranho nunca vira JSON cru."""

import pytest

from comum.auditoria import ACOES
from comum.auditoria_rotulos import ROTULOS, rotulo_e_resumo


def test_toda_acao_auditada_tem_rotulo_e_so_ela():
    assert set(ROTULOS) == ACOES


@pytest.mark.parametrize('acao', sorted(ACOES))
def test_toda_acao_resume_detalhes_vazios_sem_erro_e_sem_json(acao):
    rotulo, resumo = rotulo_e_resumo(acao, {})
    assert rotulo and rotulo != acao
    assert '{' not in resumo and 'None' not in resumo


@pytest.mark.parametrize('detalhes', [None, [], 'texto', 7])
def test_detalhes_que_nao_sao_um_objeto_nao_derrubam_o_resumo(detalhes):
    assert rotulo_e_resumo('conta_bloqueada', detalhes) == ('Conta bloqueada', '')


def test_acao_desconhecida_de_registro_antigo_cai_no_nome_da_acao():
    assert rotulo_e_resumo('acao_removida_no_futuro', {'x': 1}) == ('acao_removida_no_futuro', '')


def test_resumos_mostram_so_o_que_importa_em_portugues():
    assert rotulo_e_resumo('fazenda_renomeada', {'nome_antigo': 'F1', 'nome_novo': 'F1 Nova'})[1] == 'De "F1" para "F1 Nova".'
    assert rotulo_e_resumo('conta_bloqueada', {'segundos': 30})[1] == 'Bloqueada por 30 segundos.'
    assert rotulo_e_resumo('nivel_definido', {'nivel': 2, 'nome_antigo': None, 'nome_novo': 'Talhão'})[1] == 'Nível 2 definido como "Talhão".'
    assert rotulo_e_resumo('nivel_definido', {'nivel': 1, 'nome_antigo': 'Quadra', 'nome_novo': None})[1] == 'Nível 1 removido (era "Quadra").'
    assert rotulo_e_resumo('cargo_alterado', {'nome': 'Cargo', 'permissoes': ['ver', 'baixar_documento']})[1] == 'Cargo "Cargo" com 2 permissões.'
    assert rotulo_e_resumo('pacote_gerado', {'versao': 3, 'origem': 'comando', 'usuario_so': 'maria'})[1] == 'Versão 3, origem comando.'
    assert rotulo_e_resumo('auditoria_consultada', {})[1] == 'Sem filtros.'
    assert rotulo_e_resumo('auditoria_consultada', {'acao': 'pessoa_criada', 'empresa_id': 4})[1] == 'Filtros: acao=pessoa_criada, empresa_id=4.'


def test_resumo_nao_mostra_o_dado_que_o_detalhe_guarda_e_a_tela_nao_precisa():
    _, resumo = rotulo_e_resumo('titularidade_transferida', {'de': 1, 'para': 2, 'justificativa': 'texto livre do administrador'})
    assert 'texto livre' not in resumo and 'justificativa' not in resumo
