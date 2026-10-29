"""Painel de acesso (T5.2): concessão, revogação e cargo pelos serviços, também sob o papel `app` com RLS."""

from importlib import import_module

import pytest
from django.contrib.messages import get_messages

from comum.models import EventoAuditoria
from permissao.models import Cargo, Concessao, Permissao
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
    alvo = fabrica_pessoa('Alvo')
    cliente = entrar_no_painel(admin)
    corpo = {'pessoa': alvo.pk, 'cargo': cenario.cargos_x['usuario'].pk, 'fazenda': cenario.f1.pk, 'inicio_0': '2026-01-01', 'inicio_1': '00:00:00'}
    assert cliente.post('/painel/permissao/concessao/add/', corpo).status_code == 302
    assert Concessao.objects.get(pessoa=alvo).fazenda_id == cenario.f1.pk
    assert EventoAuditoria.objects.filter(acao='concessao_criada', pessoa_id=admin.pk).exists()


def test_concessao_de_cargo_de_outra_empresa_ou_por_tecnico_e_negada(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    tecnico = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['tecnico'], cenario.f1, 'Técnico')
    alvo = fabrica_pessoa('Alvo')
    base = {'pessoa': alvo.pk, 'fazenda': cenario.f1.pk, 'inicio_0': '2026-01-01', 'inicio_1': '00:00:00'}
    assert entrar_no_painel(admin).post('/painel/permissao/concessao/add/', {**base, 'cargo': cenario.cargos_y['usuario'].pk}).status_code == 403
    # Técnico nem abre o painel (vai para o login): negado do mesmo jeito, sem concessão gravada.
    assert entrar_no_painel(tecnico).post('/painel/permissao/concessao/add/', {**base, 'cargo': cenario.cargos_x['usuario'].pk}).status_code in (302, 403)
    assert not Concessao.objects.filter(pessoa=alvo).exists()


def test_apagar_concessao_no_painel_revoga_e_nao_apaga_a_linha(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    alvo = fabrica_pessoa('Alvo')
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
    assert cliente.post(f'/painel/permissao/cargo/{cargo.pk}/change/', {'nome': 'Campo 2', 'codigos': ['ver']}).status_code == 302
    cargo.refresh_from_db()
    assert (cargo.nome, cargo.base, set(cargo.permissoes.values_list('pk', flat=True))) == ('Campo 2', 'tecnico', {'ver'})
    assert EventoAuditoria.objects.filter(acao='cargo_alterado').count() == 2


def test_curador_nao_cria_nem_altera_cargo_e_ve_so_os_da_propria_empresa(cenario, fabrica_pessoa, conceder_direto, entrar_no_painel):
    cliente = entrar_no_painel(_com(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.f1))
    corpo = {'nome': 'Intruso', 'empresa': cenario.x.pk, 'base': 'usuario', 'codigos': ['ver']}
    assert cliente.post('/painel/permissao/cargo/add/', corpo).status_code == 403
    alheio = cenario.cargos_y['usuario']
    assert cliente.post(f'/painel/permissao/cargo/{alheio.pk}/change/', {'nome': 'Roubado', 'codigos': []}).status_code in (302, 403, 404)
    alheio.refresh_from_db()
    assert alheio.nome != 'Roubado'
    assert not Cargo.objects.filter(nome='Intruso').exists()


@pytest.fixture
def pessoas_do_painel(cenario, fabrica_pessoa, conceder_direto):
    # Montado como dono, antes de `como_app`: o papel `app` sem contexto não grava concessão.
    return (
        _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x, 'Admin X'),
        _com(fabrica_pessoa, conceder_direto, cenario.cargos_y['administrador'], cenario.y, 'Admin Y'),
        fabrica_pessoa('Alvo'),
    )


@pytest.mark.django_db(transaction=True, databases=['default', 'app'])
def test_painel_sob_o_papel_app_com_rls(cenario, pessoas_do_painel, entrar_no_painel, como_app):
    admin_x, admin_y, alvo = pessoas_do_painel
    cliente, cliente_y = entrar_no_painel(admin_x), entrar_no_painel(admin_y)

    def concessao_do_alvo():
        with com_permissao(admin_x, 'convidar_pessoa'):  # o ORM do teste é o papel `app`: sem contexto, não vê linha
            return Concessao.objects.filter(pessoa=alvo).first()

    assert 'F1' in cliente.get('/painel/territorio/fazenda/').content.decode()
    assert 'F1' not in cliente_y.get('/painel/territorio/fazenda/').content.decode()
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
