"""Exportação CSV de fazendas (012 R30): formato pt-BR, neutralização de fórmula, ausente ≠ zero e auditoria por empresa."""

import csv
import io
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from comum.auditoria_rotulos import rotulo_e_resumo
from comum.models import EventoAuditoria
from territorio import exportacao
from territorio.exportacao import csv_das_fazendas, neutralizar, registrar_exportacao
from territorio.listagem import LinhaFazenda

pytestmark = pytest.mark.django_db

ATUALIZADO = datetime(2026, 3, 5, 12, 0, tzinfo=ZoneInfo('America/Sao_Paulo'))
CABECALHO = 'Fazenda;Empresa;Município;Área (ha);Talhões;Situação;Atualizado\r\n'


def _linha(fazenda, area=None, talhoes=2):
    return LinhaFazenda(fazenda=fazenda, area=area, talhoes=talhoes, atualizado=ATUALIZADO)


def _lido(texto):
    """Células de cada linha, como o Excel as separaria (`;`), depois do BOM."""
    assert texto.startswith('﻿')
    return list(csv.reader(io.StringIO(texto[1:]), delimiter=';'))


def test_neutraliza_celula_que_comeca_com_formula_e_so_ela():
    for celula in ('=SOMA(1)', '+1', '-1', '@x', '\tx', '\rx', '\nx'):
        assert neutralizar(celula) == "'" + celula
    assert neutralizar('Fazenda Sol') == 'Fazenda Sol'
    assert neutralizar('a=b') == 'a=b'  # sinal no meio do texto não é fórmula
    assert neutralizar('') == ''


def test_csv_feliz_cabecalho_separador_bom_e_formatos(cenario):
    texto = csv_das_fazendas([_linha(cenario.f1, area=12.5, talhoes=3)])
    assert texto == '﻿' + CABECALHO + 'F1;Empresa X;Sem dados;12,50;3;Ativa;05/03/2026\r\n'
    assert texto.encode('utf-8')[:3] == b'\xef\xbb\xbf'


def test_ausente_vira_sem_dados_e_zero_de_talhao_continua_zero(cenario):
    # municipio vazio e área None são "não informado"; talhão 0 é contagem real.
    texto = csv_das_fazendas([_linha(cenario.f2, area=None, talhoes=0)])
    assert _lido(texto)[1] == ['F2', 'Empresa X', 'Sem dados', 'Sem dados', '0', 'Ativa', '05/03/2026']


def test_arquivada_aparece_como_arquivada(cenario):
    from django.utils import timezone

    cenario.f2.arquivada_em = timezone.now()
    texto = csv_das_fazendas([_linha(cenario.f2)])
    assert _lido(texto)[1][5] == 'Arquivada'


def test_injecao_de_formula_em_nome_e_municipio_nao_vira_formula(cenario):
    from territorio.models import Fazenda

    Fazenda.objects.filter(pk=cenario.f1.pk).update(nome='=HYPERLINK("http://x")', municipio='+CMD|x')
    cenario.f1.refresh_from_db()
    celulas = _lido(csv_das_fazendas([_linha(cenario.f1)]))[1]
    assert celulas[0] == "'=HYPERLINK(\"http://x\")"
    assert celulas[2] == "'+CMD|x"


def test_registrar_exportacao_grava_um_evento_por_empresa_sem_busca(cenario, plataforma):
    registrar_exportacao(plataforma, [_linha(cenario.f1), _linha(cenario.f2), _linha(cenario.fy)])
    eventos = EventoAuditoria.objects.filter(acao='dados_exportados').order_by('empresa_id')
    assert [(e.empresa_id, e.detalhes) for e in eventos] == [
        (cenario.x.pk, {'quantidade': 2}),
        (cenario.y.pk, {'quantidade': 1}),
    ]


def test_registrar_exportacao_sem_linhas_nao_grava_evento(cenario, plataforma):
    registrar_exportacao(plataforma, [])
    assert not EventoAuditoria.objects.filter(acao='dados_exportados').exists()


def test_rotulo_do_evento_de_exportacao_em_portugues():
    assert rotulo_e_resumo('dados_exportados', {'quantidade': 3}) == ('Dados exportados', '3 fazendas exportadas em CSV.')
    assert rotulo_e_resumo('dados_exportados', {}) == ('Dados exportados', ' fazendas exportadas em CSV.')


def test_modulo_expoe_so_o_que_a_matriz_cobre():
    assert {'neutralizar', 'csv_das_fazendas', 'registrar_exportacao'} <= set(vars(exportacao))
