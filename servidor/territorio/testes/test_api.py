"""Rotas territoriais pela URL real: A7 (15 fazendas, listagem só das autorizadas, sem autocadastro), R7, R14 e RLS."""

import json
from types import SimpleNamespace

import pytest
from django.test import Client

from identidade import sessao
from permissao.models import Cargo, CargoPermissao, Permissao
from territorio.models import Empresa, Fazenda


def _cabecalho(pessoa):
    return {'Authorization': f'Bearer {sessao.emitir_acesso(pessoa, "teste")}'}


def _enviar(pessoa, rota, corpo=None, metodo='post'):
    chamar = getattr(Client(), metodo)
    if metodo == 'get':
        return chamar(f'/api/v1/{rota}', headers=_cabecalho(pessoa))
    return chamar(f'/api/v1/{rota}', data=json.dumps(corpo or {}), content_type='application/json', headers=_cabecalho(pessoa))


def _com(fabrica_pessoa, conceder_direto, cargo, escopo, nome='Pessoa'):
    pessoa = fabrica_pessoa(nome)
    conceder_direto(pessoa, cargo, escopo)
    return pessoa


def test_sem_entrada_nenhuma_rota_territorial_responde(db):
    cliente = Client()
    assert cliente.get('/api/v1/fazendas').status_code == 401
    assert cliente.post('/api/v1/empresas', data='{}', content_type='application/json').status_code == 401


def test_plataforma_cria_empresa_e_recebe_a_senha_temporaria_do_primeiro_administrador(plataforma, cpf_novo):
    corpo = {'nome': 'Empresa Nova', 'nome_administrador': 'Ana', 'email_administrador': 'ana@exemplo.test', 'cpf_administrador': cpf_novo()}
    resposta = _enviar(plataforma, 'empresas', corpo)
    assert resposta.status_code == 201
    assert resposta.json()['senha_temporaria']
    assert Empresa.objects.filter(nome='Empresa Nova').exists()


def test_administrador_de_empresa_nao_cria_empresa_e_nao_existe_autocadastro(cenario, fabrica_pessoa, conceder_direto, cpf_novo):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    corpo = {'nome': 'Intrusa', 'nome_administrador': 'Ivo', 'email_administrador': 'ivo@exemplo.test', 'cpf_administrador': cpf_novo()}
    assert _enviar(admin, 'empresas', corpo).status_code == 403
    assert not Empresa.objects.filter(nome='Intrusa').exists()
    assert Client().post('/api/v1/pessoas', data=json.dumps({}), content_type='application/json').status_code in (401, 404, 405)


def test_administrador_cria_quinze_fazendas_uma_a_uma_e_so_na_propria_empresa(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    for numero in range(15):
        assert _enviar(admin, f'empresas/{cenario.x.pk}/fazendas', {'nome': f'Fazenda {numero}'}).status_code == 201
    assert Fazenda.objects.filter(empresa=cenario.x).count() == 15 + 2  # as 15 mais F1 e F2 do cenário
    assert _enviar(admin, f'empresas/{cenario.y.pk}/fazendas', {'nome': 'Invasora'}).status_code == 403
    assert not Fazenda.objects.filter(nome='Invasora').exists()


@pytest.mark.parametrize('base', ['curador', 'tecnico', 'usuario'])
def test_cargo_abaixo_de_administrador_nao_cria_fazenda_nem_sub_area(cenario, fabrica_pessoa, conceder_direto, base):
    pessoa = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x[base], cenario.f1)
    assert _enviar(pessoa, f'empresas/{cenario.x.pk}/fazendas', {'nome': 'Nova'}).status_code == 403
    assert _enviar(pessoa, f'fazendas/{cenario.f1.pk}/sub-areas', {'nome': 'Nova'}).status_code == 403


