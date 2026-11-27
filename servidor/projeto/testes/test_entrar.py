"""Tela de login (R4, R8; A1, A5): mesma função da API, mensagem única, destino seguro, cookie."""

import re

import pytest
from django.conf import settings
from django.test import Client

from identidade import login, senha
from projeto.testes.conftest import SENHA

FALHA = 'CPF ou senha incorretos.'


def _entrar(cliente, cpf, senha=SENHA, **extras):
    return cliente.post('/entrar', {'cpf': cpf, 'senha': senha, **extras})


def test_entrar_abre_a_sessao_e_leva_ao_destino(conta):
    resposta = _entrar(Client(), conta.cpf)
    assert (resposta.status_code, resposta['Location']) == (302, '/')


@pytest.mark.parametrize('formatar', [lambda c: c, lambda c: f'{c[:3]}.{c[3:6]}.{c[6:9]}-{c[9:]}'])
def test_cpf_com_e_sem_pontuacao_entra(conta, formatar):
    assert _entrar(Client(), formatar(conta.cpf)).status_code == 302


def test_cookie_de_sessao_sai_com_httponly_secure_e_samesite_lax(conta):
    cookie = _entrar(Client(), conta.cpf).cookies['sessionid']
    assert (cookie['httponly'], cookie['secure'], cookie['samesite']) == (True, True, 'Lax')


def test_tres_falhas_dao_a_mesma_resposta_byte_a_byte(conta):
    cliente = Client()
    inexistente = _entrar(cliente, '529.982.247-25')
    errada = _entrar(cliente, conta.cpf, 'senha errada qualquer')
    digito_invalido = _entrar(cliente, '123.456.789-00')
    assert FALHA in inexistente.content.decode()
    # Token CSRF, nonce e o CPF devolvido no campo mudam a cada resposta: compara o resto do corpo.
    corpos = {_sem_variaveis(r.content.decode()) for r in (inexistente, errada, digito_invalido)}
    assert len(corpos) == 1
    assert {r.status_code for r in (inexistente, errada, digito_invalido)} == {200}


def test_conta_bloqueada_da_a_mesma_mensagem(conta):
    for _ in range(settings.AUTENTICACAO_FALHAS_LIMITE):
        _entrar(Client(), conta.cpf, 'senha errada qualquer')
    resposta = _entrar(Client(), conta.cpf)
    assert FALHA in resposta.content.decode()


def test_proximo_interno_vale_e_externo_cai_em_barra(conta):
    assert _entrar(Client(), conta.cpf, proximo='/empresa/1/fazenda/2/')['Location'] == '/empresa/1/fazenda/2/'
    assert _entrar(Client(), conta.cpf, proximo='https://externo.exemplo/')['Location'] == '/'


def test_senha_temporaria_leva_a_troca(conta):
    temporaria = senha.emitir_senha_temporaria(conta.pessoa)
    assert _entrar(Client(), conta.cpf, temporaria)['Location'] == '/trocar-senha'
    # Qodo e Sourcery, PR #20: a página pedida atravessa a troca obrigatória.
    temporaria = senha.emitir_senha_temporaria(conta.pessoa)  # a anterior vale uma vez
    com_proximo = _entrar(Client(), conta.cpf, temporaria, proximo='/empresa/1/fazenda/2/')
    assert com_proximo['Location'] == '/trocar-senha?proximo=%2Fempresa%2F1%2Ffazenda%2F2%2F'


def test_avisos_de_sessao_expirada_e_de_senha_trocada():
    assert 'Sua sessão expirou.' in Client().get('/entrar?expirou=1').content.decode()
    assert 'Senha alterada.' in Client().get('/entrar?trocada=1').content.decode()
    assert 'Sua sessão expirou.' not in Client().get('/entrar').content.decode()


def test_sem_csrf_a_entrada_e_recusada(conta):
    resposta = Client(enforce_csrf_checks=True).post('/entrar', {'cpf': conta.cpf, 'senha': conta.senha})
    assert resposta.status_code == 403


def test_a_tela_chama_a_mesma_funcao_da_api(conta, monkeypatch):
    chamadas = []
    original = login.autenticar
    monkeypatch.setattr(login, 'autenticar', lambda *a, **k: chamadas.append(a) or original(*a, **k))
    _entrar(Client(), conta.cpf)
    assert len(chamadas) == 1


def _sem_variaveis(html):
    import re

    return re.sub(r' (?:value|nonce)="[^"]*"', '', html)


def test_entrada_nao_usa_no_referrer_que_faz_o_navegador_mandar_origin_null():
    # Regressão medida no Chromium: com `no-referrer` o POST do formulário leva `Origin: null` e o CSRF recusa (403).
    politica = Client().get('/entrar')['Referrer-Policy']
    assert politica == 'same-origin'
    assert Client(enforce_csrf_checks=True).post('/entrar', {}, HTTP_ORIGIN='null').status_code == 403  # o que `no-referrer` causava


def test_tela_tem_os_campos_do_prototipo_e_o_script_com_nonce():
    html = Client().get('/entrar').content.decode()
    assert 'inputmode="numeric"' in html
    assert 'autocomplete="username"' in html
    assert 'placeholder="000.000.000-00"' in html
    assert 'autocomplete="current-password"' in html
    assert 'href="/esqueci-senha"' in html
    assert 'Esqueci a senha' in html
    assert 'Use seu CPF e a senha da sua conta AgriOn.' in html
    assert re.search(r'<script src="[^"]*entrar\.js"[^>]*nonce=', html)


def test_campos_vazios_sem_js_ficam_com_required_e_com_js_o_servidor_recebe_o_vazio():
    # Sem JS, `required` barra o vazio; o aviso do script só vale com o JS, que tira `required` pelo `noValidate`.
    html = Client().get('/entrar').content.decode()
    assert 'name="cpf"' in html
    assert 'required' in html
    assert re.search(r'id="aviso-campos"[^>]*\shidden', html)


def test_post_com_campos_vazios_continua_recusado_pelo_servidor(conta):
    # Negativo: a mensagem do JS não muda a regra; o servidor recusa o vazio com a mesma mensagem única.
    resposta = _entrar(Client(), '', '')
    assert resposta.status_code == 200
    assert FALHA in resposta.content.decode()


def test_cpf_vazio_nao_abre_sessao(conta):
    assert 'sessionid' not in _entrar(Client(), '', SENHA).cookies
