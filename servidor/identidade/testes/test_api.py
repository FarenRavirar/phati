"""Rotas de identidade pela URL real (Client do Django: middleware, cookie e CSRF valem): A2, A4, A14, R5, R15."""

import json
import re

import pytest
from django.test import Client

from identidade import senha, sessao
from identidade.testes.conftest import CPF, SENHA

NOVA = 'outra-senha-bem-longa'


def _enviar(cliente, rota, corpo=None, headers=None):
    return cliente.post(f'/api/v1/{rota}', data=json.dumps(corpo or {}), content_type='application/json', headers=headers)


def _entrar(cliente, cpf=CPF, senha_digitada=SENHA, **extras):
    return _enviar(cliente, 'entrar', {'cpf': cpf, 'senha': senha_digitada, **extras})


def test_entrada_com_cpf_inexistente_e_com_senha_errada_sao_indistinguiveis(pessoa):
    inexistente = _entrar(Client(), cpf='529.982.247-25')
    errada = _entrar(Client(), senha_digitada='senha errada qualquer')
    assert inexistente.status_code == errada.status_code == 401
    assert inexistente.content == errada.content
    ignorados = {'Date', 'Content-Length'}
    assert {k: v for k, v in inexistente.items() if k not in ignorados} == {k: v for k, v in errada.items() if k not in ignorados}


def test_entrada_do_navegador_define_o_cookie_de_sessao_com_os_tres_atributos(pessoa):
    resposta = _entrar(Client())
    assert resposta.status_code == 200
    assert resposta.json() == {'deve_trocar_senha': False, 'segredo': None}
    cookie = resposta.cookies['sessionid']
    assert cookie['httponly']
    assert cookie['secure']
    assert cookie['samesite'] == 'Lax'
    assert 'csrftoken' in resposta.cookies


def test_entrada_do_aplicativo_devolve_segredo_e_nao_define_cookie_de_sessao(pessoa):
    resposta = _entrar(Client(), dispositivo='celular')
    assert resposta.status_code == 200
    assert resposta.json()['segredo']
    assert 'sessionid' not in resposta.cookies


def test_primeiro_acesso_com_senha_temporaria_avisa_que_deve_trocar_e_usa_uma_vez(pessoa):
    temporaria = senha.emitir_senha_temporaria(pessoa)
    primeira = _entrar(Client(), senha_digitada=temporaria)
    assert primeira.json()['deve_trocar_senha'] is True
    assert _entrar(Client(), senha_digitada=temporaria).status_code == 401


def test_entrada_mantem_corpo_e_codigos_do_contrato(pessoa):
    # T1.3: o contrato do aplicativo não muda com a extração para `acesso.entrar`.
    assert _entrar(Client(), senha_digitada='senha errada qualquer').json() == {'detalhe': 'credenciais_invalidas'}
    aplicativo = _entrar(Client(), dispositivo='celular')
    assert (aplicativo.status_code, set(aplicativo.json())) == (200, {'deve_trocar_senha', 'segredo'})
    assert aplicativo.json()['deve_trocar_senha'] is False


def test_entrada_invalida_devolve_422_sem_ecoar_o_valor_recebido(pessoa):
    resposta = _enviar(Client(), 'entrar', {'cpf': CPF, 'senha': ['marcador-secreto-9137']})
    assert resposta.status_code == 422
    assert 'marcador-secreto-9137' not in resposta.content.decode()
    assert resposta.json()['campos'] == [{'campo': ['body', 'dados', 'senha'], 'tipo': 'string_type'}]


def test_sair_sem_cookie_csrf_e_negado_e_com_cookie_encerra_a_sessao(pessoa):
    cliente = Client(enforce_csrf_checks=True)
    _entrar(cliente)
    assert _enviar(cliente, 'sair').status_code == 403
    chave_csrf = cliente.cookies['csrftoken'].value
    assert _enviar(cliente, 'sair', headers={'X-CSRFToken': chave_csrf}).status_code == 204
    assert _enviar(cliente, 'sair', headers={'X-CSRFToken': chave_csrf}).status_code == 401


def test_sair_sem_entrada_e_negado(db):
    assert _enviar(Client(), 'sair').status_code == 401


