"""Instância da API: tratamento de erro e as duas autenticações (R15, R17; A4)."""

import json
import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied, ValidationError
from django.test import RequestFactory
from django.urls import ResolverMatch
from ninja.errors import HttpError
from ninja.errors import ValidationError as ErroDeEntrada

from identidade import sessao
from projeto import api as api_do_projeto
from projeto.api import AutenticacaoAplicativo, AutenticacaoNavegador, _liberar


def _requisicao(url_name=None):
    requisicao = RequestFactory().get('/')
    requisicao.resolver_match = ResolverMatch(func=lambda: None, args=(), kwargs={}, url_name=url_name)
    requisicao.session = SessionStore()
    return requisicao


def _corpo(resposta):
    return resposta.status_code, json.loads(resposta.content)


def test_erro_de_entrada_nao_devolve_o_valor_recusado():
    erro = ErroDeEntrada([{'loc': ('body', 'senha'), 'type': 'string_type', 'msg': 'x', 'input': 'valor-secreto-731'}])
    status, corpo = _corpo(api_do_projeto.entrada_invalida(_requisicao(), erro))
    assert status == 422
    assert 'valor-secreto-731' not in json.dumps(corpo)
    assert corpo == {'detalhe': 'entrada_invalida', 'campos': [{'campo': ['body', 'senha'], 'tipo': 'string_type'}]}


def test_regra_recusada_devolve_so_o_codigo_e_sem_codigo_devolve_invalido():
    assert _corpo(api_do_projeto.regra_recusada(_requisicao(), ValidationError('texto interno', code='cpf_duplicado'))) == (
        400, {'detalhe': 'cpf_duplicado'}
    )
    assert _corpo(api_do_projeto.regra_recusada(_requisicao(), ValidationError('texto interno'))) == (400, {'detalhe': 'invalido'})


def test_permissao_negada_e_objeto_ausente_viram_403_e_404():
    assert _corpo(api_do_projeto.negado(_requisicao(), PermissionDenied())) == (403, {'detalhe': 'negado'})
    assert _corpo(api_do_projeto.nao_encontrado(_requisicao(), ObjectDoesNotExist())) == (404, {'detalhe': 'nao_encontrado'})


def test_pessoa_que_deve_trocar_a_senha_so_passa_nas_rotas_da_troca(fabrica_pessoa):
    pessoa = fabrica_pessoa()
    pessoa.deve_trocar_senha = True
    for liberada in ('trocar_senha', 'sair'):
        assert _liberar(_requisicao(liberada), pessoa) is pessoa
    for bloqueada in ('fazendas_listar', None):
        with pytest.raises(HttpError) as erro:
            _liberar(_requisicao(bloqueada), pessoa)
        assert erro.value.status_code == 403


def test_pessoa_sem_troca_pendente_passa_e_vira_o_usuario_da_requisicao(fabrica_pessoa):
    pessoa = fabrica_pessoa()
    requisicao = _requisicao('fazendas_listar')
    assert _liberar(requisicao, pessoa) is pessoa
    assert requisicao.user is pessoa


def test_navegador_sem_cookie_ou_com_sessao_vencida_nao_autentica(fabrica_pessoa):
    autenticacao = AutenticacaoNavegador()
    assert autenticacao.authenticate(_requisicao(), None) is None
    requisicao = _requisicao()
    requisicao.user = fabrica_pessoa()  # cookie presente, mas a sessão não tem `entrada_em`
    assert autenticacao.authenticate(requisicao, 'qualquer') is None


def test_aplicativo_com_segredo_desconhecido_ou_revogado_nao_autentica(fabrica_pessoa):
    pessoa = fabrica_pessoa()
    autenticacao = AutenticacaoAplicativo()
    assert autenticacao.authenticate(_requisicao(), 'segredo-que-nao-existe') is None
    segredo = sessao.emitir_acesso(pessoa, 'celular')
    requisicao = _requisicao('fazendas_listar')
    autenticada = autenticacao.authenticate(requisicao, segredo)
    assert autenticada is not None and autenticada.pk == pessoa.pk
    assert getattr(requisicao, 'segredo_do_acesso') == segredo
    sessao.revogar_acesso(segredo)
    assert autenticacao.authenticate(_requisicao(), segredo) is None
