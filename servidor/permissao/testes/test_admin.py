"""Painel de acesso (T5.2): concessão, revogação e cargo pelos serviços, também sob o papel `app` com RLS."""

from importlib import import_module

import pytest
from django.contrib.messages import get_messages

from comum.models import EventoAuditoria
from permissao.models import Cargo, CargoPermissao, Concessao, Permissao
from permissao.pode import com_permissao


@pytest.fixture(autouse=True)
def catalogo(db):
    for codigo, descricao, delegavel in import_module('permissao.migrations.0001_initial').ACOES:
        Permissao.objects.get_or_create(codigo=codigo, defaults={'descricao': descricao, 'delegavel': delegavel})


def _com(fabrica_pessoa, conceder_direto, cargo, escopo, nome='Pessoa'):
    pessoa = fabrica_pessoa(nome)
    conceder_direto(pessoa, cargo, escopo)
    return pessoa


def _mensagens(resposta):
    return [str(m) for m in get_messages(resposta.wsgi_request)]


def test_administrador_concede_pelo_painel_e_a_lista_mostra(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    alvo = fabrica_pessoa('Alvo', empresa_origem=cenario.x)
    cliente = entrar_no_painel(admin)
    corpo = {'pessoa': alvo.pk, 'cargo': cenario.cargos_x['usuario'].pk, 'fazenda': cenario.f1.pk, 'inicio_0': '2026-01-01', 'inicio_1': '00:00:00'}
    assert cliente.post('/painel/permissao/concessao/add/', corpo).status_code == 302
    assert Concessao.objects.get(pessoa=alvo).fazenda_id == cenario.f1.pk
    assert EventoAuditoria.objects.filter(acao='concessao_criada', pessoa_id=admin.pk).exists()


def test_concessao_de_cargo_de_outra_empresa_ou_por_tecnico_e_negada(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    tecnico = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['tecnico'], cenario.f1, 'Técnico')
    alvo = fabrica_pessoa('Alvo', empresa_origem=cenario.x)
    base = {'pessoa': alvo.pk, 'fazenda': cenario.f1.pk, 'inicio_0': '2026-01-01', 'inicio_1': '00:00:00'}
    assert entrar_no_painel(admin).post('/painel/permissao/concessao/add/', {**base, 'cargo': cenario.cargos_y['usuario'].pk}).status_code in (200, 403)
    # Técnico nem abre o painel (vai para o login): negado do mesmo jeito, sem concessão gravada.
    assert entrar_no_painel(tecnico).post('/painel/permissao/concessao/add/', {**base, 'cargo': cenario.cargos_x['usuario'].pk}).status_code in (302, 403)
    assert not Concessao.objects.filter(pessoa=alvo).exists()


def test_apagar_concessao_no_painel_revoga_e_nao_apaga_a_linha(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    alvo = fabrica_pessoa('Alvo', empresa_origem=cenario.x)
    concessao = conceder_direto(alvo, cenario.cargos_x['usuario'], cenario.f1)
    resposta = entrar_no_painel(admin).post(f'/painel/permissao/concessao/{concessao.pk}/delete/', {'post': 'yes'})
    assert resposta.status_code == 302
    concessao.refresh_from_db()
    assert (concessao.revogada_em is not None, concessao.revogada_por) == (True, admin)
    assert EventoAuditoria.objects.filter(acao='concessao_revogada').exists()


def test_titular_nao_sai_pelo_painel_e_tecnico_nao_revoga(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    titular = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x, 'Titular')
    cenario.x.titular = titular
    cenario.x.save(update_fields=['titular'])
    outro = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x, 'Outro')
    tecnico = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['tecnico'], cenario.f1, 'Técnico')
    usuario = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.f1, 'Usuário')
    do_titular = Concessao.objects.get(pessoa=titular)
    resposta = entrar_no_painel(outro).post(f'/painel/permissao/concessao/{do_titular.pk}/delete/', {'post': 'yes'}, follow=True)
    assert any('titular' in texto for texto in _mensagens(resposta))
    do_usuario = Concessao.objects.get(pessoa=usuario)
    assert entrar_no_painel(tecnico).post(f'/painel/permissao/concessao/{do_usuario.pk}/delete/', {'post': 'yes'}).status_code == 302
    assert Concessao.objects.filter(revogada_em__isnull=True, pessoa__in=[titular, usuario]).count() == 2


