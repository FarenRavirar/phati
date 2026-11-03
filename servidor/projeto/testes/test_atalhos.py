"""Atalhos do Início por frequência (003 R27, A16): fixos do papel, os fixados e até dois por frequência, sempre pela permissão
atual e só com o uso da própria pessoa."""

from datetime import timedelta

import pytest
from django.utils import timezone

from permissao.models import Concessao, UsoAcao
from permissao.pode import esquecer
from permissao.uso import definir_estado, registrar_uso
from projeto import menu
from projeto.menu import Atalho, atalhos_da_pessoa

CONVIDAR = Atalho('Convidar pessoa', '/empresa/{empresa_id}/pessoas/convidar', 'convidar_pessoa')
CARGOS = Atalho('Cargos', '/empresa/{empresa_id}/cargos/', 'gerenciar_cargo', fixo=False)
FAZENDA = Atalho('Cadastrar fazenda', '/empresa/{empresa_id}/fazenda/nova', 'criar_fazenda', fixo=False)
SUB_AREA = Atalho('Cadastrar sub-área', '/empresa/{empresa_id}/sub-area', 'criar_sub_area', fixo=False)


@pytest.fixture
def administrador(cenario, fabrica_pessoa, conceder_direto):
    pessoa = fabrica_pessoa('Administradora')
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.x)
    return pessoa


def _usar(pessoa, acao, vezes):
    for _ in range(vezes):
        registrar_uso(pessoa, acao)


def _nomes(pessoa):
    mostrados, _, _ = atalhos_da_pessoa(pessoa)
    return [a.nome for a in mostrados]


def test_sem_historico_vale_so_a_ordem_fixa(administrador, monkeypatch):
    monkeypatch.setattr(menu, 'ATALHOS', (CONVIDAR, CARGOS, FAZENDA))
    mostrados, ocultos, _ = atalhos_da_pessoa(administrador)
    assert [a.nome for a in mostrados] == ['Convidar pessoa']
    assert ocultos == []


def test_a16_acao_que_ja_e_fixa_nao_se_repete_e_a_frequente_vem_depois(administrador, monkeypatch):
    monkeypatch.setattr(menu, 'ATALHOS', (CONVIDAR, CARGOS, FAZENDA))
    _usar(administrador, 'criar_fazenda', 5)
    _usar(administrador, 'convidar_pessoa', 9)
    assert _nomes(administrador) == ['Convidar pessoa', 'Cadastrar fazenda']


def test_nunca_mais_de_dois_por_frequencia_e_vence_a_de_maior_contagem(administrador, monkeypatch):
    monkeypatch.setattr(menu, 'ATALHOS', (CONVIDAR, CARGOS, FAZENDA, SUB_AREA))
    _usar(administrador, 'gerenciar_cargo', 2)
    _usar(administrador, 'criar_fazenda', 5)
    _usar(administrador, 'criar_sub_area', 3)
    assert _nomes(administrador) == ['Convidar pessoa', 'Cadastrar fazenda', 'Cadastrar sub-área']


def test_empate_de_contagem_vence_o_uso_mais_recente(administrador, monkeypatch):
    monkeypatch.setattr(menu, 'ATALHOS', (CARGOS, FAZENDA, SUB_AREA))
    _usar(administrador, 'gerenciar_cargo', 1)
    _usar(administrador, 'criar_fazenda', 1)
    _usar(administrador, 'criar_sub_area', 1)
    # O relógio do Windows é grosseiro: datas distintas à mão, senão o empate dependeria da velocidade do teste.
    for deslocamento, acao in enumerate(('gerenciar_cargo', 'criar_fazenda', 'criar_sub_area')):
        UsoAcao.objects.filter(pessoa=administrador, acao=acao).update(ultimo_uso=timezone.now() + timedelta(seconds=deslocamento))
    assert _nomes(administrador) == ['Cadastrar sub-área', 'Cadastrar fazenda']


def test_empate_total_segue_a_ordem_dos_atalhos(administrador, monkeypatch):
    monkeypatch.setattr(menu, 'ATALHOS', (CARGOS, FAZENDA, SUB_AREA))
    _usar(administrador, 'criar_sub_area', 1)
    _usar(administrador, 'criar_fazenda', 1)
    _usar(administrador, 'gerenciar_cargo', 1)
    UsoAcao.objects.filter(pessoa=administrador).update(ultimo_uso=timezone.now())
    assert _nomes(administrador) == ['Cargos', 'Cadastrar fazenda']


def test_permissao_revogada_tira_o_atalho_mesmo_com_uso(cenario, fabrica_pessoa, conceder_direto, monkeypatch):
    monkeypatch.setattr(menu, 'ATALHOS', (CONVIDAR, CARGOS))
    usuario = fabrica_pessoa('Usuaria')
    concessao = conceder_direto(usuario, cenario.cargos_x['administrador'], cenario.x)
    _usar(usuario, 'gerenciar_cargo', 4)
    assert _nomes(usuario) == ['Convidar pessoa', 'Cargos']
    Concessao.objects.filter(pk=concessao.pk).update(revogada_em=timezone.now(), revogada_por=usuario)
    esquecer(usuario)  # a memória de permissão vale uma requisição (D095, 7)
    assert _nomes(usuario) == []


