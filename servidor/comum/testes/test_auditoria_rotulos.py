"""Rótulo e resumo de cada ação auditada (005 R5): toda ação de `ACOES` tem texto, e dado estranho nunca vira JSON cru."""

import pytest

from comum.auditoria import ACOES
from comum.auditoria_rotulos import ROTULOS, rotulo_e_resumo


def test_toda_acao_auditada_tem_rotulo_e_so_ela():
    assert set(ROTULOS) == ACOES


@pytest.mark.parametrize('acao', sorted(ACOES))
def test_toda_acao_resume_detalhes_vazios_sem_erro_e_sem_json(acao):
    rotulo, resumo = rotulo_e_resumo(acao, {})
    assert rotulo
    assert rotulo != acao
    assert '{' not in resumo
    assert 'None' not in resumo


@pytest.mark.parametrize('detalhes', [None, [], 'texto', 7])
def test_detalhes_que_nao_sao_um_objeto_nao_derrubam_o_resumo(detalhes):
    assert rotulo_e_resumo('conta_bloqueada', detalhes) == ('Conta bloqueada', '')


def test_acao_desconhecida_de_registro_antigo_cai_no_nome_da_acao():
    assert rotulo_e_resumo('acao_removida_no_futuro', {'x': 1}) == ('acao_removida_no_futuro', '')


def test_resumos_mostram_so_o_que_importa_em_portugues():
    assert rotulo_e_resumo('fazenda_renomeada', {'nome_antigo': 'F1', 'nome_novo': 'F1 Nova'})[1] == 'De "F1" para "F1 Nova".'
    assert rotulo_e_resumo('conta_bloqueada', {'segundos': 30})[1] == 'Bloqueada por 30 segundos.'
    assert rotulo_e_resumo('nivel_definido', {'nivel': 2, 'nome_antigo': 'Talhão', 'nome_novo': 'Pivô'})[1] == 'Nível 2: de "Talhão" para "Pivô".'
    assert rotulo_e_resumo('nivel_definido', {'nivel': 2, 'nome_antigo': None, 'nome_novo': 'Talhão'})[1] == 'Nível 2 definido como "Talhão".'
    assert rotulo_e_resumo('nivel_definido', {'nivel': 1, 'nome_antigo': 'Quadra', 'nome_novo': None})[1] == 'Nível 1 removido (era "Quadra").'
    assert rotulo_e_resumo('cargo_alterado', {'nome': 'Cargo', 'permissoes': ['ver', 'baixar_documento']})[1] == 'Cargo "Cargo" com 2 permissões.'
    assert rotulo_e_resumo('pacote_gerado', {'versao': 3, 'origem': 'comando', 'usuario_so': 'maria'})[1] == 'Versão 3, origem comando.'
    assert rotulo_e_resumo('auditoria_consultada', {})[1] == 'Sem filtros.'
    assert rotulo_e_resumo('auditoria_consultada', {'acao': 'pessoa_criada', 'empresa_id': 4})[1] == 'Filtros: acao=pessoa_criada, empresa_id=4.'


def test_resumo_nao_mostra_o_dado_que_o_detalhe_guarda_e_a_tela_nao_precisa():
    _, resumo = rotulo_e_resumo('titularidade_transferida', {'de': 1, 'para': 2, 'justificativa': 'texto livre do administrador'})
    assert 'texto livre' not in resumo
    assert 'justificativa' not in resumo


def test_resumo_da_consulta_so_mostra_filtros_seguros_e_nao_o_que_veio_de_fora():
    """Sourcery (PR #55): segredo, objeto ou texto livre no filtro de um registro não chega à tela."""
    hostil = {'acao': 'senha-do-banco-123', 'empresa_id': 'texto', 'pessoa_id': True, 'desde': 'x' * 100, 'ate': {'a': 1},
              'segredo': 'valor-secreto', 'alvo_pessoa_id': [1]}
    assert rotulo_e_resumo('auditoria_consultada', hostil)[1] == 'Sem filtros.'
    seguro = {'acao': 'pessoa_criada', 'empresa_id': 4, 'desde': '2026-08-11T01:12:20+00:00', 'segredo': 'valor-secreto'}
    resumo = rotulo_e_resumo('auditoria_consultada', seguro)[1]
    assert resumo == 'Filtros: desde=2026-08-11T01:12:20+00:00, acao=pessoa_criada, empresa_id=4.'


