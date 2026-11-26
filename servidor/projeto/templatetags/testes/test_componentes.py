"""Filtros dos componentes (spec 012, R14): variante validada, mapa do Selo e limite do Esqueleto, com caso infeliz."""

import pytest

from projeto.templatetags.componentes import dentre, repetir, selo_rotulo, selo_tom


def test_dentre_devolve_a_variante_conhecida():
    assert dentre('secundario', 'primario secundario fantasma perigo') == 'secundario'


def test_dentre_devolve_vazio_para_variante_desconhecida_e_para_valor_ausente():
    assert dentre('inventada', 'primario secundario') == ''
    assert dentre(None, 'primario secundario') == ''
    assert dentre(1, 'primario secundario') == ''  # não-texto nunca casa com a lista
    assert dentre('', 'primario secundario') == ''


def test_dentre_nao_casa_parte_de_palavra():
    # `in` sobre a string casaria "ai" dentro de "aviso"; a lista é por palavra.
    assert dentre('ai', 'erro aviso info sucesso') == ''


def test_selo_tom_e_rotulo_seguem_o_mapeamento_de_governanca():
    assert (selo_tom('em_analise'), selo_rotulo('em_analise')) == ('aviso', 'Em análise')
    assert (selo_tom('vigente'), selo_rotulo('vigente')) == ('sucesso', 'Vigente')
    assert (selo_tom('arquivada'), selo_rotulo('arquivada')) == ('neutro', 'Arquivada')


@pytest.mark.parametrize('situacao', ['desconhecida', '', None, 3])
def test_selo_situacao_desconhecida_ou_ausente_nao_inventa_tom(situacao):
    assert selo_tom(situacao) == ''
    assert selo_rotulo(situacao) == ''


def test_repetir_gera_as_linhas_do_esqueleto():
    assert list(repetir(3)) == [0, 1, 2]


@pytest.mark.parametrize('quantidade', [0, -1, 21, 10**9, '3', None, True, 2.0])
def test_repetir_recusa_quantidade_invalida_ou_hostil(quantidade):
    assert list(repetir(quantidade)) == []
