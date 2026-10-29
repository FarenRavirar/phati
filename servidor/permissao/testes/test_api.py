"""Rotas de permissão pela URL real: pessoas, concessões, redefinição por Administrador, cargos e catálogo (R9, R10, R17)."""

import json
from datetime import timedelta
from importlib import import_module

import pytest
from django.test import Client
from django.utils import timezone

from identidade import sessao
from identidade.models import PedidoRedefinicao, Pessoa
from permissao.models import Cargo, CargoPermissao, CategoriaDado, Concessao, Permissao


@pytest.fixture(autouse=True)
def catalogo(db):
    for codigo, descricao, delegavel in import_module('permissao.migrations.0001_initial').ACOES:
        Permissao.objects.get_or_create(codigo=codigo, defaults={'descricao': descricao, 'delegavel': delegavel})


def _enviar(pessoa, rota, corpo=None, metodo='post'):
    cabecalho = {'Authorization': f'Bearer {sessao.emitir_acesso(pessoa, "teste")}'}
    chamar = getattr(Client(), metodo)
    if metodo in ('get', 'delete'):
        return chamar(f'/api/v1/{rota}', headers=cabecalho)
    return chamar(f'/api/v1/{rota}', data=json.dumps(corpo or {}), content_type='application/json', headers=cabecalho)


def _com(fabrica_pessoa, conceder_direto, cargo, escopo, nome='Pessoa'):
    pessoa = fabrica_pessoa(nome)
    conceder_direto(pessoa, cargo, escopo)
    return pessoa


def _convite(cargo, escopo, cpf, **extra):
    return {'nome': 'Convidada', 'email': 'convidada@exemplo.test', 'cpf': cpf, 'cargo_id': cargo.pk, 'escopo': escopo, **extra}


def test_sem_credencial_toda_rota_de_permissao_responde_401(cenario):
    cliente = Client()
    for metodo, rota in (('get', 'pessoas'), ('get', 'cargos'), ('get', 'permissoes'), ('post', 'pessoas'),
                         ('post', 'pessoas/1/concessoes'), ('delete', 'pessoas/1/concessoes/1'),
                         ('post', 'pessoas/1/redefinir-senha')):
        assert getattr(cliente, metodo)(f'/api/v1/{rota}').status_code == 401, rota


def test_administrador_convida_usuario_na_fazenda_e_a_pessoa_aparece_na_lista(cenario, fabrica_pessoa, conceder_direto, cpf_novo):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    resposta = _enviar(admin, 'pessoas', _convite(cenario.cargos_x['usuario'], {'fazenda_id': cenario.f1.pk}, cpf_novo()))
    assert resposta.status_code == 201
    assert resposta.json()['senha_temporaria']
    nova = Pessoa.objects.get(pk=resposta.json()['id'])
    assert Concessao.objects.get(pk=resposta.json()['concessao_id']).pessoa_id == nova.pk
    assert nova.pk in {p['id'] for p in _enviar(admin, 'pessoas', metodo='get').json()}


@pytest.mark.parametrize('base', ['tecnico', 'usuario'])
def test_cargo_sem_convidar_nao_convida_nem_concede(cenario, fabrica_pessoa, conceder_direto, cpf_novo, base):
    pessoa = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x[base], cenario.f1)
    alvo = fabrica_pessoa('Alvo')
    assert _enviar(pessoa, 'pessoas', _convite(cenario.cargos_x['usuario'], {'fazenda_id': cenario.f1.pk}, cpf_novo())).status_code == 403
    corpo = {'cargo_id': cenario.cargos_x['usuario'].pk, 'escopo': {'fazenda_id': cenario.f1.pk}}
    assert _enviar(pessoa, f'pessoas/{alvo.pk}/concessoes', corpo).status_code == 403
    assert not Concessao.objects.filter(pessoa=alvo).exists()


def test_administrador_de_x_nao_convida_nem_concede_na_empresa_y(cenario, fabrica_pessoa, conceder_direto, cpf_novo):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    total = Pessoa.objects.count()
    convite = _convite(cenario.cargos_y['usuario'], {'fazenda_id': cenario.fy.pk}, cpf_novo())
    assert _enviar(admin, 'pessoas', convite).status_code in (403, 404)
    assert Pessoa.objects.count() == total
    alvo = fabrica_pessoa('Alvo')
    corpo = {'cargo_id': cenario.cargos_y['usuario'].pk, 'escopo': {'empresa_id': cenario.y.pk}}
    assert _enviar(admin, f'pessoas/{alvo.pk}/concessoes', corpo).status_code in (403, 404)
    assert not Concessao.objects.filter(pessoa=alvo).exists()


