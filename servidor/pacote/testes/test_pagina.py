"""Dados do pacote na página da fazenda (004b R7, R8, R11): a web monta o fundo próprio sem passar pelo manifesto (que pede
`baixar_pacote_offline`), com a mesma regra dos arquivos (`ver` na fazenda inteira)."""

from django.test import override_settings

from pacote.models import VersaoPacote
from pacote.pagina import fundo_da_pagina

URL_FUNDO = '/empresa/{}/fazenda/{}/pacote/arquivo/fundo.pmtiles?versao=1'
PAGINA = '/empresa/{}/fazenda/{}/'


def _pessoa(entrar, cargo, escopo):
    """Cliente logado e a `Pessoa` dele."""
    cliente = entrar(cargo, escopo)
    return cliente, getattr(cliente, 'pessoa')


def test_com_pacote_devolve_urls_da_versao_vigente_e_a_data_da_ortofoto(entrar, cenario, referencia_instalada):
    _, pessoa = _pessoa(entrar, cenario.cargos_x['usuario'], cenario.f1)
    dados = fundo_da_pagina(pessoa, cenario.f1)
    assert dados is not None
    assert dados['fundo'] == URL_FUNDO.format(cenario.x.pk, cenario.f1.pk)
    assert dados['ortofoto'].endswith('/arquivo/ortofoto.pmtiles?versao=1')
    assert dados['atribuicao'] == '© OpenStreetMap contributors'
    assert dados['ortofoto_capturada_em'] == '2026-01-15'


def test_quem_so_ve_recebe_as_urls_sem_baixar_pacote_offline(entrar, cenario, cargo_so_ver, referencia_instalada):
    _, pessoa = _pessoa(entrar, cargo_so_ver, cenario.f1)
    assert fundo_da_pagina(pessoa, cenario.f1) is not None  # D097: quem tem `ver` lê os bytes do fundo e da ortofoto


def test_sem_pacote_vigente_devolve_none(entrar, cenario, pacotes):
    _, pessoa = _pessoa(entrar, cenario.cargos_x['usuario'], cenario.f1)
    assert fundo_da_pagina(pessoa, cenario.f1) is None


def test_versao_que_nao_e_vigente_nao_aparece(entrar, cenario, referencia_instalada):
    VersaoPacote.objects.filter(pk=referencia_instalada.pk).update(vigente=False)
    _, pessoa = _pessoa(entrar, cenario.cargos_x['usuario'], cenario.f1)
    assert fundo_da_pagina(pessoa, cenario.f1) is None


def test_so_sub_area_nao_recebe_url_nenhuma(entrar, cenario, referencia_instalada):
    _, pessoa = _pessoa(entrar, cenario.cargos_x['usuario'], cenario.g1)
    assert fundo_da_pagina(pessoa, cenario.f1) is None


def test_de_outra_empresa_nao_recebe(entrar, cenario, referencia_instalada):
    _, pessoa = _pessoa(entrar, cenario.cargos_y['administrador'], cenario.y)
    assert fundo_da_pagina(pessoa, cenario.f1) is None


def test_manifesto_quebrado_vira_none_e_nao_erro(entrar, cenario, referencia_instalada):
    VersaoPacote.objects.filter(pk=referencia_instalada.pk).update(manifesto={'formato_versao': 99})
    _, pessoa = _pessoa(entrar, cenario.cargos_x['usuario'], cenario.f1)
    assert fundo_da_pagina(pessoa, cenario.f1) is None


def test_pacote_sem_fundo_vira_none(entrar, cenario, referencia_instalada):
    manifesto = dict(referencia_instalada.manifesto)
    manifesto['arquivos'] = [a for a in manifesto['arquivos'] if a['papel'] != 'fundo']
    VersaoPacote.objects.filter(pk=referencia_instalada.pk).update(manifesto=manifesto)
    _, pessoa = _pessoa(entrar, cenario.cargos_x['usuario'], cenario.f1)
    assert fundo_da_pagina(pessoa, cenario.f1) is None


def test_pacote_so_com_fundo_nao_leva_ortofoto(entrar, cenario, referencia_instalada):
    manifesto = dict(referencia_instalada.manifesto)
    manifesto['arquivos'] = [a for a in manifesto['arquivos'] if a['papel'] == 'fundo']
    VersaoPacote.objects.filter(pk=referencia_instalada.pk).update(manifesto=manifesto)
    _, pessoa = _pessoa(entrar, cenario.cargos_x['usuario'], cenario.f1)
    dados = fundo_da_pagina(pessoa, cenario.f1)
    assert dados is not None and dados['ortofoto'] is None and dados['ortofoto_capturada_em'] == ''


@override_settings(MAPA_TESTE_ATIVO=True)
def test_pagina_com_a_flag_leva_o_fundo_nos_atributos(entrar, cenario, referencia_instalada):
    cliente, _ = _pessoa(entrar, cenario.cargos_x['usuario'], cenario.f1)
    html = cliente.get(PAGINA.format(cenario.x.pk, cenario.f1.pk)).content.decode()
    assert f'data-pacote-fundo="{URL_FUNDO.format(cenario.x.pk, cenario.f1.pk)}"' in html
    assert 'data-pacote-ortofoto-data="2026-01-15"' in html
    assert 'estilo_base' in html
    assert 'data-atribuicao-aberta' in html


@override_settings(MAPA_TESTE_ATIVO=True)
def test_pagina_de_quem_so_tem_sub_area_nao_vaza_url_do_pacote(entrar, cenario, referencia_instalada):
    cliente, _ = _pessoa(entrar, cenario.cargos_x['usuario'], cenario.g1)
    resposta = cliente.get(PAGINA.format(cenario.x.pk, cenario.f1.pk))
    html = resposta.content.decode()
    assert 'pacote/arquivo' not in html and 'data-pacote-fundo' not in html


@override_settings(MAPA_TESTE_ATIVO=False)
def test_pagina_com_a_flag_desligada_nao_leva_pacote(entrar, cenario, referencia_instalada):
    cliente, _ = _pessoa(entrar, cenario.cargos_x['usuario'], cenario.f1)
    html = cliente.get(PAGINA.format(cenario.x.pk, cenario.f1.pk)).content.decode()
    assert 'data-pacote' not in html
