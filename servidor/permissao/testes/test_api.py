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
    alvo = fabrica_pessoa('Alvo', empresa_origem=cenario.x)
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
    alvo = fabrica_pessoa('Alvo', empresa_origem=cenario.x)
    corpo = {'cargo_id': cenario.cargos_y['usuario'].pk, 'escopo': {'empresa_id': cenario.y.pk}}
    assert _enviar(admin, f'pessoas/{alvo.pk}/concessoes', corpo).status_code in (403, 404)
    assert not Concessao.objects.filter(pessoa=alvo).exists()


def test_cargo_de_outra_empresa_numa_concessao_da_propria_e_negado(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    alvo = fabrica_pessoa('Alvo', empresa_origem=cenario.x)
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


def test_administrador_com_cargo_personalizado_sem_convidar_nem_revogar_convida_e_revoga(cenario, fabrica_pessoa, conceder_direto, cpf_novo):
    # D043: o Administrador convida e revoga sempre, mesmo que o cargo personalizado não liste as duas ações.
    cargo = Cargo.objects.create(empresa=cenario.x, nome='Administrador enxuto', base='administrador')
    CargoPermissao.objects.create(cargo=cargo, permissao_id='ver')
    admin = _com(fabrica_pessoa, conceder_direto, cargo, cenario.x)
    convite = _enviar(admin, 'pessoas', _convite(cenario.cargos_x['usuario'], {'fazenda_id': cenario.f1.pk}, cpf_novo()))
    assert convite.status_code == 201
    revogada = _enviar(admin, f"pessoas/{convite.json()['id']}/concessoes/{convite.json()['concessao_id']}", metodo='delete')
    assert revogada.status_code == 204


def test_curador_com_cargo_personalizado_sem_convidar_nem_revogar_convida_e_revoga_so_na_fazenda_dele(cenario, fabrica_pessoa, conceder_direto, cpf_novo):
    # D073 (mantenedor, 2026-10-31): o Curador, que administra a fazenda, convida e revoga sempre, no escopo dele e abaixo do nível dele.
    usuario = cenario.cargos_x['usuario']
    cargo = Cargo.objects.create(empresa=cenario.x, nome='Curador enxuto', base='curador')
    # O Curador não concede permissão que não tem (D043): leva as do cargo que concede, sem as duas ações de delegação.
    for codigo in CargoPermissao.objects.filter(cargo=usuario).values_list('permissao_id', flat=True):
        CargoPermissao.objects.create(cargo=cargo, permissao_id=codigo)
    assert not CargoPermissao.objects.filter(cargo=cargo, permissao_id__in=('convidar_pessoa', 'revogar_acesso')).exists()
    curador = _com(fabrica_pessoa, conceder_direto, cargo, cenario.f1)
    convite = _enviar(curador, 'pessoas', _convite(usuario, {'fazenda_id': cenario.f1.pk}, cpf_novo()))
    assert convite.status_code == 201
    revogada = _enviar(curador, f"pessoas/{convite.json()['id']}/concessoes/{convite.json()['concessao_id']}", metodo='delete')
    assert revogada.status_code == 204
    total = Pessoa.objects.count()
    assert _enviar(curador, 'pessoas', _convite(usuario, {'fazenda_id': cenario.f2.pk}, cpf_novo())).status_code in (403, 404)
    assert _enviar(curador, 'pessoas', _convite(cenario.cargos_x['administrador'], {'fazenda_id': cenario.f1.pk}, cpf_novo())).status_code == 403
    assert Pessoa.objects.count() == total


def test_lista_de_pessoas_nao_expoe_cpf_nem_hash_de_senha(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    for pessoa in _enviar(admin, 'pessoas', metodo='get').json():
        assert set(pessoa) == {'id', 'nome', 'email', 'empresa_origem_id', 'deve_trocar_senha'}


def test_concede_e_revoga_e_a_revogacao_de_outra_empresa_ou_de_outra_pessoa_e_negada(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    admin_y = _com(fabrica_pessoa, conceder_direto, cenario.cargos_y['administrador'], cenario.y, 'Admin Y')
    alvo, outra = fabrica_pessoa('Alvo', empresa_origem=cenario.x), fabrica_pessoa('Outra', empresa_origem=cenario.x)
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
    # Existente fora do alcance e inexistente respondem igual (404): 403 revelaria que a pessoa existe.
    inexistente = _enviar(admin_y, 'pessoas/999999/redefinir-senha')
    assert inexistente.status_code == 404
    assert _enviar(admin_y, f'pessoas/{alvo.pk}/redefinir-senha').status_code == inexistente.status_code
    assert _enviar(tecnico, f'pessoas/{alvo.pk}/redefinir-senha').status_code == inexistente.status_code
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
    alvo = fabrica_pessoa('Alvo', empresa_origem=cenario.x)
    resposta = _enviar(admin, f'pessoas/{alvo.pk}/concessoes', {'cargo_id': cenario.cargos_x['usuario'].pk, 'escopo': escopo})
    assert resposta.status_code == 422
    assert resposta.json()['detalhe'] == 'entrada_invalida'
    assert not Concessao.objects.filter(pessoa=alvo).exists()


def test_periodo_invalido_e_422_e_nao_500(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    alvo = fabrica_pessoa('Alvo', empresa_origem=cenario.x)
    passado = (timezone.now() - timedelta(days=1)).isoformat()
    corpo = {'cargo_id': cenario.cargos_x['usuario'].pk, 'escopo': {'fazenda_id': cenario.f1.pk}, 'fim': passado}
    assert _enviar(admin, f'pessoas/{alvo.pk}/concessoes', corpo).status_code == 422
    assert not Concessao.objects.filter(pessoa=alvo).exists()


def test_convite_com_e_mail_malformado_nao_grava_pessoa(cenario, fabrica_pessoa, conceder_direto, cpf_novo):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    ruim = _convite(cenario.cargos_x['usuario'], {'fazenda_id': cenario.f1.pk}, cpf_novo(), email='sem-arroba')
    total = Pessoa.objects.count()
    assert _enviar(admin, 'pessoas', ruim).status_code == 422
    assert Pessoa.objects.count() == total


def test_categoria_de_outra_empresa_e_recusada(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    alheia = CategoriaDado.objects.create(empresa=cenario.y, nome='Alheia')
    alvo = fabrica_pessoa('Alvo', empresa_origem=cenario.x)
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
    assert _enviar(admin_y, f'pessoas/{pessoa_id}/redefinir-senha').status_code == 404
    assert _enviar(admin, f'pessoas/{pessoa_id}/redefinir-senha').status_code == 204
    assert _enviar(admin, f'pessoas/{pessoa_id}/concessoes/{concessao_id}', metodo='delete').status_code == 204


def test_cargo_personalizado_com_redefinir_senha_sem_ser_administrador_nao_redefine(cenario, fabrica_pessoa, conceder_direto):
    # `pode()` aceita a ação; a regra de R5 (só Administrador da empresa) é do `pode_iniciar_redefinicao`.
    cargo = Cargo.objects.create(empresa=cenario.x, nome='Suporte', base='curador')
    CargoPermissao.objects.create(cargo=cargo, permissao_id='redefinir_senha')
    suporte = _com(fabrica_pessoa, conceder_direto, cargo, cenario.x, 'Suporte')
    alvo = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.f1, 'Alvo')
    assert _enviar(suporte, f'pessoas/{alvo.pk}/redefinir-senha').status_code == 404
    assert not PedidoRedefinicao.objects.filter(pessoa=alvo).exists()


def test_plataforma_pede_redefinicao_de_outra_conta_da_plataforma_que_nao_tem_empresa(plataforma, fabrica_pessoa):
    outra = fabrica_pessoa('Outra plataforma')
    outra.administrador_plataforma = True
    outra.save(update_fields=['administrador_plataforma'])
    assert _enviar(plataforma, f'pessoas/{outra.pk}/redefinir-senha').status_code == 204
    assert PedidoRedefinicao.objects.filter(pessoa=outra, solicitado_por=plataforma).count() == 1


def test_administrador_de_empresa_nao_redefine_conta_da_plataforma(cenario, plataforma, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    assert _enviar(admin, f'pessoas/{plataforma.pk}/redefinir-senha').status_code == 404
    assert not PedidoRedefinicao.objects.filter(pessoa=plataforma).exists()


def test_administrador_da_segunda_empresa_redefine_pessoa_com_acesso_nas_duas(cenario, fabrica_pessoa, conceder_direto):
    admin_y = _com(fabrica_pessoa, conceder_direto, cenario.cargos_y['administrador'], cenario.y, 'Admin Y')
    colaboradora = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.f1, 'Colaboradora')
    conceder_direto(colaboradora, cenario.cargos_y['usuario'], cenario.fy)
    assert _enviar(admin_y, f'pessoas/{colaboradora.pk}/redefinir-senha').status_code == 204
    assert PedidoRedefinicao.objects.filter(pessoa=colaboradora, solicitado_por=admin_y).count() == 1


def test_concessao_a_pessoa_fora_do_alcance_responde_como_inexistente_e_nao_grava(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    estranha = fabrica_pessoa('Estranha')  # sem origem nem concessão na empresa X: a tabela `pessoa` não tem RLS
    corpo = {'cargo_id': cenario.cargos_x['usuario'].pk, 'escopo': {'fazenda_id': cenario.f1.pk}}
    inexistente = _enviar(admin, 'pessoas/999999/concessoes', corpo)
    assert inexistente.status_code == 404
    assert _enviar(admin, f'pessoas/{estranha.pk}/concessoes', corpo).status_code == inexistente.status_code
    assert not Concessao.objects.filter(pessoa=estranha).exists()


def test_lista_de_pessoas_nao_faz_consulta_por_concessao(cenario, fabrica_pessoa, conceder_direto, django_assert_num_queries):
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    conceder_direto(fabrica_pessoa('Dois', empresa_origem=cenario.x), cenario.cargos_x['usuario'], cenario.g1)

    def consultas():
        with CaptureQueriesContext(connection) as captura:
            assert _enviar(admin, 'pessoas', metodo='get').status_code == 200
        return len(captura)

    poucas = consultas()
    for numero in range(8):
        conceder_direto(fabrica_pessoa(f'Mais {numero}', empresa_origem=cenario.x), cenario.cargos_x['usuario'], cenario.g1)
    assert consultas() == poucas


def test_curador_de_sub_area_lista_a_pessoa_da_filha_e_nao_a_da_irma(cenario, fabrica_pessoa, conceder_direto):
    curador = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['curador'], cenario.g1, 'Curador de G1')
    filha = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.t1, 'Pessoa de T1')
    irma = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.g2, 'Pessoa de G2')
    ids = {p['id'] for p in _enviar(curador, 'pessoas', metodo='get').json()}
    assert filha.pk in ids
    assert irma.pk not in ids


def test_lista_de_pessoas_tem_limite_marcador_e_teto(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    for numero in range(4):
        fabrica_pessoa(f'Da empresa {numero}', empresa_origem=cenario.x)
    primeira = _enviar(admin, 'pessoas?limite=2', metodo='get').json()
    assert len(primeira) == 2
    segunda = _enviar(admin, f'pessoas?limite=2&depois={primeira[-1]["id"]}', metodo='get').json()
    assert len(segunda) == 2
    assert not {p['id'] for p in primeira} & {p['id'] for p in segunda}
    assert min(p['id'] for p in segunda) > max(p['id'] for p in primeira)
    todas = []
    marcador = 0
    while pagina := _enviar(admin, f'pessoas?limite=2&depois={marcador}', metodo='get').json():
        todas += pagina
        marcador = pagina[-1]['id']
    assert len(todas) == len({p['id'] for p in todas}) == 5  # o administrador e as quatro da empresa


@pytest.mark.parametrize('consulta', ['limite=0', 'limite=101', 'depois=-1', 'limite=abc'])
def test_limite_fora_da_faixa_e_422_sem_ecoar_o_valor(cenario, fabrica_pessoa, conceder_direto, consulta):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    resposta = _enviar(admin, f'pessoas?{consulta}', metodo='get')
    assert (resposta.status_code, resposta.json()['detalhe']) == (422, 'entrada_invalida')


def test_pagina_padrao_tem_no_maximo_trinta_pessoas(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    for numero in range(32):
        fabrica_pessoa(f'Da empresa {numero}', empresa_origem=cenario.x)
    assert len(_enviar(admin, 'pessoas', metodo='get').json()) == 30


def test_convite_leva_o_mesmo_tempo_para_cpf_novo_e_existente(cenario, fabrica_pessoa, conceder_direto, cpf_novo, smtp_lento):
    # T5.5c, R24, A2: 15 rodadas de cada caso (30 convites, abaixo da cota de 50 por hora).
    # Folga de 20 ms contra o resíduo medido em 2026-10-29 (5 a 7 ms; sem o Argon2 equivalente a diferença é de 35 ms); o e-mail sai pela fila real (`smtp_lento`, 200 ms por envio): a resposta tem de voltar antes dele.
    import statistics
    import time

    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    cabecalho = {'Authorization': f'Bearer {sessao.emitir_acesso(admin, "teste")}'}
    cargo, escopo = cenario.cargos_x['usuario'], {'fazenda_id': cenario.f1.pk}

    def medir(cpfs):
        tempos = []
        for cpf in cpfs:
            inicio = time.perf_counter()
            resposta = Client().post('/api/v1/pessoas', data=json.dumps(_convite(cargo, escopo, cpf)), content_type='application/json', headers=cabecalho)
            tempos.append(time.perf_counter() - inicio)
            assert resposta.status_code == 201
        return statistics.median(tempos)

    cpfs_existentes = [cpf_novo() for _ in range(15)]
    for cpf in cpfs_existentes:
        Pessoa.objects.criar(nome='Existente', email='existente@exemplo.test', cpf=cpf)
    novos = medir([cpf_novo() for _ in range(15)])
    existente = medir(cpfs_existentes)
    smtp_lento.esvaziar()
    assert len(smtp_lento.enviados) == 30  # o callback rodou nos dois caminhos (CodeRabbit, PR #17)
    assert max(novos, existente) < smtp_lento.atraso * 0.75  # envio síncrono somaria 200 ms aos dois
    assert abs(novos - existente) < 0.02