def test_cargo_de_outra_empresa_numa_concessao_da_propria_e_negado(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    alvo = fabrica_pessoa('Alvo')
    corpo = {'cargo_id': cenario.cargos_y['usuario'].pk, 'escopo': {'fazenda_id': cenario.f1.pk}}
    assert _enviar(admin, f'pessoas/{alvo.pk}/concessoes', corpo).status_code in (403, 404)
    assert not Concessao.objects.filter(pessoa=alvo).exists()


def test_lista_de_pessoas_nao_vaza_entre_empresas_e_sem_acesso_recebe_vazio(cenario, fabrica_pessoa, conceder_direto):
    admin_x = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x, 'Admin X')
    usuario_x = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.f1, 'Usuário X')
    admin_y = _com(fabrica_pessoa, conceder_direto, cenario.cargos_y['administrador'], cenario.y, 'Admin Y')
    sem_acesso = fabrica_pessoa('Sem acesso')
    vistas_por_y = {p['id'] for p in _enviar(admin_y, 'pessoas', metodo='get').json()}
    assert vistas_por_y == {admin_y.pk}
    assert usuario_x.pk in {p['id'] for p in _enviar(admin_x, 'pessoas', metodo='get').json()}
    assert _enviar(sem_acesso, 'pessoas', metodo='get').json() == []
    assert _enviar(usuario_x, 'pessoas', metodo='get').json() == []


def test_lista_de_pessoas_nao_expoe_cpf_nem_hash_de_senha(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    for pessoa in _enviar(admin, 'pessoas', metodo='get').json():
        assert set(pessoa) == {'id', 'nome', 'email', 'empresa_origem_id', 'deve_trocar_senha'}


def test_concede_e_revoga_e_a_revogacao_de_outra_empresa_ou_de_outra_pessoa_e_negada(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    admin_y = _com(fabrica_pessoa, conceder_direto, cenario.cargos_y['administrador'], cenario.y, 'Admin Y')
    alvo, outra = fabrica_pessoa('Alvo'), fabrica_pessoa('Outra')
    corpo = {'cargo_id': cenario.cargos_x['usuario'].pk, 'escopo': {'fazenda_id': cenario.f1.pk}}
    criada = _enviar(admin, f'pessoas/{alvo.pk}/concessoes', corpo)
    assert criada.status_code == 201
    concessao_id = criada.json()['id']
    assert _enviar(admin_y, f'pessoas/{alvo.pk}/concessoes/{concessao_id}', metodo='delete').status_code in (403, 404)
    assert _enviar(admin, f'pessoas/{outra.pk}/concessoes/{concessao_id}', metodo='delete').status_code == 404
    assert Concessao.objects.get(pk=concessao_id).revogada_em is None
    assert _enviar(admin, f'pessoas/{alvo.pk}/concessoes/{concessao_id}', metodo='delete').status_code == 204
    revogada = Concessao.objects.get(pk=concessao_id)
    assert (revogada.revogada_em is not None, revogada.revogada_por) == (True, admin)
    repetida = _enviar(admin, f'pessoas/{alvo.pk}/concessoes/{concessao_id}', metodo='delete')
    assert (repetida.status_code, repetida.json()) == (400, {'detalhe': 'concessao_ja_revogada'})


def test_titular_nao_sai_por_revogacao(cenario, fabrica_pessoa, conceder_direto):
    titular = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x, 'Titular')
    cenario.x.titular = titular
    cenario.x.save(update_fields=['titular'])
    outro = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x, 'Outro admin')
    concessao = Concessao.objects.get(pessoa=titular)
    resposta = _enviar(outro, f'pessoas/{titular.pk}/concessoes/{concessao.pk}', metodo='delete')
    assert (resposta.status_code, resposta.json()) == (400, {'detalhe': 'titular_protegido'})