@pytest.mark.parametrize('detalhes', [
    {'acao': {'a': 1}},
    {'acao': ['pessoa_criada']},
    {'desde': '12345678901'},
    {'desde': '2026-08-11T01:12:20'},
])
def test_filtro_que_nao_e_nome_de_acao_nem_data_com_fuso_nao_chega_ao_resumo(detalhes):
    assert rotulo_e_resumo('auditoria_consultada', detalhes) == ('Auditoria consultada', 'Sem filtros.')


def test_data_com_fuso_do_filtro_continua_no_resumo():
    assert rotulo_e_resumo('auditoria_consultada', {'desde': '2026-08-11T01:12:20+00:00'})[1] == 'Filtros: desde=2026-08-11T01:12:20+00:00.'


@pytest.mark.parametrize(('detalhes', 'esperado'), [
    ({'sub_area_id': 3, 'fazenda_id': 2}, 'Acesso na sub-área.'),
    ({'fazenda_id': 2, 'sub_area_id': None}, 'Acesso na fazenda.'),
    ({'fazenda_id': None, 'sub_area_id': None}, 'Acesso na empresa.'),
])
def test_resumo_da_concessao_diz_o_nivel_do_acesso(detalhes, esperado):
    assert rotulo_e_resumo('concessao_criada', detalhes)[1] == esperado


def test_edicao_da_fazenda_so_com_nome_mostra_o_nome():
    _, resumo = rotulo_e_resumo('fazenda_renomeada', {'nome_antigo': 'F1', 'nome_novo': 'F2'})
    assert resumo == 'De "F1" para "F2".'


def test_edicao_so_do_municipio_mostra_o_municipio_e_nao_repete_o_nome():
    rotulo, resumo = rotulo_e_resumo('fazenda_renomeada', {'nome_antigo': 'F1', 'nome_novo': 'F1', 'municipio_antigo': '', 'municipio_novo': 'Sorriso'})
    assert rotulo == 'Fazenda editada'
    assert resumo == 'Município de Sem dados para "Sorriso".'


def test_edicao_sem_mudanca_devolve_sem_alteracao():
    # Feliz do resumo vazio: nome e município iguais não geram frase; negativo: sem detalhe de município também.
    assert rotulo_e_resumo('fazenda_renomeada', {'nome_antigo': 'F1', 'nome_novo': 'F1', 'municipio_antigo': 'Sorriso', 'municipio_novo': 'Sorriso'}) == (
        'Fazenda editada', 'Sem alteração.')
    assert rotulo_e_resumo('fazenda_renomeada', {'nome_antigo': 'F1', 'nome_novo': 'F1'}) == ('Fazenda editada', 'Sem alteração.')


def test_municipio_limpo_mostra_sem_dados_sem_aspas_no_novo_valor():
    _, resumo = rotulo_e_resumo('fazenda_renomeada', {'nome_antigo': 'F1', 'nome_novo': 'F1', 'municipio_antigo': 'Sorriso', 'municipio_novo': ''})
    assert resumo == 'Município de "Sorriso" para Sem dados.'


def test_municipio_antigo_ausente_vira_sem_dados_sem_aspas():
    _, resumo = rotulo_e_resumo('fazenda_renomeada', {'nome_antigo': 'F1', 'nome_novo': 'F1', 'municipio_novo': 'Sorriso'})
    assert resumo == 'Município de Sem dados para "Sorriso".'


def test_edicao_com_nome_e_municipio_mostra_os_dois_e_sem_municipio_no_detalhe_nao_mostra_municipio():
    _, resumo = rotulo_e_resumo('fazenda_renomeada', {'nome_antigo': 'F1', 'nome_novo': 'F2', 'municipio_antigo': 'A', 'municipio_novo': 'B'})
    assert resumo == 'De "F1" para "F2". Município de "A" para "B".'
    assert 'Município' not in rotulo_e_resumo('fazenda_renomeada', {'nome_antigo': 'F1', 'nome_novo': 'F2'})[1]

