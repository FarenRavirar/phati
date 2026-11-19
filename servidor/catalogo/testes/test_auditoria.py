"""Auditoria do catálogo (008 R14): publicar, confirmar sistema, trocar nó e ocultar atributo geram evento com rótulo;
o evento salvo guarda só as chaves permitidas da ação, e o detalhe nunca leva valor de atributo nem dado pessoal."""

import pytest

from comum.auditoria import ACOES, CAMPOS_PERMITIDOS, auditar
from comum.auditoria_rotulos import rotulo_e_resumo
from comum.models import EventoAuditoria

ROTULO_ESPERADO = {
    'camada_publicada': 'Camada publicada',
    'sistema_confirmado': 'Sistema de referência confirmado',
    'no_trocado': 'Nó trocado',
    'atributo_ocultado': 'Atributo ocultado',
}
NOVAS = tuple(ROTULO_ESPERADO)
SENSIVEIS = {'valor': 'Maria Sintética', 'cpf': '000.000.000-00'}


@pytest.mark.parametrize('acao', NOVAS)
def test_acao_do_catalogo_esta_na_lista_de_acoes(acao):
    assert acao in ACOES


@pytest.mark.parametrize('acao', NOVAS)
def test_rotulo_em_portugues_e_o_esperado(acao):
    rotulo, _resumo = rotulo_e_resumo(acao, {})
    assert rotulo == ROTULO_ESPERADO[acao]


def test_resumo_de_atributo_ocultado_cita_o_nome_do_atributo():
    _rotulo, resumo = rotulo_e_resumo('atributo_ocultado', {'nome_atributo': 'nome_proprietario'})
    assert 'nome_proprietario' in resumo


def test_resumo_de_atributo_ocultado_nao_leva_valor_nem_cpf():
    _rotulo, resumo = rotulo_e_resumo('atributo_ocultado', {'nome_atributo': 'n', **SENSIVEIS})
    assert all(valor not in resumo for valor in SENSIVEIS.values())


def test_evento_de_atributo_ocultado_salvo_so_com_chaves_permitidas(cenario):
    evento = auditar('atributo_ocultado', pessoa=None, empresa_id=cenario.x.pk,
                     detalhes={'nome_atributo': 'area_ha', 'versao': 1, 'camada': 'Solo', **SENSIVEIS})
    evento.refresh_from_db()
    assert evento.detalhes == {'nome_atributo': 'area_ha', 'versao': 1, 'camada': 'Solo'}
    assert all(valor not in str(evento.detalhes) for valor in SENSIVEIS.values())


@pytest.mark.parametrize('acao', NOVAS)
def test_cada_acao_nova_grava_so_os_campos_da_sua_lista(cenario, acao):
    # Lista permitida por ação: o que não está nela (valor e cpf) é descartado antes de gravar.
    detalhes = {campo: 'x' for campo in CAMPOS_PERMITIDOS[acao]} | SENSIVEIS
    evento = auditar(acao, pessoa=None, empresa_id=cenario.x.pk, detalhes=detalhes)
    evento.refresh_from_db()
    assert set(evento.detalhes) == CAMPOS_PERMITIDOS[acao]
    assert all(valor not in str(evento.detalhes) for valor in SENSIVEIS.values())


def test_acao_fora_da_lista_e_recusada_e_nao_grava(cenario):
    with pytest.raises(ValueError):
        auditar('acao_inventada', pessoa=None, empresa_id=cenario.x.pk, detalhes={})
    assert not EventoAuditoria.objects.filter(acao='acao_inventada').exists()