def test_tecnico_nao_revoga(cenario, fabrica_pessoa, conceder_direto):
    tecnico = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['tecnico'], cenario.f1)
    usuario = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.f1, 'Usuário')
    concessao = Concessao.objects.get(pessoa=usuario)
    assert _enviar(tecnico, f'pessoas/{usuario.pk}/concessoes/{concessao.pk}', metodo='delete').status_code == 403
    assert Concessao.objects.get(pk=concessao.pk).revogada_em is None


def test_administrador_pede_redefinicao_de_pessoa_da_empresa_e_o_link_sai_por_e_mail(cenario, fabrica_pessoa, conceder_direto, mailoutbox):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    alvo = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.f1, 'Alvo')
    assert _enviar(admin, f'pessoas/{alvo.pk}/redefinir-senha').status_code == 204
    assert PedidoRedefinicao.objects.filter(pessoa=alvo, solicitado_por=admin).count() == 1
    assert len(mailoutbox) == 1


def test_redefinicao_negada_a_outra_empresa_ao_tecnico_e_a_pessoa_inexistente_nao_cria_pedido(cenario, fabrica_pessoa, conceder_direto):
    admin_y = _com(fabrica_pessoa, conceder_direto, cenario.cargos_y['administrador'], cenario.y, 'Admin Y')
    tecnico = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['tecnico'], cenario.f1, 'Técnico')
    alvo = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.f1, 'Alvo')
    assert _enviar(admin_y, f'pessoas/{alvo.pk}/redefinir-senha').status_code in (403, 404)
    assert _enviar(tecnico, f'pessoas/{alvo.pk}/redefinir-senha').status_code == 403
    assert _enviar(admin_y, 'pessoas/999999/redefinir-senha').status_code in (403, 404)
    assert not PedidoRedefinicao.objects.filter(pessoa=alvo).exists()


def test_cargos_e_catalogo_so_para_quem_age_e_so_da_propria_empresa(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    usuario = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.f1, 'Usuário')
    sem_acesso = fabrica_pessoa('Sem acesso')
    cargos = _enviar(admin, 'cargos', metodo='get').json()
    assert {c['empresa_id'] for c in cargos} == {cenario.x.pk}
    assert {c['base'] for c in cargos} == {'administrador', 'curador', 'tecnico', 'usuario'}
    assert len(_enviar(admin, 'permissoes', metodo='get').json()) == Permissao.objects.count()
    for pessoa in (usuario, sem_acesso):
        assert _enviar(pessoa, 'cargos', metodo='get').json() == []
        assert _enviar(pessoa, 'permissoes', metodo='get').json() == []


def test_plataforma_lista_cargos_de_todas_as_empresas(cenario, plataforma):
    cargos = _enviar(plataforma, 'cargos', metodo='get').json()
    assert {c['empresa_id'] for c in cargos} == {cenario.x.pk, cenario.y.pk}


@pytest.mark.parametrize(
    'escopo',
    [{}, {'empresa_id': 1, 'fazenda_id': 1}, {'empresa_id': None}],
)
def test_escopo_sem_exatamente_um_alvo_e_422_sem_ecoar_o_valor(cenario, fabrica_pessoa, conceder_direto, escopo):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    alvo = fabrica_pessoa('Alvo')
    resposta = _enviar(admin, f'pessoas/{alvo.pk}/concessoes', {'cargo_id': cenario.cargos_x['usuario'].pk, 'escopo': escopo})
    assert resposta.status_code == 422
    assert resposta.json()['detalhe'] == 'entrada_invalida'
    assert not Concessao.objects.filter(pessoa=alvo).exists()