def test_trocar_senha_invalida_a_sessao_aberta_e_o_acesso_do_aplicativo(pessoa):
    navegador, aplicativo = Client(), Client()
    _entrar(navegador)
    segredo = _entrar(aplicativo, dispositivo='celular').json()['segredo']
    cabecalho = {'Authorization': f'Bearer {segredo}'}
    resposta = _enviar(navegador, 'trocar-senha', {'senha_atual': SENHA, 'senha_nova': NOVA})
    assert resposta.status_code == 204
    assert _enviar(navegador, 'sair').status_code == 401
    assert _enviar(aplicativo, 'sair', headers=cabecalho).status_code == 401


def test_trocar_senha_com_senha_atual_errada_devolve_o_codigo_da_regra(pessoa):
    cliente = Client()
    _entrar(cliente)
    resposta = _enviar(cliente, 'trocar-senha', {'senha_atual': 'errada errada errada', 'senha_nova': NOVA})
    assert resposta.status_code == 400
    assert resposta.json() == {'detalhe': 'senha_atual_incorreta'}


def test_acesso_do_aplicativo_rotaciona_a_cada_renovacao_e_o_anterior_deixa_de_valer(pessoa):
    primeiro = _entrar(Client(), dispositivo='celular').json()['segredo']
    renovado = _enviar(Client(), 'acesso/renovar', {'segredo': primeiro})
    assert renovado.status_code == 200
    segundo = renovado.json()['segredo']
    assert segundo != primeiro
    assert _enviar(Client(), 'sair', headers={'Authorization': f'Bearer {primeiro}'}).status_code == 401  # já não autentica
    assert _enviar(Client(), 'acesso/renovar', {'segredo': primeiro}).status_code == 200  # dentro da janela, ainda renova
    assert _enviar(Client(), 'sair', headers={'Authorization': f'Bearer {primeiro}'}).status_code == 401
    assert _enviar(Client(), 'sair', headers={'Authorization': f'Bearer {segundo}'}).status_code == 204


def test_sair_do_aplicativo_encerra_so_aquele_dispositivo(pessoa):
    celular = _entrar(Client(), dispositivo='celular').json()['segredo']
    tablet = _entrar(Client(), dispositivo='tablet').json()['segredo']
    assert _enviar(Client(), 'sair', headers={'Authorization': f'Bearer {celular}'}).status_code == 204
    assert _enviar(Client(), 'sair', headers={'Authorization': f'Bearer {celular}'}).status_code == 401
    assert _enviar(Client(), 'sair', headers={'Authorization': f'Bearer {tablet}'}).status_code == 204


@pytest.mark.parametrize('cpf', [CPF, '529.982.247-25', 'nao e cpf'])
def test_pedido_de_redefinicao_e_neutro_para_cpf_existente_inexistente_e_invalido(pessoa, cpf):
    resposta = _enviar(Client(), 'redefinir-senha/solicitar', {'cpf': cpf})
    assert resposta.status_code == 204
    assert resposta.content == b''


def test_redefinicao_pela_api_troca_a_senha_e_nao_abre_sessao(pessoa, mailoutbox):
    _enviar(Client(), 'redefinir-senha/solicitar', {'cpf': CPF})
    segredo = re.findall(r'segredo=(\S+)', mailoutbox[-1].body)[-1]
    cliente = Client()
    resposta = _enviar(cliente, 'redefinir-senha/confirmar', {'segredo': segredo, 'senha_nova': NOVA})
    assert resposta.status_code == 204
    assert 'sessionid' not in resposta.cookies
    assert _enviar(cliente, 'sair').status_code == 401
    assert _entrar(Client(), senha_digitada=NOVA).status_code == 200
    assert _enviar(Client(), 'redefinir-senha/confirmar', {'segredo': segredo, 'senha_nova': NOVA}).json() == {'detalhe': 'link_invalido'}


def test_primeiro_acesso_so_alcanca_trocar_senha_e_sair_ate_trocar(pessoa):
    temporaria = senha.emitir_senha_temporaria(pessoa)
    segredo = _entrar(Client(), senha_digitada=temporaria, dispositivo='celular').json()['segredo']
    cabecalho = {'Authorization': f'Bearer {segredo}'}
    bloqueada = Client().get('/api/v1/fazendas', headers=cabecalho)
    assert (bloqueada.status_code, bloqueada.json()) == (403, {'detalhe': 'troca_de_senha_obrigatoria'})
    assert _enviar(Client(), 'trocar-senha', {'senha_atual': temporaria, 'senha_nova': NOVA}, headers=cabecalho).status_code == 204


@pytest.mark.parametrize('tamanho, status', [(0, 422), (1, 200), (200, 200), (201, 422)])
def test_dispositivo_respeita_o_limite_da_coluna(pessoa, tamanho, status):
    assert _entrar(Client(), dispositivo='d' * tamanho).status_code == status


