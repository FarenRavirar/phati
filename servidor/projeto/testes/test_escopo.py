"""Escopo na URL (R3, D063, A6): inexistente, de outra empresa e sem permissão dão o mesmo 404."""

import pytest
from django.http import Http404

from projeto.escopo import resolver_escopo


def _administrador_de_x(cenario, fabrica_pessoa, conceder_direto):
    pessoa = fabrica_pessoa('Admin')
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.x)
    return pessoa


def test_administrador_da_empresa_resolve_a_empresa_e_a_fazenda(cenario, fabrica_pessoa, conceder_direto):
    pessoa = _administrador_de_x(cenario, fabrica_pessoa, conceder_direto)
    assert resolver_escopo(pessoa, cenario.x.pk) == (cenario.x, None)
    assert resolver_escopo(pessoa, cenario.x.pk, cenario.f1.pk) == (cenario.x, cenario.f1)


def test_plataforma_resolve_qualquer_empresa(cenario, plataforma):
    assert resolver_escopo(plataforma, cenario.y.pk, cenario.fy.pk) == (cenario.y, cenario.fy)


def test_acesso_so_a_fazenda_resolve_a_fazenda_e_a_empresa_dela(cenario, fabrica_pessoa, conceder_direto):
    pessoa = fabrica_pessoa('Usuaria')
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    assert resolver_escopo(pessoa, cenario.x.pk, cenario.f1.pk) == (cenario.x, cenario.f1)
    with pytest.raises(Http404):
        resolver_escopo(pessoa, cenario.x.pk, cenario.f2.pk)  # irmã sem concessão


def test_administrador_da_empresa_x_recebe_o_mesmo_404_de_inexistente_para_tudo_de_fora(cenario, fabrica_pessoa, conceder_direto):
    pessoa = _administrador_de_x(cenario, fabrica_pessoa, conceder_direto)
    inexistente = 999_999
    pedidos = [
        (inexistente, None),
        (cenario.y.pk, None),  # empresa de outro escopo
        (cenario.y.pk, cenario.fy.pk),
        (cenario.x.pk, inexistente),
        (cenario.x.pk, cenario.fy.pk),  # fazenda de outra empresa dentro da URL da minha
    ]
    for empresa_id, fazenda_id in pedidos:
        with pytest.raises(Http404) as erro:
            resolver_escopo(pessoa, empresa_id, fazenda_id)
        assert str(erro.value) == ''  # mesmo corpo para inexistente e proibido: nada revela existência


def test_pessoa_sem_concessao_recebe_404_em_tudo(cenario, fabrica_pessoa):
    pessoa = fabrica_pessoa('Sem acesso')
    for empresa_id, fazenda_id in [(cenario.x.pk, None), (cenario.x.pk, cenario.f1.pk), (cenario.y.pk, cenario.fy.pk)]:
        with pytest.raises(Http404):
            resolver_escopo(pessoa, empresa_id, fazenda_id)


def test_escopo_arquivado_ainda_resolve_para_leitura_por_url_direta(cenario, plataforma):
    from territorio.cadastro import arquivar

    arquivar(plataforma, cenario.f1)
    empresa, fazenda = resolver_escopo(plataforma, cenario.x.pk, cenario.f1.pk)
    assert fazenda is not None
    assert (empresa.pk, fazenda.pk, fazenda.arquivada_em is not None) == (cenario.x.pk, cenario.f1.pk, True)
    arquivar(plataforma, cenario.x)
    assert resolver_escopo(plataforma, cenario.x.pk)[0].arquivada_em is not None