def test_periodo_invalido_e_422_e_nao_500(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    alvo = fabrica_pessoa('Alvo')
    passado = (timezone.now() - timedelta(days=1)).isoformat()
    corpo = {'cargo_id': cenario.cargos_x['usuario'].pk, 'escopo': {'fazenda_id': cenario.f1.pk}, 'fim': passado}
    assert _enviar(admin, f'pessoas/{alvo.pk}/concessoes', corpo).status_code == 422
    assert not Concessao.objects.filter(pessoa=alvo).exists()


def test_convite_com_e_mail_malformado_ou_cpf_repetido_nao_grava_pessoa(cenario, fabrica_pessoa, conceder_direto, cpf_novo):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    existente = fabrica_pessoa('Existente')
    escopo = {'fazenda_id': cenario.f1.pk}
    ruim = _convite(cenario.cargos_x['usuario'], escopo, cpf_novo(), email='sem-arroba')
    assert _enviar(admin, 'pessoas', ruim).status_code == 422
    total = Pessoa.objects.count()
    assert total == 2
    # CPF de pessoa já cadastrada: o serviço recusa; quem já existe recebe concessão pela outra rota.
    from identidade import cpf as modulo_cpf

    repetido = _convite(cenario.cargos_x['usuario'], escopo, modulo_cpf.decifrar(existente.cpf_cifrado))
    resposta = _enviar(admin, 'pessoas', repetido)
    assert (resposta.status_code, resposta.json()) == (400, {'detalhe': 'cpf_duplicado'})
    assert Pessoa.objects.count() == total


def test_categoria_de_outra_empresa_e_recusada(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    alheia = CategoriaDado.objects.create(empresa=cenario.y, nome='Alheia')
    alvo = fabrica_pessoa('Alvo')
    corpo = {'cargo_id': cenario.cargos_x['usuario'].pk, 'escopo': {'fazenda_id': cenario.f1.pk}, 'categoria_ids': [alheia.pk]}
    resposta = _enviar(admin, f'pessoas/{alvo.pk}/concessoes', corpo)
    assert (resposta.status_code, resposta.json()) == (400, {'detalhe': 'categoria_invalida'})
    assert not Concessao.objects.filter(pessoa=alvo).exists()


def test_pessoa_inexistente_e_404(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    corpo = {'cargo_id': cenario.cargos_x['usuario'].pk, 'escopo': {'fazenda_id': cenario.f1.pk}}
    assert _enviar(admin, 'pessoas/999999/concessoes', corpo).status_code == 404


@pytest.fixture
def pessoas_do_fluxo(cenario, fabrica_pessoa, conceder_direto):
    # Montado como dono, antes de `como_app`: o papel `app` sem contexto não grava concessão.
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    admin_y = _com(fabrica_pessoa, conceder_direto, cenario.cargos_y['administrador'], cenario.y, 'Admin Y')
    return admin, admin_y


@pytest.mark.django_db(transaction=True, databases=['default', 'app'])
def test_fluxo_completo_sob_o_papel_app_com_rls(cenario, pessoas_do_fluxo, cpf_novo, como_app):
    admin, admin_y = pessoas_do_fluxo
    convite = _enviar(admin, 'pessoas', _convite(cenario.cargos_x['usuario'], {'fazenda_id': cenario.f1.pk}, cpf_novo()))
    assert convite.status_code == 201
    pessoa_id, concessao_id = convite.json()['id'], convite.json()['concessao_id']
    assert pessoa_id in {p['id'] for p in _enviar(admin, 'pessoas', metodo='get').json()}
    assert pessoa_id not in {p['id'] for p in _enviar(admin_y, 'pessoas', metodo='get').json()}
    assert {c['empresa_id'] for c in _enviar(admin, 'cargos', metodo='get').json()} == {cenario.x.pk}
    assert _enviar(admin_y, f'pessoas/{pessoa_id}/concessoes/{concessao_id}', metodo='delete').status_code in (403, 404)
    assert _enviar(admin_y, f'pessoas/{pessoa_id}/redefinir-senha').status_code in (403, 404)
    assert _enviar(admin, f'pessoas/{pessoa_id}/redefinir-senha').status_code == 204
    assert _enviar(admin, f'pessoas/{pessoa_id}/concessoes/{concessao_id}', metodo='delete').status_code == 204


def test_cargo_personalizado_com_redefinir_senha_sem_ser_administrador_nao_redefine(cenario, fabrica_pessoa, conceder_direto):
    # `pode()` aceita a ação; a regra de R5 (só Administrador da empresa) é do `pode_iniciar_redefinicao`.
    cargo = Cargo.objects.create(empresa=cenario.x, nome='Suporte', base='curador')
    CargoPermissao.objects.create(cargo=cargo, permissao_id='redefinir_senha')
    suporte = _com(fabrica_pessoa, conceder_direto, cargo, cenario.x, 'Suporte')
    alvo = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.f1, 'Alvo')
    assert _enviar(suporte, f'pessoas/{alvo.pk}/redefinir-senha').status_code in (403, 404)
    assert not PedidoRedefinicao.objects.filter(pessoa=alvo).exists()
