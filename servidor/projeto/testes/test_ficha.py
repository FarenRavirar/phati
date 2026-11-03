"""Contrato de encaixe do mapa (003 R22, R23; A14): `contrato_mapa.md`, `ficha.py` e as regiões de `regiao.html`."""

import re
from datetime import date
from pathlib import Path

import pytest
from django.template.loader import render_to_string

from projeto.ficha import CAMPOS, SEM_INFORMACAO, SITUACOES, montar_ficha

CONTRATO = Path(__file__).resolve().parent.parent / 'contrato_mapa.md'

# Dado sintético: nome, valor e fonte inventados; nenhuma camada real existe ainda para popular.
SINTETICO = {
    'camada': 'Camada Sintetica 1', 'atributo': 'Atributo Sintetico', 'valor': 12.5, 'unidade': 'ha',
    'fonte': 'Fonte Sintetica', 'data': date(2026, 1, 15), 'situacao': 'vigente', 'ressalva': 'Ressalva sintetica.',
    'origem': 'medicao',
}


def test_o_contrato_lista_exatamente_os_campos_do_codigo():
    campos = re.findall(r'^\| `(\w+)` \|', CONTRATO.read_text(encoding='utf-8'), re.M)
    assert campos == list(CAMPOS)


@pytest.mark.parametrize('campo', CAMPOS)
def test_registro_sem_um_campo_do_contrato_e_recusado(campo):
    registro = {chave: valor for chave, valor in SINTETICO.items() if chave != campo}
    with pytest.raises(ValueError, match=campo):
        montar_ficha(registro)


def test_ficha_sintetica_traz_cada_campo_em_texto():
    ficha = montar_ficha(SINTETICO)
    assert ficha['valor'] == '12.5 ha'
    assert (ficha['data'], ficha['situacao'], ficha['origem']) == ('15/01/2026', 'Vigente', 'Medição de campo')


def test_zero_medido_aparece_como_zero_e_ausente_como_sem_informacao():
    assert montar_ficha({**SINTETICO, 'valor': 0})['valor'] == '0 ha'
    ausente = montar_ficha({**SINTETICO, 'valor': None, 'fonte': None, 'data': None, 'ressalva': ''})
    assert (ausente['valor'], ausente['fonte'], ausente['data'], ausente['ressalva']) == (SEM_INFORMACAO,) * 4
    assert '0' not in ausente['valor']


def test_valor_sem_unidade_nao_inventa_unidade():
    assert montar_ficha({**SINTETICO, 'unidade': None})['valor'] == '12.5 (sem informação de unidade)'


def test_estimativa_nunca_se_rotula_como_medicao():
    assert montar_ficha({**SINTETICO, 'origem': 'estimativa'})['origem'] == 'Estimativa'


@pytest.mark.parametrize(('campo', 'valor'), [('situacao', 'rascunho'), ('origem', 'palpite')])
def test_situacao_e_origem_fora_da_lista_sao_recusadas(campo, valor):
    with pytest.raises(ValueError, match=valor):
        montar_ficha({**SINTETICO, campo: valor})


@pytest.mark.parametrize('situacao', SITUACOES)
def test_ficha_renderiza_a_situacao_e_a_ressalva_como_texto_visivel(situacao):
    html = render_to_string('componentes/ficha.html', {'ficha': montar_ficha({**SINTETICO, 'situacao': situacao})})
    assert situacao.capitalize() in html
    assert 'Ressalva sintetica.' in html
    assert 'title=' not in html  # ficha e ressalva nunca em tooltip (R22)


@pytest.mark.parametrize(
    ('estado', 'esperado'),
    [
        ('vazio', 'Sem camadas ainda.'), ('carregando', 'Carregando…'), ('erro', 'Não foi possível carregar esta região.'),
        ('sem_permissao', 'Você não tem permissão para ver esta região.'), ('sem_informacao', 'Sem informação.'),
    ],
)
def test_regiao_tem_um_texto_proprio_para_cada_estado(estado, esperado):
    html = render_to_string('componentes/regiao.html', {'id': 'camadas', 'titulo': 'Camadas', 'estado': estado, 'texto': 'Sem camadas ainda.' if estado == 'vazio' else ''})
    assert esperado in html
    assert '>0<' not in html  # sem informação nunca vira zero


def test_erro_e_anunciado_e_painel_recolhivel_usa_details():
    erro = render_to_string('componentes/regiao.html', {'id': 'ficha', 'titulo': 'Ficha', 'estado': 'erro', 'recolhivel': True})
    assert 'role="alert"' in erro
    assert '<details class="regiao-recolhivel" open><summary>' in erro
    assert '<details' not in render_to_string('componentes/regiao.html', {'id': 'mapa', 'titulo': 'Mapa', 'estado': 'vazio', 'texto': 'x'})


def test_cor_de_camada_mora_so_em_camadas_css():
    estaticos = Path(__file__).resolve().parent.parent / 'static' / 'projeto'
    assert 'camada' not in (estaticos / 'tokens.css').read_text(encoding='utf-8')
    assert '--cor-camada-provisoria-1' in (estaticos / 'camadas.css').read_text(encoding='utf-8')
