"""Página de destino do link de redefinição (T5.5g, R5): existe, não guarda cache e o confirmar aceita o POST dela."""

import json
import re
from pathlib import Path

from django.conf import settings
from django.test import Client
from django.urls import reverse

from identidade import redefinicao
from identidade.models import PedidoRedefinicao, Pessoa


def test_o_caminho_do_link_do_email_abre_a_pagina(db, cpf_novo, mailoutbox):
    cpf = cpf_novo()
    Pessoa.objects.criar(nome='Fulana', email='fulana@exemplo.test', cpf=cpf)
    redefinicao.pedir_redefinicao(cpf)
    link = re.findall(r'https?://\S+', mailoutbox[0].body)[0]
    caminho = link.removeprefix(settings.URL_BASE).split('#')[0]
    resposta = Client().get(caminho)
    assert resposta.status_code == 200
    assert caminho == reverse('redefinir_senha')


def test_pagina_nao_fica_em_cache_e_nao_vaza_referencia():
    resposta = Client().get('/redefinir-senha')
    assert 'no-store' in resposta['Cache-Control']
    assert resposta['Referrer-Policy'] == 'same-origin'
    assert b'projeto/redefinir-senha.js' in resposta.content
    assert b'<script>' not in resposta.content  # sem script inline (R14); o código está no .js
    script = (Path(settings.STATICFILES_DIRS[0]) / 'projeto' / 'redefinir-senha.js').read_text(encoding='utf-8')
    assert 'history.replaceState' in script
    assert '/api/v1/redefinir-senha/confirmar' in script


def test_pagina_so_aceita_consulta():
    assert Client().post('/redefinir-senha').status_code == 405


def test_confirmar_aceita_o_post_da_pagina_sem_cookie_nem_csrf(db, cpf_novo, mailoutbox):
    # O script da página envia JSON sem cookie: o confirmar não pode exigir CSRF (rota `auth=None`).
    cpf = cpf_novo()
    pessoa = Pessoa.objects.criar(nome='Fulana', email='fulana@exemplo.test', cpf=cpf)
    redefinicao.pedir_redefinicao(cpf)
    segredo = re.findall(r'#segredo=(\S+)', mailoutbox[0].body)[0]
    resposta = Client(enforce_csrf_checks=True).post(
        '/api/v1/redefinir-senha/confirmar',
        data=json.dumps({'segredo': segredo, 'senha_nova': 'uma frase longa e incomum para testar'}),
        content_type='application/json',
    )
    assert resposta.status_code == 204
    assert PedidoRedefinicao.objects.filter(pessoa=pessoa, usado_em__isnull=False).exists()


def test_falha_csrf_e_erro_500_renderizam_com_a_requisicao(db):
    from django.test import RequestFactory

    from projeto import paginas

    requisicao = RequestFactory().get('/')
    assert paginas.falha_csrf(requisicao, reason='x').status_code == 403
    assert paginas.erro_500(requisicao).status_code == 500
