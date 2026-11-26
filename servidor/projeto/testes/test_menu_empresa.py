"""Menu com a empresa escolhida (R15, R16): Pessoas e Cargos só com o alcance da tela, um só item atual, trilha do topo e
atalhos do Início que seguem a empresa escolhida. Negativos: usuário, empresa sem acesso e sem escolha."""

import pytest

from projeto.menu import atalhos_da_pessoa, itens_do_menu, trilha_da


def _itens(pessoa, empresa=None, caminho=None):
    return itens_do_menu(pessoa, empresa, caminho, empresa=empresa)


def _nomes(pessoa, empresa=None):
    return [item.nome for item in _itens(pessoa, empresa)]


def test_administrador_da_empresa_ve_pessoas_e_cargos_na_ordem_da_gestao(cenario, fabrica_pessoa, conceder_direto):
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.x)
    assert _nomes(pessoa, cenario.x) == ['Início', 'Fazendas', 'Pessoas', 'Cargos', 'Auditoria']


def test_administrador_so_de_fazenda_ve_pessoas_mas_nao_cargos(cenario, fabrica_pessoa, conceder_direto):
    # Cargo é da empresa inteira (003 R18): quem o administra só numa fazenda não vê o item, como a tela recusa.
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.f1)
    nomes = _nomes(pessoa, cenario.x)
    assert 'Pessoas' in nomes
    assert 'Cargos' not in nomes


def test_usuario_nao_ve_gestao_mesmo_com_empresa_escolhida(cenario, fabrica_pessoa, conceder_direto):
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    assert _nomes(pessoa, cenario.x) == ['Início', 'Fazendas']


def test_sem_empresa_escolhida_nao_ha_pessoas_nem_cargos(cenario, fabrica_pessoa, conceder_direto):
    # Com duas empresas alcançadas, não há escolha padrão: sem a escolhida, Pessoas e Cargos somem.
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.x)
    conceder_direto(pessoa, cenario.cargos_y['usuario'], cenario.y)
    assert _nomes(pessoa) == ['Início', 'Fazendas', 'Auditoria']  # Auditoria é da empresa, não da escolha: aparece sem empresa


def test_empresa_sem_acesso_nao_abre_pessoas_nem_cargos(cenario, fabrica_pessoa, conceder_direto):
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.x)
    assert 'Pessoas' not in _nomes(pessoa, cenario.y)
    assert 'Cargos' not in _nomes(pessoa, cenario.y)


def test_plataforma_ve_pessoas_e_cargos_em_qualquer_empresa(cenario, plataforma):
    assert {'Pessoas', 'Cargos'} <= set(_nomes(plataforma, cenario.y))


@pytest.mark.parametrize(
    ('sufixo', 'esperado'),
    [
        ('pessoas/', {'Pessoas': 'page'}),
        ('pessoas/convidar', {'Pessoas': 'true'}),
        ('pessoa/9/revogar/3', {'Pessoas': 'true'}),
        ('cargos/', {'Cargos': 'page'}),
        ('cargos/novo', {'Cargos': 'true'}),
        ('', {'Fazendas': 'true'}),
        ('fazenda/1/', {'Fazendas': 'true'}),
    ],
)
def test_so_um_item_fica_atual_e_fazendas_nao_marca_as_telas_de_gestao(cenario, fabrica_pessoa, conceder_direto, sufixo, esperado):
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.x)
    atuais = {item.nome: item.atual for item in _itens(pessoa, cenario.x, f'/empresa/{cenario.x.pk}/{sufixo}') if item.atual}
    assert atuais == esperado


def test_trilha_de_pessoas_leva_o_grupo_e_a_pagina(cenario, fabrica_pessoa, conceder_direto):
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.x)
    itens = _itens(pessoa, cenario.x, f'/empresa/{cenario.x.pk}/pessoas/')
    assert trilha_da(itens, cenario.x) == ['Gestão', 'Pessoas']


