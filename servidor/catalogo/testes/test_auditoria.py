"""Auditoria do catálogo (008 R14): publicar, confirmar sistema, trocar nó e ocultar atributo geram evento com rótulo;
o detalhe nunca leva valor de atributo nem dado pessoal."""

import pytest
from django.db import IntegrityError

from comum.auditoria import ACOES, auditar
from comum.auditoria_rotulos import rotulo_e_resumo
from comum.models import EventoAuditoria

NOVAS = ('camada_publicada', 'sistema_confirmado', 'no_trocado', 'atributo_ocultado')


@pytest.mark.parametrize('acao', NOVAS)
def test_acao_do_catalogo_esta_na_lista_de_acoes(acao):
    assert acao in ACOES


@pytest.mark.parametrize('acao', NOVAS)
def test_acao_do_catalogo_tem_rotulo_em_portugues(acao):
    rotulo, _resumo = rotulo_e_resumo(acao, {})
    assert rotulo and rotulo != acao


def test_resumo_de_atributo_ocultado_nao_leva_o_valor_do_atributo():
    # Caminho feliz e prova de R14: o detalhe só tem o nome do atributo; valor e dado pessoal ficam de fora.
    _rotulo, resumo = rotulo_e_resumo('atributo_ocultado', {
        'nome_atributo': 'nome_proprietario', 'valor': 'Maria Sintética', 'cpf': '000.000.000-00',
    })
    assert 'nome_proprietario' in resumo
    assert 'Maria Sintética' not in resumo and '000.000.000-00' not in resumo


def test_evento_de_camada_publicada_grava_so_os_campos_permitidos(cenario):
    evento = auditar('camada_publicada', pessoa=None, empresa_id=cenario.x.pk,
                     detalhes={'versao': 1, 'nome_camada': 'Solo sintético'})
    evento.refresh_from_db()
    assert evento.detalhes == {'versao': 1, 'nome_camada': 'Solo sintético'}


def test_acao_fora_da_lista_e_recusada_ao_auditar(cenario):
    # Caminho infeliz: ação não cadastrada não grava evento sem rótulo.
    with pytest.raises(ValueError):
        auditar('acao_inventada', pessoa=None, empresa_id=cenario.x.pk, detalhes={})
    assert not EventoAuditoria.objects.filter(acao='acao_inventada').exists()
