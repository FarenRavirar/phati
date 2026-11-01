"""Página da fazenda (R11, R22; A6, A9): nome, empresa, árvore em leitura, sem botão de criar."""

import re

from django.test import Client

from territorio.models import Fazenda, SubArea


def _sem_nonce(resposta):
    return re.sub(rb'nonce="[^"]*"', b'', resposta.content)


def _caminho(empresa, fazenda):
    return f'/empresa/{empresa.pk}/fazenda/{fazenda.pk}/'


def _conteudo(resposta):
    return resposta.content.decode().split('<main')[1]


def test_arvore_de_tres_niveis_aparece_aninhada(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    SubArea.objects.create(empresa=cenario.x, fazenda=cenario.f1, pai=cenario.t1, nivel=3, nome='Parcela P1')
    html = cliente_logado.get(_caminho(cenario.x, cenario.f1)).content.decode()
    assert '<h1>F1</h1>' in html
    assert 'Empresa X' in html
    # Procura a partir da árvore: o `nonce` aleatório do `<head>` pode conter "G1" ou "T1" e quebrar a ordem às vezes.
    arvore = html[html.index('<ul class="arvore">'):]
    ordem = [arvore.index(nome) for nome in ('G1', 'T1', 'Parcela P1', 'G2')]
    assert ordem == sorted(ordem)
    assert html.count('<ul class="arvore">') == 3  # raiz, filhos de G1 e filhos de T1; G2 e a parcela não abrem lista
    assert 'Sem camadas ainda.' in html


def test_fazenda_sem_sub_areas_mostra_o_estado_vazio_e_nao_oferece_criar(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    conteudo = _conteudo(cliente_logado.get(_caminho(cenario.x, cenario.f2)))
    assert 'Sem sub-áreas cadastradas.' in conteudo
    assert 'Sem camadas ainda.' in conteudo
    assert '<form' not in conteudo
    assert '<button' not in conteudo


def test_acesso_so_a_uma_sub_area_mostra_ela_e_as_descendentes(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['usuario'], cenario.t1)
    SubArea.objects.create(empresa=cenario.x, fazenda=cenario.f1, pai=cenario.t1, nivel=3, nome='Parcela P1')
    conteudo = _conteudo(cliente_logado.get(_caminho(cenario.x, cenario.f1)))
    assert 'T1' in conteudo
    assert 'Parcela P1' in conteudo  # descendente da sub-área concedida (Sourcery, PR #21)
    assert 'G1' not in conteudo
    assert 'G2' not in conteudo


def test_fazenda_de_outra_empresa_e_inexistente_dao_o_mesmo_404(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    de_fora = cliente_logado.get(_caminho(cenario.y, cenario.fy))
    cruzada = cliente_logado.get(f'/empresa/{cenario.x.pk}/fazenda/{cenario.fy.pk}/')
    inexistente = cliente_logado.get(f'/empresa/{cenario.x.pk}/fazenda/999999/')
    assert [r.status_code for r in (de_fora, cruzada, inexistente)] == [404, 404, 404]
    assert _sem_nonce(de_fora) == _sem_nonce(cruzada) == _sem_nonce(inexistente)
    assert b'Empresa Y' not in de_fora.content
    assert b'FY' not in de_fora.content


def test_pessoa_sem_concessao_e_pessoa_de_outra_empresa_recebem_404(cliente_logado, conta, cenario, conceder_direto):
    assert cliente_logado.get(_caminho(cenario.x, cenario.f1)).status_code == 404
    conceder_direto(conta.pessoa, cenario.cargos_y['administrador'], cenario.y)
    assert cliente_logado.get(_caminho(cenario.x, cenario.f1)).status_code == 404


def test_irma_sem_concessao_da_mesma_empresa_recebe_404(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['usuario'], cenario.f1)
    assert cliente_logado.get(_caminho(cenario.x, cenario.f1)).status_code == 200
    assert cliente_logado.get(_caminho(cenario.x, cenario.f2)).status_code == 404


def test_trilha_da_faixa_tem_um_link_para_a_empresa_e_outro_para_a_fazenda(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['usuario'], cenario.f1)
    resposta = cliente_logado.get(_caminho(cenario.x, cenario.f1))
    faixa = resposta.content.decode().split('<p class="faixa-escopo">')[1].split('</p>')[0]
    assert re.findall(r'<a href="([^"]+)">([^<]+)</a>', faixa) == [
        (f'/empresa/{cenario.x.pk}/', 'Empresa X'),
        (_caminho(cenario.x, cenario.f1), 'F1'),
    ]
    assert 'Empresa X' not in _conteudo(resposta)  # A2: o nome da empresa não se repete no <main>


def test_no_da_arvore_nao_e_link_enquanto_a_sub_area_nao_tem_pagina(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    arvore = cliente_logado.get(_caminho(cenario.x, cenario.f1)).content.decode().split('<ul class="arvore">')[1].split('</main>')[0]
    assert '<a ' not in arvore


def test_deslogado_vai_a_entrada_e_senha_temporaria_vai_a_troca(cliente_logado, conta, cenario):
    caminho = _caminho(cenario.x, cenario.f1)
    assert Client().get(caminho)['Location'].startswith('/entrar?proximo=')
    conta.pessoa.deve_trocar_senha = True
    conta.pessoa.save(update_fields=['deve_trocar_senha'])
    assert cliente_logado.get(caminho)['Location'].startswith('/trocar-senha')


def test_pagina_so_aceita_consulta(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    assert cliente_logado.post(_caminho(cenario.x, cenario.f1)).status_code == 405
    assert Fazenda.objects.filter(empresa=cenario.x).count() == 2