def test_trilha_de_fazendas_leva_a_empresa_ou_a_fazenda(cenario, fabrica_pessoa, conceder_direto):
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    na_empresa = _itens(pessoa, cenario.x, f'/empresa/{cenario.x.pk}/')
    na_fazenda = _itens(pessoa, cenario.f1, f'/empresa/{cenario.x.pk}/fazenda/{cenario.f1.pk}/')
    assert trilha_da(na_empresa, cenario.x) == ['Fazendas', 'Empresa X']
    assert trilha_da(na_fazenda, cenario.f1, cenario.f1) == ['Fazendas', 'F1']


def test_trilha_fica_vazia_sem_item_atual(cenario, fabrica_pessoa):
    assert trilha_da(_itens(fabrica_pessoa('Pessoa'), None, '/convites/1/aceitar')) == []


def test_atalho_por_empresa_segue_a_empresa_escolhida(cenario, fabrica_pessoa, conceder_direto):
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.x)
    conceder_direto(pessoa, cenario.cargos_y['administrador'], cenario.y)
    convidar_x = f'/empresa/{cenario.x.pk}/pessoas/convidar'
    convidar_y = f'/empresa/{cenario.y.pk}/pessoas/convidar'
    escolhida, _, _ = atalhos_da_pessoa(pessoa, cenario.x)
    assert [a.caminho for a in escolhida if a.caminho.endswith('/pessoas/convidar')] == [convidar_x]
    sem_escolha, _, _ = atalhos_da_pessoa(pessoa)
    assert {a.caminho for a in sem_escolha if a.caminho.endswith('/pessoas/convidar')} == {convidar_x, convidar_y}


@pytest.mark.parametrize(
    ('caminho', 'esperado'),
    [
        ('/', ['Início']),
        ('/empresas/', ['Fazendas']),
        ('/empresa/{x}/cargos/', ['Gestão', 'Cargos']),
        ('/auditoria/', ['Gestão', 'Auditoria']),
        ('/monitor-google', ['Gestão', 'Uso do Google']),
    ],
)
def test_trilha_de_cada_pagina_do_menu_telas_secao_0(cenario, plataforma, caminho, esperado):
    # Uma linha por página de primeiro nível de telas.md §0 (a empresa e a fazenda têm teste próprio).
    itens = _itens(plataforma, cenario.x, caminho.format(x=cenario.x.pk))
    assert trilha_da(itens) == esperado


def test_trilha_de_pagina_que_o_menu_nao_mostra_fica_vazia(cenario, fabrica_pessoa, conceder_direto):
    # Uso do Google é da plataforma: o administrador de empresa não vê o item, então a página não tem trilha de menu.
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.x)
    assert trilha_da(_itens(pessoa, cenario.x, '/monitor-google')) == []


def test_trilha_com_sub_area_e_etapa_leva_fazenda_e_o_que_esta_dentro(cenario, fabrica_pessoa, conceder_direto):
    pessoa = fabrica_pessoa('Pessoa')
    conceder_direto(pessoa, cenario.cargos_x['usuario'], cenario.f1)
    sub_area = _itens(pessoa, cenario.f1, f'/empresa/{cenario.x.pk}/fazenda/{cenario.f1.pk}/sub-area/{cenario.g1.pk}/')
    envio = _itens(pessoa, cenario.f1, f'/empresa/{cenario.x.pk}/fazenda/{cenario.f1.pk}/camadas/novo')
    assert trilha_da(sub_area, cenario.x, cenario.f1, cenario.g1) == ['Fazendas', 'F1', 'G1']
    assert trilha_da(envio, cenario.x, cenario.f1, etapa='Enviar camada') == ['Fazendas', 'F1', 'Enviar camada']


def test_sub_area_e_etapa_nao_entram_sem_fazenda_nem_fora_de_fazendas(cenario, fabrica_pessoa):
    pessoa = fabrica_pessoa('Pessoa')
    assert trilha_da(_itens(pessoa, cenario.x, f'/empresa/{cenario.x.pk}/'), cenario.x, None, cenario.g1, 'Enviar camada') == ['Fazendas', 'Empresa X']
    assert trilha_da(_itens(pessoa, None, '/'), None, None, cenario.g1, 'Enviar camada') == ['Início']
