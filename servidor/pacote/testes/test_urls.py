"""Rotas do pacote (004b R3, R18): nomes, caminhos e conversores."""

import pytest
from django.urls import Resolver404, resolve, reverse

ARGS = {'empresa_id': 3, 'fazenda_id': 7}


def test_as_tres_rotas_existem_sob_a_fazenda():
    assert reverse('pacote_manifesto', kwargs=ARGS) == '/empresa/3/fazenda/7/pacote/manifesto.json'
    assert reverse('pacote_camadas', kwargs=ARGS) == '/empresa/3/fazenda/7/pacote/camadas.geojson'
    assert reverse('pacote_arquivo', kwargs={**ARGS, 'nome': 'fundo.pmtiles'}) == '/empresa/3/fazenda/7/pacote/arquivo/fundo.pmtiles'


def test_o_nome_do_arquivo_nunca_atravessa_diretorio_pela_url():
    # `<str:nome>` não casa barra: `..%2F` decodificado vira outro caminho e cai fora da rota.
    with pytest.raises(Resolver404):
        resolve('/empresa/3/fazenda/7/pacote/arquivo/../../x.pmtiles')
    with pytest.raises(Resolver404):
        resolve('/empresa/3/fazenda/7/pacote/arquivo/a/b.pmtiles')
    assert resolve('/empresa/3/fazenda/7/pacote/arquivo/fundo.pmtiles').url_name == 'pacote_arquivo'


def test_id_que_nao_e_numero_nao_casa():
    with pytest.raises(Resolver404):
        resolve('/empresa/abc/fazenda/7/pacote/manifesto.json')
