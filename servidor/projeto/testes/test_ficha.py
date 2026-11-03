"""Contrato de encaixe do mapa (003 R22, R23; A14): `contrato_mapa.md`, `ficha.py` e as regiões de `regiao.html`."""

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.template.loader import render_to_string

from projeto.ficha import CAMPOS, SEM_INFORMACAO, SITUACOES, montar_ficha

PROJETO = Path(__file__).resolve().parent.parent
CONTRATO = PROJETO / 'contrato_mapa.md'

# Dado sintético: nome, valor e fonte inventados; nenhuma camada real existe ainda para popular.
SINTETICO = {
    'camada': 'Camada Sintetica 1', 'atributo': 'Atributo Sintetico', 'valor': 12.5, 'unidade': 'ha',
    'fonte': 'Fonte Sintetica', 'data': date(2026, 1, 15), 'situacao': 'vigente', 'ressalva': 'Ressalva sintetica.',
    'origem': 'medicao', 'metodo': None,
}
ESTIMATIVA = {**SINTETICO, 'origem': 'estimativa', 'metodo': 'Interpolacao sintetica'}


def test_o_contrato_lista_exatamente_os_campos_do_codigo():
    campos = re.findall(r'^\| `(\w+)` \|', CONTRATO.read_text(encoding='utf-8'), re.M)
    assert list(CAMPOS) == campos


@pytest.mark.parametrize('campo', CAMPOS)
def test_registro_sem_um_campo_do_contrato_e_recusado(campo):
    registro = {chave: valor for chave, valor in SINTETICO.items() if chave != campo}
    with pytest.raises(ValueError, match=campo):
        montar_ficha(registro)


def test_ficha_sintetica_traz_cada_campo_em_texto():
    assert montar_ficha(SINTETICO) == {
        'camada': 'Camada Sintetica 1', 'atributo': 'Atributo Sintetico', 'valor': '12,5 ha', 'fonte': 'Fonte Sintetica',
        'data': '15/01/2026', 'situacao': 'Vigente', 'ressalva': 'Ressalva sintetica.', 'origem': 'Medição de campo',
        'metodo': SEM_INFORMACAO,
    }


def test_decimal_sai_com_virgula_na_lingua_do_produto():
    assert montar_ficha({**SINTETICO, 'valor': Decimal('3.25')})['valor'] == '3,25 ha'


def test_zero_medido_aparece_como_zero_e_ausente_como_sem_informacao():
    assert montar_ficha({**SINTETICO, 'valor': 0})['valor'] == '0 ha'
    ausente = montar_ficha({**SINTETICO, 'valor': None, 'fonte': None, 'data': None, 'ressalva': ''})
    assert (SEM_INFORMACAO,) * 4 == (ausente['valor'], ausente['fonte'], ausente['data'], ausente['ressalva'])


@pytest.mark.parametrize('vazio', [None, ''])
def test_valor_vazio_nao_mostra_so_a_unidade(vazio):
    assert montar_ficha({**SINTETICO, 'valor': vazio})['valor'] == SEM_INFORMACAO


def test_valor_sem_unidade_nao_inventa_unidade():
    assert montar_ficha({**SINTETICO, 'unidade': None})['valor'] == '12,5 (sem informação de unidade)'


def test_estimativa_nunca_se_rotula_como_medicao_e_mostra_o_metodo():
    ficha = montar_ficha(ESTIMATIVA)
    assert (ficha['origem'], ficha['metodo']) == ('Estimativa', 'Interpolacao sintetica')


@pytest.mark.parametrize('metodo', [None, ''])
def test_estimativa_sem_metodo_e_recusada(metodo):
    with pytest.raises(ValueError, match='sem método'):
        montar_ficha({**ESTIMATIVA, 'metodo': metodo})


@pytest.mark.parametrize(('campo', 'valor'), [('situacao', 'rascunho'), ('origem', 'palpite')])
def test_situacao_e_origem_fora_da_lista_sao_recusadas(campo, valor):
    with pytest.raises(ValueError, match=valor):
        montar_ficha({**SINTETICO, campo: valor})


@pytest.mark.parametrize(
    ('campo', 'valor'),
    [('valor', True), ('valor', [1]), ('data', '2026-01-15'), ('fonte', 7), ('camada', ['a'])],
)
def test_tipo_fora_do_contrato_e_recusado(campo, valor):
    with pytest.raises(ValueError, match=campo):
        montar_ficha({**SINTETICO, campo: valor})


@pytest.mark.parametrize('situacao', SITUACOES)
def test_ficha_renderiza_cada_campo_como_texto_visivel(situacao):
    html = render_to_string('componentes/ficha.html', {'ficha': montar_ficha({**ESTIMATIVA, 'situacao': situacao})})
    for texto in (situacao.capitalize(), 'Ressalva sintetica.', 'Camada Sintetica 1', 'Atributo Sintetico', 'Fonte Sintetica', 'Interpolacao sintetica'):
        assert texto in html
    assert 'title=' not in html  # ficha e ressalva nunca em tooltip (R22)


@pytest.mark.parametrize(
    ('estado', 'esperado'),
    [
        ('vazio', 'Sem camadas ainda.'), ('carregando', 'Carregando…'), ('erro', 'Não foi possível carregar esta região.'),
        ('sem_permissao', 'Você não tem permissão para ver esta região.'), ('sem_informacao', 'Sem informação.'),
        ('inventado', 'Estado de região fora do contrato.'),
    ],
)
def test_regiao_tem_um_texto_proprio_para_cada_estado_e_estado_desconhecido_e_erro(estado, esperado):
    texto = 'Sem camadas ainda.' if estado == 'vazio' else ''
    html = render_to_string('componentes/regiao.html', {'id': 'camadas', 'titulo': 'Camadas', 'estado': estado, 'texto': texto})
    assert esperado in html
    assert '>0<' not in html  # sem informação nunca vira zero


def test_carregando_usa_output_erro_e_anunciado_e_titulo_fica_fora_do_summary():
    carregando = render_to_string('componentes/regiao.html', {'id': 'ficha', 'titulo': 'Ficha', 'estado': 'carregando'})
    assert '<output class="regiao-carregando">Carregando…</output>' in carregando
    erro = render_to_string('componentes/regiao.html', {'id': 'ficha', 'titulo': 'Ficha', 'estado': 'erro', 'recolhivel': True})
    assert 'role="alert"' in erro
    assert '<h2 class="regiao-titulo" id="regiao-ficha-titulo">Ficha</h2>' in erro
    assert '<details class="regiao-recolhivel" open><summary>Mostrar ou ocultar ficha</summary>' in erro  # h2 em summary perde o papel de título
    fixa = render_to_string('componentes/regiao.html', {'id': 'mapa', 'titulo': 'Mapa', 'estado': 'vazio', 'texto': 'x'})
    assert '<details' not in fixa


def test_cor_de_camada_mora_so_em_camadas_css():
    estaticos = PROJETO / 'static' / 'projeto'
    assert 'camada' not in (estaticos / 'tokens.css').read_text(encoding='utf-8')
    assert '--cor-camada-provisoria-1' in (estaticos / 'camadas.css').read_text(encoding='utf-8')


def test_regioes_so_viram_duas_colunas_com_o_menu_lateral_ja_descontado():
    css = (PROJETO / 'static' / 'projeto' / 'componentes.css').read_text(encoding='utf-8')
    assert re.search(r'@media \(min-width: 64rem\) \{\s*\.regioes \{ grid-template-columns', css)
