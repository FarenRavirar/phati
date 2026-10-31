"""Início (R9, R22; A7): convites pendentes com Aceitar e Recusar, fazendas acessíveis e o estado vazio."""

import re

from django.test import Client

from permissao.models import Concessao, Convite
from projeto.testes.conftest import SENHA


def _chave_em(html):
    achada = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', html)
    assert achada is not None
    return achada.group(1)


def _entrar_com_csrf(conta):
    cliente = Client(enforce_csrf_checks=True)
    chave = _chave_em(cliente.get('/entrar').content.decode())
    cliente.post('/entrar', {'cpf': conta.cpf, 'senha': SENHA, 'csrfmiddlewaretoken': chave})
    return cliente


def _sem_nonce(resposta):
    return re.sub(rb'nonce="[^"]*"', b'', resposta.content)


def _chave_da_pagina(cliente):
    return _chave_em(cliente.get('/').content.decode())


def test_sem_convite_nem_fazenda_diz_sem_pendencias(cliente_logado):
    html = cliente_logado.get('/').content.decode()
    assert 'Sem pendências.' in html
    assert 'Convites' not in html


def test_convite_aparece_com_empresa_cargo_validade_e_os_dois_botoes(cliente_logado, convite_pendente):
    html = cliente_logado.get('/').content.decode()
    assert 'Empresa X' in html
    assert 'Cargo: Usuário' in html
    assert f'/convites/{convite_pendente.pk}/aceitar' in html
    assert f'/convites/{convite_pendente.pk}/recusar' in html
    assert 'Sem pendências.' not in html


def test_aceitar_cria_a_concessao_e_o_convite_sai_da_lista(cliente_logado, convite_pendente, conta, cenario):
    assert not Concessao.objects.filter(pessoa=conta.pessoa).exists()
    resposta = cliente_logado.post(f'/convites/{convite_pendente.pk}/aceitar')
    assert (resposta.status_code, resposta['Location']) == (302, '/')
    assert Concessao.objects.filter(pessoa=conta.pessoa, fazenda=cenario.f1).exists()
    html = cliente_logado.get('/').content.decode()
    assert f'/convites/{convite_pendente.pk}/' not in html
    assert 'F1' in html  # a fazenda aparece em "Suas fazendas"


def test_recusar_tira_o_convite_sem_criar_concessao(cliente_logado, convite_pendente, conta):
    resposta = cliente_logado.post(f'/convites/{convite_pendente.pk}/recusar')
    assert resposta.status_code == 302
    assert not Concessao.objects.filter(pessoa=conta.pessoa).exists()
    assert Convite.objects.get(pk=convite_pendente.pk).recusado_em is not None
    assert 'Sem pendências.' in cliente_logado.get('/').content.decode()


def test_aceitar_e_recusar_exigem_csrf(conta, convite_pendente):
    cliente = _entrar_com_csrf(conta)
    for acao in ('aceitar', 'recusar'):
        assert cliente.post(f'/convites/{convite_pendente.pk}/{acao}').status_code == 403
    assert not Concessao.objects.filter(pessoa=conta.pessoa).exists()
    resposta = cliente.post(f'/convites/{convite_pendente.pk}/aceitar', {'csrfmiddlewaretoken': _chave_da_pagina(cliente)})
    assert resposta.status_code == 302


def test_consulta_nao_responde_ao_convite(cliente_logado, convite_pendente):
    assert cliente_logado.get(f'/convites/{convite_pendente.pk}/aceitar').status_code == 405
    assert cliente_logado.get(f'/convites/{convite_pendente.pk}/recusar').status_code == 405


def test_convite_de_outra_pessoa_e_convite_inexistente_dao_o_mesmo_404(cliente_logado, convite_pendente, fabrica_pessoa):
    outra = fabrica_pessoa('Outra pessoa')
    Convite.objects.filter(pk=convite_pendente.pk).update(pessoa=outra)
    alheio = cliente_logado.post(f'/convites/{convite_pendente.pk}/aceitar')
    inexistente = cliente_logado.post('/convites/999999/aceitar')
    assert (alheio.status_code, inexistente.status_code) == (404, 404)
    assert _sem_nonce(alheio) == _sem_nonce(inexistente)  # o nonce da política de conteúdo muda a cada resposta
    assert not Concessao.objects.filter(pessoa=outra).exists()


def test_convite_ja_respondido_mostra_o_motivo_sem_segunda_concessao(cliente_logado, convite_pendente, conta):
    cliente_logado.post(f'/convites/{convite_pendente.pk}/recusar')
    resposta = cliente_logado.post(f'/convites/{convite_pendente.pk}/aceitar')
    assert resposta.status_code == 200
    assert 'Convite já respondido.' in resposta.content.decode()
    assert not Concessao.objects.filter(pessoa=conta.pessoa).exists()


def test_deslogado_vai_a_entrada_com_a_pagina_pedida():
    resposta = Client().get('/')
    assert resposta.status_code == 302
    assert resposta['Location'].startswith('/entrar?proximo=')
    assert Client().post('/convites/1/aceitar').status_code == 302


def test_senha_temporaria_so_alcanca_a_troca(cliente_logado, conta):
    conta.pessoa.deve_trocar_senha = True
    conta.pessoa.save(update_fields=['deve_trocar_senha'])
    assert cliente_logado.get('/').status_code == 302
    assert cliente_logado.get('/')['Location'].startswith('/trocar-senha')
    assert cliente_logado.post('/convites/1/aceitar')['Location'].startswith('/trocar-senha')
