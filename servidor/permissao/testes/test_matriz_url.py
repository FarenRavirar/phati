"""Matriz cargo × rota por URL direta (A9, R19; T5.5b item 3), com as expectativas escritas à mão.

Roda duas vezes: como o dono do banco e como o papel `app`, em que a RLS vale e o alvo fora do escopo some (a rota
responde 404 em vez de 403: as duas respostas são negação). Nenhuma expectativa vem de `cargo_permissao`.
"""

import json
from importlib import import_module
from types import SimpleNamespace

import pytest
from django.test import Client

from identidade import sessao
from permissao.cargos_base import criar_cargos_base
from permissao.models import Permissao
from territorio.models import Empresa, Fazenda

pytestmark = pytest.mark.django_db(transaction=True, databases=['default', 'app'])

OK, NEGADO, VAZIA = 'permitido', 'negado', 'lista vazia'

# (rótulo da rota, método, caminho com {x} {y} {f1} {fy}) e, por pessoa, o que a URL direta deve dar.
MATRIZ = {
    ('criar empresa', 'post', 'empresas'): {
        'plataforma': OK, 'admin_x': NEGADO, 'curador_f1': NEGADO, 'tecnico_f1': NEGADO,
        'usuario_f1': NEGADO, 'sem_acesso': NEGADO, 'admin_y': NEGADO,
    },
    ('criar fazenda em X', 'post', 'empresas/{x}/fazendas'): {
        'plataforma': OK, 'admin_x': OK, 'curador_f1': NEGADO, 'tecnico_f1': NEGADO,
        'usuario_f1': NEGADO, 'sem_acesso': NEGADO, 'admin_y': NEGADO,
    },
    ('criar fazenda em Y', 'post', 'empresas/{y}/fazendas'): {
        'plataforma': OK, 'admin_x': NEGADO, 'curador_f1': NEGADO, 'tecnico_f1': NEGADO,
        'usuario_f1': NEGADO, 'sem_acesso': NEGADO, 'admin_y': OK,
    },
    ('listar fazendas', 'get', 'fazendas'): {
        'plataforma': OK, 'admin_x': OK, 'curador_f1': OK, 'tecnico_f1': OK,
        'usuario_f1': OK, 'sem_acesso': VAZIA, 'admin_y': OK,
    },
    ('criar sub-área em F1', 'post', 'fazendas/{f1}/sub-areas'): {
        'plataforma': OK, 'admin_x': OK, 'curador_f1': NEGADO, 'tecnico_f1': NEGADO,
        'usuario_f1': NEGADO, 'sem_acesso': NEGADO, 'admin_y': NEGADO,
    },
    ('criar sub-área em FY', 'post', 'fazendas/{fy}/sub-areas'): {
        'plataforma': OK, 'admin_x': NEGADO, 'curador_f1': NEGADO, 'tecnico_f1': NEGADO,
        'usuario_f1': NEGADO, 'sem_acesso': NEGADO, 'admin_y': OK,
    },
    ('listar pessoas', 'get', 'pessoas'): {
        'plataforma': OK, 'admin_x': OK, 'curador_f1': OK, 'tecnico_f1': VAZIA,
        'usuario_f1': VAZIA, 'sem_acesso': VAZIA, 'admin_y': OK,
    },
    ('listar cargos', 'get', 'cargos'): {
        'plataforma': OK, 'admin_x': OK, 'curador_f1': OK, 'tecnico_f1': VAZIA,
        'usuario_f1': VAZIA, 'sem_acesso': VAZIA, 'admin_y': OK,
    },
    ('listar o catálogo', 'get', 'permissoes'): {
        'plataforma': OK, 'admin_x': OK, 'curador_f1': OK, 'tecnico_f1': VAZIA,
        'usuario_f1': VAZIA, 'sem_acesso': VAZIA, 'admin_y': OK,
    },
}


@pytest.fixture
def mundo(fabrica_pessoa, conceder_direto, plataforma):
    for codigo, descricao, delegavel in import_module('permissao.migrations.0001_initial').ACOES:
        Permissao.objects.get_or_create(codigo=codigo, defaults={'descricao': descricao, 'delegavel': delegavel})
    x, y = Empresa.objects.create(nome='Empresa X'), Empresa.objects.create(nome='Empresa Y')
    cargos_x, cargos_y = criar_cargos_base(x), criar_cargos_base(y)
    f1, fy = Fazenda.objects.create(empresa=x, nome='F1'), Fazenda.objects.create(empresa=y, nome='FY')
    pessoas = {'plataforma': plataforma, 'sem_acesso': fabrica_pessoa('Sem acesso')}
    for chave, cargo, escopo in (
        ('admin_x', cargos_x['administrador'], x), ('curador_f1', cargos_x['curador'], f1),
        ('tecnico_f1', cargos_x['tecnico'], f1), ('usuario_f1', cargos_x['usuario'], f1),
        ('admin_y', cargos_y['administrador'], y),
    ):
        pessoas[chave] = fabrica_pessoa(chave)
        conceder_direto(pessoas[chave], cargo, escopo)
    return SimpleNamespace(pessoas=pessoas, ids={'x': x.pk, 'y': y.pk, 'f1': f1.pk, 'fy': fy.pk})


def _chamar(pessoa, metodo, caminho, cpf_novo):
    cpf = cpf_novo()
    corpo = {'nome': f'Nova {cpf}', 'nome_administrador': 'Ana', 'email_administrador': 'ana@exemplo.test', 'cpf_administrador': cpf}  # nome único: a regra de nome ativo recusa repetição
    cabecalho = {'Authorization': f'Bearer {sessao.emitir_acesso(pessoa, "teste")}'}
    cliente = Client()
    if metodo == 'get':
        return cliente.get(f'/api/v1/{caminho}', headers=cabecalho)
    return cliente.post(f'/api/v1/{caminho}', data=json.dumps(corpo), content_type='application/json', headers=cabecalho)


def _divergencias(mundo, cpf_novo):
    divergencias = []
    for (rotulo, metodo, modelo), esperado in MATRIZ.items():
        caminho = modelo.format(**mundo.ids)
        for chave, expectativa in esperado.items():
            resposta = _chamar(mundo.pessoas[chave], metodo, caminho, cpf_novo)
            if expectativa == NEGADO:
                certo = resposta.status_code in (403, 404)
            elif expectativa == VAZIA:
                certo = resposta.status_code == 200 and resposta.json() == []
            else:
                certo = resposta.status_code in (200, 201) and resposta.json() != []
            if not certo:
                divergencias.append((rotulo, chave, expectativa, resposta.status_code))
    return divergencias


def test_matriz_como_dono_do_banco(mundo, cpf_novo):
    assert _divergencias(mundo, cpf_novo) == []


def test_matriz_como_papel_app_com_rls(mundo, como_app, cpf_novo):
    assert _divergencias(mundo, cpf_novo) == []


def test_sem_credencial_toda_rota_protegida_responde_401(mundo):
    cliente = Client()
    for (_, metodo, modelo) in MATRIZ:
        resposta = getattr(cliente, metodo)(f'/api/v1/{modelo.format(**mundo.ids)}')
        assert resposta.status_code == 401, modelo
