"""Telas de cargos (003 R18, R20, R28, R33; A9, A12, A24): feliz, validação, conflito de versão e acesso negado por URL direta."""

import re

import pytest
from django.test import Client

from comum.models import EventoAuditoria
from permissao.cargo import gerenciar_cargo
from permissao.models import Cargo, CargoPermissao


def _casa(cenario):
    return f'/empresa/{cenario.x.pk}/'


def _telas(cenario, cargo_id):
    base = _casa(cenario)
    return {'cargos': base + 'cargos/', 'cargo_novo': base + 'cargos/novo', 'cargo_editar': base + f'cargos/{cargo_id}/editar'}


def _html(resposta):
    return re.sub(r'name="csrfmiddlewaretoken" value="[^"]+"| nonce="[^"]+"', '', resposta.content.decode())


def _versao(resposta):
    achado = re.search(r'name="versao" value="(\d+)"', resposta.content.decode())
    assert achado, 'a tela não leva a versão oculta'
    return int(achado.group(1))


@pytest.fixture
def administradora(conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    return conta.pessoa


@pytest.fixture
def campo(cenario, administradora):
    """Cargo personalizado de X que as telas editam."""
    return gerenciar_cargo(administradora, cenario.x, 'Campo', ['ver', 'baixar_documento'], base='tecnico')


# --- acesso negado (R20, A9) ---


def test_deslogado_e_levado_a_entrada_em_toda_tela(cenario):
    cliente = Client()
    for nome, caminho in _telas(cenario, cenario.cargos_x['tecnico'].pk).items():
        resposta = cliente.get(caminho)
        assert (nome, resposta.status_code, resposta['Location'].startswith('/entrar')) == (nome, 302, True)
        assert (nome, cliente.post(caminho).status_code) == (nome, 302)


def test_sem_alcance_ou_de_outra_empresa_e_404_em_toda_tela(cliente_logado, conta, cenario, conceder_direto):
    telas = _telas(cenario, cenario.cargos_x['tecnico'].pk)
    for nome, caminho in telas.items():
        assert (nome, cliente_logado.get(caminho).status_code) == (nome, 404)
    conceder_direto(conta.pessoa, cenario.cargos_y['administrador'], cenario.y)  # administra Y, não X
    for nome, caminho in telas.items():
        assert (nome, cliente_logado.get(caminho).status_code) == (nome, 404)
        assert (nome, cliente_logado.post(caminho, {'nome': 'Invasor', 'base': 'usuario'}).status_code) == (nome, 404)
    assert not Cargo.objects.filter(nome='Invasor').exists()


def test_quem_tem_alcance_sem_gerenciar_cargo_recebe_403_em_toda_tela(cliente_logado, conta, cenario, conceder_direto):
    alvo = cenario.cargos_x['tecnico']
    telas = _telas(cenario, alvo.pk)
    for base in ('curador', 'tecnico', 'usuario'):  # o Curador base convida, mas não gerencia cargo
        da_conta = conceder_direto(conta.pessoa, cenario.cargos_x[base], cenario.x)
        for nome, caminho in telas.items():
            assert (base, nome, cliente_logado.get(caminho).status_code) == (base, nome, 403)
            assert (base, nome, cliente_logado.post(caminho, {'nome': 'Invasor', 'base': 'usuario'}).status_code) == (base, nome, 403)
        da_conta.delete()
    assert not Cargo.objects.filter(nome='Invasor').exists()


def test_editar_cargo_de_outra_empresa_pela_url_de_x_e_404_e_nao_muda_nada(cliente_logado, administradora, cenario):
    de_y = cenario.cargos_y['tecnico']
    resposta = cliente_logado.post(_casa(cenario) + f'cargos/{de_y.pk}/editar', {'nome': 'Roubado', 'versao': de_y.versao, 'permissoes': ['ver']})
    assert resposta.status_code == 404
    de_y.refresh_from_db()
    assert de_y.nome == 'Técnico'
    assert de_y.versao == 1


# --- lista (R18, A12) ---


def test_lista_mostra_cada_cargo_com_empresa_nivel_e_total_em_portugues(cliente_logado, administradora, cenario, campo):
    html = _html(cliente_logado.get(_casa(cenario) + 'cargos/'))
    for esperado in ('Campo', 'Empresa X', 'nível Técnico', 'nível Administrador', 'Criar cargo', f'cargos/{campo.pk}/editar'):
        assert esperado in html, esperado
    assert 'Empresa Y' not in html
    assert not re.search(r'object \(|Select an option', html)


# --- criar (R18) ---


def test_formulario_de_criar_lista_a_matriz_pela_descricao_e_sem_acao_da_plataforma(cliente_logado, administradora, cenario):
    html = _html(cliente_logado.get(_casa(cenario) + 'cargos/novo'))
    assert 'Ver o território e seus dados' in html
    assert 'Criar e alterar cargo' in html
    assert 'Criar empresa' not in html
    assert 'value="criar_empresa"' not in html
    assert not re.search(r'object \(|Select an option', html)


def test_criar_grava_o_cargo_com_as_permissoes_e_audita(cliente_logado, administradora, cenario):
    resposta = cliente_logado.post(_casa(cenario) + 'cargos/novo', {'nome': 'Campo 2', 'base': 'tecnico', 'permissoes': ['ver', 'baixar_documento']})
    assert resposta.status_code == 302
    assert resposta['Location'].endswith('/cargos/?feito=criado')
    cargo = Cargo.objects.get(empresa=cenario.x, nome='Campo 2')
    assert cargo.base == 'tecnico'
    assert set(CargoPermissao.objects.filter(cargo=cargo).values_list('permissao_id', flat=True)) == {'ver', 'baixar_documento'}
    assert EventoAuditoria.objects.filter(acao='cargo_alterado', alvo_id=cargo.pk).count() == 1
    assert 'Cargo criado.' in _html(cliente_logado.get(resposta['Location']))


@pytest.mark.parametrize('mudanca, campo_do_erro, texto', [
    ({'nome': ' '}, 'campo_nome', 'Nome do cargo inválido.'),
    ({'nome': 'Técnico'}, 'campo_nome', 'Já existe cargo com esse nome na empresa.'),
    ({'permissoes': ['criar_empresa']}, 'campo_permissoes', 'Permissão inexistente ou exclusiva da plataforma.'),
    ({'permissoes': ['nao_existe']}, 'campo_permissoes', 'Permissão inexistente ou exclusiva da plataforma.'),
    ({'base': 'chefe'}, 'campo_base', 'Escolha o nível do cargo.'),
])
def test_criar_com_dado_invalido_volta_com_o_erro_uma_vez_so_no_campo(cliente_logado, administradora, cenario, mudanca, campo_do_erro, texto):
    dados = {'nome': 'Novo', 'base': 'tecnico', 'permissoes': ['ver'], **mudanca}
    antes = Cargo.objects.count()
    resposta = cliente_logado.post(_casa(cenario) + 'cargos/novo', dados)
    html = _html(resposta)
    assert resposta.status_code == 400
    assert html.count(texto) == 1
    assert f'id="{campo_do_erro}-descricao"' in html
    assert Cargo.objects.count() == antes


# --- editar (R18, A12) ---


def test_editar_mostra_o_nivel_como_texto_e_a_versao_oculta(cliente_logado, administradora, cenario, campo):
    resposta = cliente_logado.get(_casa(cenario) + f'cargos/{campo.pk}/editar')
    html = _html(resposta)
    assert _versao(resposta) == campo.versao
    assert 'nível Técnico, que não muda' in html
    assert 'name="base"' not in html
    assert re.search(r'value="baixar_documento"[^>]* checked', html)
    assert not re.search(r'value="validar_registro"[^>]* checked', html)


def test_editar_grava_nome_e_permissoes_soma_a_versao_e_ignora_base_e_empresa_enviadas(cliente_logado, administradora, cenario, campo):
    caminho = _casa(cenario) + f'cargos/{campo.pk}/editar'
    resposta = cliente_logado.post(caminho, {
        'nome': 'Campo novo', 'versao': campo.versao, 'permissoes': ['ver'], 'base': 'administrador', 'empresa': cenario.y.pk,
    })
    assert resposta.status_code == 302
    assert resposta['Location'].endswith('/cargos/?feito=alterado')
    campo.refresh_from_db()
    assert (campo.nome, campo.versao, campo.base, campo.empresa_id) == ('Campo novo', 2, 'tecnico', cenario.x.pk)
    assert set(campo.permissoes.values_list('pk', flat=True)) == {'ver'}


def test_versao_velha_volta_409_com_o_cargo_recarregado_e_nao_sobrescreve(cliente_logado, administradora, cenario, campo):
    caminho = _casa(cenario) + f'cargos/{campo.pk}/editar'
    lida = _versao(cliente_logado.get(caminho))
    gerenciar_cargo(administradora, cenario.x, 'Campo da outra pessoa', ['ver'], cargo=campo, versao=lida)  # a outra pessoa grava primeiro
    resposta = cliente_logado.post(caminho, {'nome': 'Campo velho', 'versao': lida, 'permissoes': ['ver', 'baixar_documento']})
    html = _html(resposta)
    assert resposta.status_code == 409
    assert html.count('Outra pessoa alterou este cargo.') == 1
    assert 'value="Campo da outra pessoa"' in html
    assert _versao(resposta) == lida + 1  # a tela reabre com a versão nova: o próximo envio vale
    campo.refresh_from_db()
    assert campo.nome == 'Campo da outra pessoa'


@pytest.mark.parametrize('versao', ['', 'abc', '-1', '١'])
def test_versao_ausente_ou_malformada_e_tratada_como_conflito_sem_erro_500(cliente_logado, administradora, cenario, campo, versao):
    resposta = cliente_logado.post(_casa(cenario) + f'cargos/{campo.pk}/editar', {'nome': 'X', 'versao': versao, 'permissoes': ['ver']})
    assert resposta.status_code == 409
    campo.refresh_from_db()
    assert campo.nome == 'Campo'


# --- ninguém passa do que tem (A24, D043, D075) ---


@pytest.fixture
def gestor(conta, cenario, conceder_direto):
    """Cargo personalizado de nível Curador com `gerenciar_cargo` e só duas permissões a mais, na empresa X inteira."""
    cargo = Cargo.objects.create(empresa=cenario.x, nome='Gestor de cargos', base='curador')
    CargoPermissao.objects.bulk_create(CargoPermissao(cargo=cargo, permissao_id=c) for c in ('ver', 'gerenciar_cargo'))
    conceder_direto(conta.pessoa, cargo, cenario.x)
    return conta.pessoa


def test_gestor_nao_cria_cargo_de_nivel_acima_nem_com_permissao_que_nao_tem(cliente_logado, gestor, cenario):
    caminho = _casa(cenario) + 'cargos/novo'
    antes = Cargo.objects.count()
    acima = cliente_logado.post(caminho, {'nome': 'Chefe', 'base': 'administrador', 'permissoes': ['ver']})
    a_mais = cliente_logado.post(caminho, {'nome': 'Campo', 'base': 'tecnico', 'permissoes': ['ver', 'validar_registro']})
    # O nível Administrador nem é oferecido (400); a recusa por nível acima, com 403, é do serviço (`test_cargo.py`).
    assert (acima.status_code, a_mais.status_code) == (400, 403)
    assert 'nível ou permissões acima das suas' in _html(a_mais)
    assert Cargo.objects.count() == antes
    dentro = cliente_logado.post(caminho, {'nome': 'Leitor', 'base': 'tecnico', 'permissoes': ['ver']})
    assert dentro.status_code == 302
    assert Cargo.objects.filter(nome='Leitor').exists()


def test_gestor_nao_edita_cargo_de_nivel_igual_ou_acima_e_nada_muda(cliente_logado, gestor, cenario):
    adm = cenario.cargos_x['administrador']
    resposta = cliente_logado.post(_casa(cenario) + f'cargos/{adm.pk}/editar', {'nome': 'Rebaixado', 'versao': adm.versao, 'permissoes': ['ver']})
    assert resposta.status_code == 403
    adm.refresh_from_db()
    assert adm.nome == 'Administrador'
    assert adm.versao == 1


# --- achados de revisão da PR #31 ---


def test_erro_de_validacao_na_edicao_mantem_a_versao_enviada_e_o_reenvio_ainda_da_409(cliente_logado, administradora, cenario, campo):
    caminho = _casa(cenario) + f'cargos/{campo.pk}/editar'
    lida = _versao(cliente_logado.get(caminho))
    gerenciar_cargo(administradora, cenario.x, 'Campo da outra pessoa', ['ver'], cargo=campo, versao=lida)
    invalida = cliente_logado.post(caminho, {'nome': ' ', 'versao': lida, 'permissoes': ['ver', 'baixar_documento']})
    assert invalida.status_code == 400
    assert _versao(invalida) == lida  # a versão que a pessoa leu, não a que a outra pessoa gravou
    reenvio = cliente_logado.post(caminho, {'nome': 'Campo corrigido', 'versao': _versao(invalida), 'permissoes': ['ver', 'baixar_documento']})
    assert reenvio.status_code == 409
    campo.refresh_from_db()
    assert campo.nome == 'Campo da outra pessoa'


def test_gerenciar_cargo_so_na_fazenda_nao_abre_as_telas_de_cargos(cliente_logado, conta, cenario, conceder_direto):
    """`gerenciar_cargo` exige a empresa inteira (cargo é da empresa): quem o tem só numa fazenda recebe 403, não um formulário que falharia."""
    cargo = Cargo.objects.create(empresa=cenario.x, nome='Gestor de fazenda', base='curador')
    CargoPermissao.objects.bulk_create(CargoPermissao(cargo=cargo, permissao_id=c) for c in ('ver', 'gerenciar_cargo'))
    conceder_direto(conta.pessoa, cargo, cenario.f1)
    for nome, caminho in _telas(cenario, cenario.cargos_x['tecnico'].pk).items():
        assert (nome, cliente_logado.get(caminho).status_code) == (nome, 403)


def test_lista_mostra_o_total_de_permissoes_de_cada_cargo(cliente_logado, administradora, cenario, campo):
    html = _html(cliente_logado.get(_casa(cenario) + 'cargos/'))
    assert 'nível Técnico · 2 permissões' in html


def test_cargo_administrador_aparece_como_somente_leitura_e_a_edicao_e_negada(cliente_logado, administradora, cenario):
    administrador = cenario.cargos_x['administrador']
    html = _html(cliente_logado.get(_casa(cenario) + 'cargos/'))
    assert 'Somente leitura' in html
    assert f'cargos/{administrador.pk}/editar' not in html
    caminho = _casa(cenario) + f'cargos/{administrador.pk}/editar'
    assert cliente_logado.get(caminho).status_code == 403
    assert cliente_logado.post(caminho, {'nome': 'Rebaixado', 'versao': administrador.versao, 'permissoes': ['ver']}).status_code == 403
    administrador.refresh_from_db()
    assert (administrador.nome, administrador.versao) == ('Administrador', 1)


# --- matriz de permissões em grupos (003 Fase 4) ---


def test_todo_codigo_do_catalogo_tem_grupo_na_matriz(db):
    """Ação nova no catálogo (migração) falha aqui até ganhar grupo; a tela a mostra em "Outras permissões" enquanto isso."""
    from permissao.models import Permissao
    from permissao.pode import ACOES_DA_PLATAFORMA
    from projeto.cargos_paginas import GRUPOS_DE_PERMISSOES

    classificadas = [c for _, codigos, _ in GRUPOS_DE_PERMISSOES for c in codigos]
    assert len(classificadas) == len(set(classificadas)), 'ação em dois grupos'
    catalogo = set(Permissao.objects.exclude(codigo__in=ACOES_DA_PLATAFORMA).values_list('pk', flat=True))
    assert catalogo - set(classificadas) == set()
    assert set(classificadas) - catalogo == set()


def test_matriz_mostra_grupos_na_ordem_com_cada_acao_uma_vez_e_o_aviso_no_ultimo(cliente_logado, administradora, cenario):
    html = _html(cliente_logado.get(_casa(cenario) + 'cargos/novo'))
    titulos = re.findall(r'<legend class="campo-rotulo">([^<]+)</legend>', html)
    assert titulos == ['Consulta', 'Trabalho de campo', 'Documentos', 'Validação e aprovação', 'Território', 'Configurações', 'Pessoas e cargos']
    from permissao.models import Permissao
    from permissao.pode import ACOES_DA_PLATAFORMA

    elegiveis = Permissao.objects.exclude(codigo__in=ACOES_DA_PLATAFORMA).count()  # o mesmo critério do teste de classificação
    assert html.count('name="permissoes"') == elegiveis
    assert html.count('value="ver"') == 1
    assert html.index('Pessoas e cargos') > html.index('Território')
    assert 'Quem tem estas permissões controla o acesso de outras pessoas.' in html
    assert html.count('Você só marca o que o seu próprio acesso permite.') == 1


def test_acao_sem_grupo_aparece_em_outras_permissoes_e_nao_some(cliente_logado, administradora, cenario, monkeypatch):
    from projeto import cargos_paginas

    sem_ver = tuple((t, tuple(c for c in codigos if c != 'ver'), a) for t, codigos, a in cargos_paginas.GRUPOS_DE_PERMISSOES)
    monkeypatch.setattr(cargos_paginas, 'GRUPOS_DE_PERMISSOES', sem_ver)
    html = _html(cliente_logado.get(_casa(cenario) + 'cargos/novo'))
    assert html.index('Outras permissões') < html.index('value="ver"')
    assert html.index('Outras permissões') < html.index('Pessoas e cargos')  # "Pessoas e cargos" segue por último
    assert html.count('value="ver"') == 1


def test_erro_de_permissao_invalida_aparece_uma_vez_no_primeiro_grupo(cliente_logado, administradora, cenario):
    resposta = cliente_logado.post(_casa(cenario) + 'cargos/novo', {'nome': 'Novo', 'base': 'tecnico', 'permissoes': ['criar_empresa']})
    html = _html(resposta)
    assert resposta.status_code == 400
    assert html.count('Permissão inexistente ou exclusiva da plataforma.') == 1
    assert 'id="campo_permissoes-descricao"' in html


def test_criar_nao_oferece_nem_aceita_o_nivel_administrador(cliente_logado, administradora, cenario):
    html = _html(cliente_logado.get(_casa(cenario) + 'cargos/novo'))
    assert '<option value="administrador"' not in html
    antes = Cargo.objects.count()
    resposta = cliente_logado.post(_casa(cenario) + 'cargos/novo', {'nome': 'Direção', 'base': 'administrador', 'permissoes': ['ver']})
    assert resposta.status_code == 400
    assert Cargo.objects.count() == antes