def test_apagar_em_massa_nao_revoga_nem_apaga(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    alvo = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.f1, 'Alvo')
    concessao = Concessao.objects.get(pessoa=alvo)
    entrar_no_painel(admin).post('/painel/permissao/concessao/', {'action': 'delete_selected', '_selected_action': [concessao.pk], 'post': 'yes'})
    assert Concessao.objects.filter(pk=concessao.pk, revogada_em__isnull=True).exists()


def test_administrador_cria_e_altera_cargo_pelo_painel_com_evento(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    cliente = entrar_no_painel(_com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x))
    corpo = {'nome': 'Campo', 'empresa': cenario.x.pk, 'base': 'tecnico', 'codigos': ['ver', 'criar_registro_campo']}
    assert cliente.post('/painel/permissao/cargo/add/', corpo).status_code == 302
    cargo = Cargo.objects.get(nome='Campo')
    assert set(cargo.permissoes.values_list('pk', flat=True)) == {'ver', 'criar_registro_campo'}
    assert cliente.post(f'/painel/permissao/cargo/{cargo.pk}/change/', {'nome': 'Campo 2', 'codigos': ['ver'], 'versao': cargo.versao}).status_code == 302
    cargo.refresh_from_db()
    assert (cargo.nome, cargo.base, set(cargo.permissoes.values_list('pk', flat=True))) == ('Campo 2', 'tecnico', {'ver'})
    assert EventoAuditoria.objects.filter(acao='cargo_alterado').count() == 2


def test_curador_nao_cria_nem_altera_cargo_e_ve_so_os_da_propria_empresa(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    cliente = entrar_no_painel(_com(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.f1))
    corpo = {'nome': 'Intruso', 'empresa': cenario.x.pk, 'base': 'usuario', 'codigos': ['ver']}
    assert cliente.post('/painel/permissao/cargo/add/', corpo).status_code == 403
    alheio = cenario.cargos_y['usuario']
    assert cliente.post(f'/painel/permissao/cargo/{alheio.pk}/change/', {'nome': 'Roubado', 'codigos': [], 'versao': alheio.versao}).status_code in (302, 403, 404)
    alheio.refresh_from_db()
    assert alheio.nome != 'Roubado'
    assert not Cargo.objects.filter(nome='Intruso').exists()


@pytest.fixture
def pessoas_do_painel(cenario, fabrica_pessoa, conceder_direto):
    # Montado como dono, antes de `como_app`: o papel `app` sem contexto não grava concessão.
    return (
        _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x, 'Admin X'),
        _com(fabrica_pessoa, conceder_direto, cenario.cargos_y['administrador'], cenario.y, 'Admin Y'),
        fabrica_pessoa('Alvo', empresa_origem=cenario.x),
    )


@pytest.mark.django_db(transaction=True, databases=['default', 'app'])
def test_painel_sob_o_papel_app_com_rls(cenario, pessoas_do_painel, entrar_no_painel, como_app):
    admin_x, admin_y, alvo = pessoas_do_painel
    cliente, cliente_y = entrar_no_painel(admin_x), entrar_no_painel(admin_y)

    def concessao_do_alvo():
        with com_permissao(admin_x, 'convidar_pessoa'):  # o ORM do teste é o papel `app`: sem contexto, não vê linha
            return Concessao.objects.filter(pessoa=alvo).first()

    assert '>F1<' in cliente.get('/painel/territorio/fazenda/').content.decode()
    assert '>F1<' not in cliente_y.get('/painel/territorio/fazenda/').content.decode()
    corpo = {'pessoa': alvo.pk, 'cargo': cenario.cargos_x['usuario'].pk, 'fazenda': cenario.f1.pk, 'inicio_0': '2026-01-01', 'inicio_1': '00:00:00'}
    cliente_y.post('/painel/permissao/concessao/add/', corpo)
    assert concessao_do_alvo() is None
    assert cliente.post('/painel/permissao/concessao/add/', corpo).status_code == 302
    concessao = concessao_do_alvo()
    assert concessao is not None
    cliente_y.post(f'/painel/permissao/concessao/{concessao.pk}/delete/', {'post': 'yes'})
    assert getattr(concessao_do_alvo(), 'revogada_em', 'sumiu') is None
    assert cliente.post(f'/painel/permissao/concessao/{concessao.pk}/delete/', {'post': 'yes'}).status_code == 302
    assert getattr(concessao_do_alvo(), 'revogada_em', None) is not None