def test_ocultar_tira_do_inicio_e_mostrar_devolve(administrador, monkeypatch):
    monkeypatch.setattr(menu, 'ATALHOS', (CONVIDAR, CARGOS))
    _usar(administrador, 'gerenciar_cargo', 3)
    definir_estado(administrador, 'gerenciar_cargo', oculto=True)
    definir_estado(administrador, 'convidar_pessoa', oculto=True)
    mostrados, ocultos, _ = atalhos_da_pessoa(administrador)
    assert mostrados == []
    assert ocultos == [('convidar_pessoa', 'Convidar pessoa'), ('gerenciar_cargo', 'Cargos')]
    definir_estado(administrador, 'gerenciar_cargo', oculto=False)
    assert _nomes(administrador) == ['Cargos']


def test_fixar_mostra_sem_uso_e_vai_antes_dos_frequentes(administrador, monkeypatch):
    monkeypatch.setattr(menu, 'ATALHOS', (CONVIDAR, CARGOS, FAZENDA))
    _usar(administrador, 'criar_fazenda', 7)
    definir_estado(administrador, 'gerenciar_cargo', fixado=True)
    mostrados, _, _ = atalhos_da_pessoa(administrador)
    assert [(a.nome, a.fixado) for a in mostrados] == [('Convidar pessoa', False), ('Cargos', True), ('Cadastrar fazenda', False)]


def test_fixado_nao_ocupa_vaga_de_frequencia(administrador, monkeypatch):
    monkeypatch.setattr(menu, 'ATALHOS', (CONVIDAR, CARGOS, FAZENDA, SUB_AREA))
    definir_estado(administrador, 'gerenciar_cargo', fixado=True)
    _usar(administrador, 'criar_fazenda', 2)
    _usar(administrador, 'criar_sub_area', 1)
    assert _nomes(administrador) == ['Convidar pessoa', 'Cargos', 'Cadastrar fazenda', 'Cadastrar sub-área']


def test_o_uso_de_uma_pessoa_nao_aparece_para_outra(cenario, administrador, fabrica_pessoa, conceder_direto, monkeypatch):
    monkeypatch.setattr(menu, 'ATALHOS', (CONVIDAR, CARGOS))
    _usar(administrador, 'gerenciar_cargo', 8)
    outra = fabrica_pessoa('Outra administradora')
    conceder_direto(outra, cenario.cargos_x['administrador'], cenario.x)
    assert _nomes(outra) == ['Convidar pessoa']


def test_acao_por_empresa_conta_como_um_atalho_no_limite(cenario, administrador, conceder_direto, monkeypatch):
    monkeypatch.setattr(menu, 'ATALHOS', (CARGOS,))
    conceder_direto(administrador, cenario.cargos_y['administrador'], cenario.y)
    _usar(administrador, 'gerenciar_cargo', 2)
    assert sorted(_nomes(administrador)) == ['Cargos · Empresa X', 'Cargos · Empresa Y']


def test_a16_com_os_atalhos_reais_redefinir_senha_vem_por_frequencia(administrador):
    _usar(administrador, 'redefinir_senha', 5)
    _usar(administrador, 'convidar_pessoa', 9)
    assert _nomes(administrador) == ['Convidar pessoa', 'Redefinir senha']


def test_permissao_so_de_fazenda_nao_gera_atalho_de_destino_que_exige_a_empresa(cenario, fabrica_pessoa, conceder_direto):
    pessoa = fabrica_pessoa('Curadora de fazenda')
    conceder_direto(pessoa, cenario.cargos_x['administrador'], cenario.f1)
    _usar(pessoa, 'gerenciar_cargo', 3)
    _usar(pessoa, 'criar_fazenda', 3)
    _usar(pessoa, 'convidar_pessoa', 3)
    mostrados, _, disponiveis = atalhos_da_pessoa(pessoa)
    assert [a.acao for a in mostrados] == ['convidar_pessoa']  # a página de cargos e a de nova fazenda dariam 403
    assert disponiveis == []


def test_redefinir_senha_so_aparece_para_administrador_da_empresa(cenario, fabrica_pessoa, conceder_direto):
    from permissao.models import Cargo, CargoPermissao

    personalizado = Cargo.objects.create(empresa=cenario.x, nome='So redefine', base='curador')
    for codigo in ('ver', 'redefinir_senha'):
        CargoPermissao.objects.create(cargo=personalizado, permissao_id=codigo)
    curadora, administradora = fabrica_pessoa('Curadora'), fabrica_pessoa('Administradora')
    conceder_direto(curadora, personalizado, cenario.x)
    conceder_direto(administradora, cenario.cargos_x['administrador'], cenario.x)
    _usar(curadora, 'redefinir_senha', 2)
    _usar(administradora, 'redefinir_senha', 2)
    assert 'Redefinir senha' not in _nomes(curadora)  # o serviço recusaria a confirmação (403)
    assert 'Redefinir senha' in _nomes(administradora)


def test_disponiveis_sao_os_permitidos_fora_do_inicio_e_nao_ocultos(administrador, monkeypatch):
    monkeypatch.setattr(menu, 'ATALHOS', (CONVIDAR, CARGOS, FAZENDA, SUB_AREA))
    _usar(administrador, 'criar_fazenda', 1)
    definir_estado(administrador, 'criar_sub_area', oculto=True)
    mostrados, ocultos, disponiveis = atalhos_da_pessoa(administrador)
    assert [a.nome for a in mostrados] == ['Convidar pessoa', 'Cadastrar fazenda']
    assert ocultos == [('criar_sub_area', 'Cadastrar sub-área')]
    assert disponiveis == [('gerenciar_cargo', 'Cargos')]