def test_usuario_lista_so_as_fazendas_autorizadas_e_administrador_de_outra_empresa_lista_zero(cenario, fabrica_pessoa, conceder_direto):
    usuario = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['usuario'], cenario.f1, 'Usuario')
    outro = _com(fabrica_pessoa, conceder_direto, cenario.cargos_y['administrador'], cenario.y, 'Outro')
    sem_acesso = fabrica_pessoa('Sem acesso')
    assert [f['nome'] for f in _enviar(usuario, 'fazendas', metodo='get').json()] == ['F1']
    assert [f['nome'] for f in _enviar(outro, 'fazendas', metodo='get').json()] == ['FY']
    assert _enviar(sem_acesso, 'fazendas', metodo='get').json() == []


def test_sub_area_cria_filha_e_recusa_pai_de_outra_fazenda(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    filha = _enviar(admin, f'fazendas/{cenario.f1.pk}/sub-areas', {'nome': 'Nova', 'pai_id': cenario.g1.pk})
    assert filha.status_code == 201
    assert filha.json()['nivel'] == 2
    outra = _enviar(admin, f'fazendas/{cenario.f2.pk}/sub-areas', {'nome': 'Torta', 'pai_id': cenario.g1.pk})
    assert (outra.status_code, outra.json()) == (400, {'detalhe': 'pai_de_outra_fazenda'})


def test_fazenda_inexistente_responde_404_e_nao_500(cenario, fabrica_pessoa, conceder_direto):
    admin = _com(fabrica_pessoa, conceder_direto, cenario.cargos_x['administrador'], cenario.x)
    assert _enviar(admin, 'fazendas/999999/sub-areas', {'nome': 'X'}).status_code == 404


@pytest.fixture
def mundo_http(transactional_db, fabrica_pessoa, conceder_direto):
    """X (F1 e F2) e Y (FY), montados pelo dono; o teste transacional esvazia o catálogo, então as ações vêm daqui."""
    for codigo in ('ver', 'criar_fazenda'):
        Permissao.objects.get_or_create(codigo=codigo, defaults={'descricao': codigo, 'delegavel': True})
    x, y = Empresa.objects.create(nome='Empresa X'), Empresa.objects.create(nome='Empresa Y')
    f1, f2 = Fazenda.objects.create(empresa=x, nome='F1'), Fazenda.objects.create(empresa=x, nome='F2')
    Fazenda.objects.create(empresa=y, nome='FY')
    cargo_x = Cargo.objects.create(empresa=x, nome='Administrador', base='administrador')
    usuario_x = Cargo.objects.create(empresa=x, nome='Usuário', base='usuario')
    for cargo, codigos in ((cargo_x, ('ver', 'criar_fazenda')), (usuario_x, ('ver',))):
        for codigo in codigos:
            CargoPermissao.objects.create(cargo=cargo, permissao_id=codigo)
    admin, usuario = fabrica_pessoa('Admin X'), fabrica_pessoa('Usuario F1')
    conceder_direto(admin, cargo_x, x)
    conceder_direto(usuario, usuario_x, f1)
    return SimpleNamespace(x=x, y=y, f1=f1, f2=f2, admin=admin, usuario=usuario)


@pytest.mark.django_db(transaction=True, databases=['default', 'app'])
def test_sob_o_papel_app_a_listagem_vem_materializada_e_a_empresa_alheia_responde_404(mundo_http, como_app):
    # Sem materializar dentro do bloco, a RLS devolveria lista vazia ao serializar (Sourcery, PR #12).
    assert [f['nome'] for f in _enviar(mundo_http.usuario, 'fazendas', metodo='get').json()] == ['F1']
    assert len(_enviar(mundo_http.admin, 'fazendas', metodo='get').json()) == 2
    criada = _enviar(mundo_http.admin, f'empresas/{mundo_http.x.pk}/fazendas', {'nome': 'F3'})
    assert criada.status_code == 201
    # Y não existe para o papel `app` de quem só tem escopo em X: a RLS esconde, a rota responde 404.
    assert _enviar(mundo_http.admin, f'empresas/{mundo_http.y.pk}/fazendas', {'nome': 'Invasora'}).status_code == 404