def test_curador_de_sub_area_nao_ve_concessao_da_irma(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    curador = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.g1, 'Curador de G1')
    _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.g2, 'Moradora de G2')
    _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.t1, 'Moradora de T1')
    pagina = entrar_no_painel(curador).get('/painel/permissao/concessao/').content.decode()
    assert 'Moradora de T1' in pagina
    assert 'Moradora de G2' not in pagina


def test_gestor_so_com_gerenciar_cargo_altera_cargo_existente(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    gestor = Cargo.objects.create(empresa=cenario.x, nome='Gestor', base='curador')
    CargoPermissao.objects.bulk_create(CargoPermissao(cargo=gestor, permissao_id=c) for c in ('ver', 'gerenciar_cargo'))
    pessoa = _com(fabrica_pessoa, conceder_direto, gestor, cenario.x, 'Gestora')
    alvo = cenario.cargos_x['usuario']
    cliente = entrar_no_painel(pessoa)
    assert cliente.post(f'/painel/permissao/cargo/{alvo.pk}/change/', {'nome': 'Leitor', 'codigos': ['ver'], 'versao': alvo.versao}).status_code == 302
    alvo.refresh_from_db()
    assert alvo.nome == 'Leitor'


def test_quem_so_revoga_acesso_ve_as_concessoes_e_revoga(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    revogador = Cargo.objects.create(empresa=cenario.x, nome='Revogador', base='curador')
    CargoPermissao.objects.bulk_create(CargoPermissao(cargo=revogador, permissao_id=c) for c in ('ver', 'revogar_acesso'))
    pessoa = _com(fabrica_pessoa, conceder_direto, revogador, cenario.x, 'Revogadora')
    alvo = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.f1, 'Alvo do revogador')
    cliente = entrar_no_painel(pessoa)
    assert 'Alvo do revogador' in cliente.get('/painel/permissao/concessao/').content.decode()
    concessao = Concessao.objects.get(pessoa=alvo)
    assert cliente.post(f'/painel/permissao/concessao/{concessao.pk}/delete/', {'post': 'yes'}).status_code == 302
    concessao.refresh_from_db()
    assert concessao.revogada_em is not None


def test_painel_nao_concede_a_pessoa_fora_do_alcance(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    estranha = fabrica_pessoa('Estranha')
    corpo = {'pessoa': estranha.pk, 'cargo': cenario.cargos_x['usuario'].pk, 'fazenda': cenario.f1.pk, 'inicio_0': '2026-01-01', 'inicio_1': '00:00:00'}
    assert entrar_no_painel(admin).post('/painel/permissao/concessao/add/', corpo).status_code == 200
    assert not Concessao.objects.filter(pessoa=estranha).exists()


def test_renomear_cargo_para_nome_repetido_vira_mensagem_e_nao_erro_500(cenario, plataforma, entrar_no_painel):
    leitor = Cargo.objects.create(empresa=cenario.x, nome='Leitor', base='usuario')
    resposta = entrar_no_painel(plataforma).post(f'/painel/permissao/cargo/{leitor.pk}/change/', {'nome': 'Usuário', 'codigos': ['ver'], 'versao': leitor.versao}, follow=True)
    assert resposta.status_code == 200
    assert any('Já existe' in m for m in _mensagens(resposta))
    leitor.refresh_from_db()
    assert leitor.nome == 'Leitor'


def test_formulario_do_cargo_leva_a_versao_e_o_segundo_salvamento_velho_e_recusado(cenario, plataforma, entrar_no_painel):
    cargo = Cargo.objects.create(empresa=cenario.x, nome='Campo', base='usuario')
    CargoPermissao.objects.create(cargo=cargo, permissao_id='ver')
    cliente = entrar_no_painel(plataforma)
    pagina = cliente.get(f'/painel/permissao/cargo/{cargo.pk}/change/').content.decode()
    assert f'name="versao" value="{cargo.versao}"' in pagina
    lida = cargo.versao
    primeira = cliente.post(f'/painel/permissao/cargo/{cargo.pk}/change/', {'nome': 'Primeiro', 'codigos': ['ver'], 'versao': lida})
    assert primeira.status_code == 302
    segunda = cliente.post(f'/painel/permissao/cargo/{cargo.pk}/change/', {'nome': 'Segundo', 'codigos': ['ver'], 'versao': lida}, follow=True)
    assert any('Outra pessoa' in m for m in _mensagens(segunda))
    cargo.refresh_from_db()
    assert (cargo.nome, cargo.versao) == ('Primeiro', lida + 1)
