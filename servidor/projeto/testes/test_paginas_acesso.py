"""Métodos aceitos e cabeçalhos das páginas de acesso (R4 a R7): nenhuma guarda cache e cada rota recusa o método errado."""

import pytest
from django.test import Client


@pytest.mark.parametrize('caminho', ['/entrar', '/esqueci-senha'])
def test_paginas_publicas_nao_ficam_em_cache(caminho):
    assert 'no-store' in Client().get(caminho)['Cache-Control']


@pytest.mark.parametrize(('caminho', 'metodo'), [
    ('/entrar', 'put'), ('/entrar', 'delete'), ('/esqueci-senha', 'put'), ('/trocar-senha', 'put'), ('/sair', 'put'), ('/sair', 'get'),
])
def test_metodo_fora_da_lista_da_405(caminho, metodo):
    assert getattr(Client(), metodo)(caminho).status_code == 405


def test_pagina_de_troca_nao_fica_em_cache(cliente_logado):
    assert 'no-store' in cliente_logado.get('/trocar-senha')['Cache-Control']