def test_corpo_que_nao_e_json_declarado_nao_cria_sessao(pessoa):
    # Achado do Qodo (PR #14): formulário text/plain de outro site entrava como JSON e criava sessão (login CSRF).
    corpo = json.dumps({'cpf': CPF, 'senha': SENHA})
    resposta = Client().post('/api/v1/entrar', data=corpo, content_type='text/plain')
    assert resposta.status_code == 400
    assert 'sessionid' not in resposta.cookies


def test_erro_de_autenticacao_usa_a_mesma_chave_dos_outros_erros(db):
    resposta = _enviar(Client(), 'sair')
    assert resposta.status_code == 401
    assert set(resposta.json()) == {'detalhe'}


def test_sair_com_cookie_e_bearer_encerra_os_dois(pessoa):
    # Achado do Qodo (PR #14): com os dois, o cookie ganhava e o segredo seguia valendo.
    cliente = Client()
    _entrar(cliente)
    segredo = _entrar(Client(), dispositivo='celular').json()['segredo']
    assert _enviar(cliente, 'sair', headers={'Authorization': f'Bearer {segredo}'}).status_code == 204
    assert _enviar(Client(), 'sair', headers={'Authorization': f'Bearer {segredo}'}).status_code == 401
    assert _enviar(cliente, 'sair').status_code == 401


def test_falha_ao_emitir_o_acesso_nao_consome_a_senha_temporaria(pessoa, monkeypatch):
    # Achado do Sourcery (PR #14): autenticar e emitir ficam na mesma transação.
    temporaria = senha.emitir_senha_temporaria(pessoa)

    def falha(*_):
        raise OSError('banco fora')

    with monkeypatch.context() as parcial:
        parcial.setattr(sessao, 'emitir_acesso', falha)
        resposta = _entrar(Client(raise_request_exception=False), senha_digitada=temporaria, dispositivo='celular')
    assert resposta.status_code == 500
    assert _entrar(Client(), senha_digitada=temporaria).status_code == 200


def test_aplicativo_escreve_sem_cookie_nem_chave_csrf(pessoa):
    # Achado do CodeRabbit (PR #14): o `APIKeyCookie` conferia o CSRF antes do Bearer e o aplicativo, que não tem
    # cookie, levava 403 em toda escrita. O `Client` comum não confere CSRF e escondia o defeito.
    segredo = _entrar(Client(), dispositivo='celular').json()['segredo']
    cliente = Client(enforce_csrf_checks=True)
    resposta = _enviar(cliente, 'trocar-senha', {'senha_atual': SENHA, 'senha_nova': NOVA}, headers={'Authorization': f'Bearer {segredo}'})
    assert resposta.status_code == 204


def test_cookie_sem_chave_csrf_continua_negado_mesmo_com_acesso_invalido(pessoa):
    cliente = Client(enforce_csrf_checks=True)
    _entrar(cliente)
    resposta = _enviar(cliente, 'trocar-senha', {'senha_atual': SENHA, 'senha_nova': NOVA}, headers={'Authorization': 'Bearer invalido'})
    assert resposta.status_code == 403


@pytest.mark.parametrize('esquema', ['Bearer', 'bearer', 'BEARER'])
def test_sair_revoga_o_acesso_com_o_esquema_em_qualquer_caixa(pessoa, esquema):
    # Achado do Codex (PR #14): o HttpBearer do ninja compara o esquema em minúsculas e `sair` só reconhecia "Bearer".
    segredo = _entrar(Client(), dispositivo='celular').json()['segredo']
    assert _enviar(Client(), 'sair', headers={'Authorization': f'{esquema} {segredo}'}).status_code == 204
    assert _enviar(Client(), 'sair', headers={'Authorization': f'Bearer {segredo}'}).status_code == 401


def test_solicitar_redefinicao_responde_antes_do_pedido_ser_gravado(pessoa, monkeypatch):
    # PR #20: a rota pública só enfileira; CPF existente e inexistente voltam no mesmo tempo.
    from identidade import email
    from identidade.models import PedidoRedefinicao

    fila = []
    monkeypatch.setattr(email, '_despachar', fila.append)
    assert _enviar(Client(), 'redefinir-senha/solicitar', {'cpf': CPF}).status_code == 204
    assert not PedidoRedefinicao.objects.exists()
    fila.pop()()
    assert PedidoRedefinicao.objects.count() == 1
