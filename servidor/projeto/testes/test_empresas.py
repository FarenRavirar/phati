"""Tela Fazendas (`/empresas/`, spec 012 R20, R30, Q17; telas.md §3) e a escolha de empresa para nova fazenda: caso feliz,
vazio, filtro, página inválida, outra empresa invisível, botões por permissão, escape de HTML. Seletor de empresa (`/empresa/<id>/`)
segue com o mesmo template de lista até a T4.4a."""

import re
from uuid import uuid4

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from projeto.escopo import CHAVE_EMPRESA
from territorio.models import Empresa, Fazenda, NivelDivisao


def _sem_nonce(resposta):
    return re.sub(rb'name="csrfmiddlewaretoken" value="[^"]+"|nonce="[^"]+"', b'', resposta.content)


def _conteudo(html):
    """Só o conteúdo da página: o seletor da sidebar repete nomes de empresa e fazenda, fora do `<main>`."""
    return html.split('<main')[1]


@pytest.fixture
def admin_de_x(cliente_logado, conta, cenario, conceder_direto):
    """Administrador de X com 13 fazendas (F1, F2 e mais 11, no total 15 na empresa X com as do cenário); Y e as dela ficam de fora."""
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    Fazenda.objects.bulk_create(Fazenda(empresa=cenario.x, nome=f'Fazenda Teste {n:02d}') for n in range(13))
    Fazenda.objects.bulk_create(Fazenda(empresa=cenario.y, nome=f'Fazenda Alheia {n}') for n in range(3))
    return cliente_logado


def test_feliz_lista_as_fazendas_visiveis_e_nao_as_de_outra_empresa(admin_de_x):
    html = _conteudo(admin_de_x.get('/empresas/').content.decode())
    assert html.count('class="ag-celula-principal"') == 15
    assert 'Fazenda Teste 00' in html
    assert 'Fazenda Teste 12' in html
    assert 'Fazenda Alheia' not in html
    assert 'Empresa Y' not in html
    assert '15 de 15 fazendas' in html


def test_fazendas_em_ordem_de_nome_com_a_empresa_na_linha(admin_de_x):
    html = _conteudo(admin_de_x.get('/empresas/').content.decode())
    assert html.index('Fazenda Teste 00') < html.index('Fazenda Teste 12')
    assert '<div class="ag-celula-sub">Empresa X</div>' in html


def test_sem_nenhuma_fazenda_visivel_mostra_o_vazio_da_tela(cliente_logado, cenario):
    html = _conteudo(cliente_logado.get('/empresas/').content.decode())
    assert 'Nenhuma fazenda disponível.' in html
    assert 'Nenhuma fazenda encontrada' not in html
    assert 'Empresa X' not in html


def test_busca_sem_acento_nem_caixa_por_nome_e_municipio(admin_de_x, cenario):
    Fazenda.objects.filter(empresa=cenario.x, nome='F1').update(municipio='Ribeirão Preto')
    html = _conteudo(admin_de_x.get('/empresas/', {'busca': 'RIBEIRAO'}).content.decode())
    assert 'href="/empresa/%d/fazenda/%d/"' % (cenario.x.pk, cenario.f1.pk) in html
    assert '1 de 15 fazendas' in html
    assert 'Fazenda Teste 00' not in html


def test_busca_sem_resultado_mostra_vazio_com_limpar_filtros(admin_de_x):
    html = _conteudo(admin_de_x.get('/empresas/', {'busca': 'zzz'}).content.decode())
    assert 'Nenhuma fazenda encontrada' in html
    assert 'Confira a grafia ou limpe o filtro.' in html
    assert 'Limpar filtros' in html
    assert 'href="/empresas/"' in html
    assert '0 de 15 fazendas' in html


def test_situacao_arquivadas_filtra_e_marca_a_opcao_ativa(admin_de_x, conta, cenario):
    Fazenda.objects.create(empresa=cenario.x, nome='Velha', arquivada_em=timezone.now(), arquivada_por=conta.pessoa, arquivamento=uuid4())
    html = _conteudo(admin_de_x.get('/empresas/', {'situacao': 'arquivadas'}).content.decode())
    assert 'Velha' in html
    assert 'Fazenda Teste 00' not in html
    assert '>Arquivada<' in html
    assert 'data-valor="arquivadas" aria-current="true"' in html
    assert 'data-valor="todas" aria-current="true"' not in html


def test_situacao_desconhecida_cai_em_todas(admin_de_x):
    html = _conteudo(admin_de_x.get('/empresas/', {'situacao': 'qualquer'}).content.decode())
    assert '15 de 15 fazendas' in html
    assert 'data-valor="todas" aria-current="true"' in html


def test_pagina_invalida_cai_na_primeira_e_pagina_alem_do_fim_na_ultima(admin_de_x, cenario):
    # 30 fazendas no total: 25 na primeira página, 5 na última.
    Fazenda.objects.bulk_create(Fazenda(empresa=cenario.x, nome=f'Extra {n:02d}') for n in range(15))
    primeira = admin_de_x.get('/empresas/', {'pagina': 'abc'})
    assert primeira.status_code == 200
    assert _conteudo(primeira.content.decode()).count('class="ag-celula-principal"') == 25
    ultima = admin_de_x.get('/empresas/', {'pagina': '999'})
    assert ultima.status_code == 200
    html = _conteudo(ultima.content.decode())
    assert html.count('class="ag-celula-principal"') == 5
    assert re.search(r'<button[^>]*disabled[^>]*>\s*Próxima', html)
    assert 'href="?pagina=1"' in html


def test_paginacao_preserva_o_filtro_e_desabilita_as_pontas(admin_de_x, cenario):
    # 30 fazendas com "Extra" no nome: a busca tem 2 páginas (25 e 5).
    Fazenda.objects.bulk_create(Fazenda(empresa=cenario.x, nome=f'Extra {n:02d}') for n in range(30))
    primeira = _conteudo(admin_de_x.get('/empresas/', {'busca': 'Extra'}).content.decode())
    assert '30 de 45 fazendas' in primeira
    assert re.search(r'<button[^>]*disabled[^>]*>\s*Anterior', primeira)
    assert 'href="?busca=Extra&amp;pagina=2"' in primeira
    segunda = _conteudo(admin_de_x.get('/empresas/', {'busca': 'Extra', 'pagina': 2}).content.decode())
    assert segunda.count('class="ag-celula-principal"') == 5
    assert 'href="?busca=Extra&amp;pagina=1"' in segunda
    assert re.search(r'<button[^>]*disabled[^>]*>\s*Próxima', segunda)


def test_nome_hostil_sai_escapado(admin_de_x, cenario):
    Fazenda.objects.create(empresa=cenario.x, nome='<script>alert(1)</script>')
    html = admin_de_x.get('/empresas/').content.decode()
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html
    assert '<script>alert(1)</script>' not in html


def test_busca_hostil_sai_escapada_no_campo(admin_de_x):
    html = admin_de_x.get('/empresas/', {'busca': '"><script>x</script>'}).content.decode()
    assert '"><script>x</script>' not in html


def test_pagina_sem_style_inline(admin_de_x):
    assert 'style=' not in admin_de_x.get('/empresas/').content.decode()


def test_administrador_com_uma_empresa_nova_fazenda_vai_direto_ao_formulario(admin_de_x, cenario):
    html = admin_de_x.get('/empresas/').content.decode()
    assert f'href="/empresa/{cenario.x.pk}/fazenda/nova"' in html
    assert '/fazendas/nova/' not in html


def test_exportar_aparece_so_para_quem_exporta_e_leva_o_filtro(admin_de_x):
    html = admin_de_x.get('/empresas/', {'busca': 'Teste'}).content.decode()
    assert 'href="/fazendas.csv?busca=Teste"' in html


def test_usuario_sem_exportar_nem_nova_fazenda_nao_ve_os_botoes(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['usuario'], cenario.x)
    html = cliente_logado.get('/empresas/').content.decode()
    assert 'href="/fazendas.csv' not in html
    assert '/fazenda/nova' not in html
    assert '>F1<' in _conteudo(html)  # a lista continua: `ver` é do cargo


def test_tecnico_sem_exportar_nem_nova_fazenda(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['tecnico'], cenario.x)
    html = cliente_logado.get('/empresas/').content.decode()
    assert 'href="/fazendas.csv' not in html
    assert '/fazenda/nova' not in html


def test_curador_de_base_exporta(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['curador'], cenario.x)
    html = cliente_logado.get('/empresas/').content.decode()
    assert 'href="/fazendas.csv' in html


def test_duas_empresas_com_nova_fazenda_leva_a_escolha(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['administrador'], cenario.x)
    conceder_direto(conta.pessoa, cenario.cargos_y['administrador'], cenario.y)
    html = cliente_logado.get('/empresas/').content.decode()
    assert 'href="/fazendas/nova/"' in html
    escolha = cliente_logado.get('/fazendas/nova/').content.decode()
    assert 'Empresa X' in escolha
    assert 'Empresa Y' in escolha
    assert f'href="/empresa/{cenario.x.pk}/fazenda/nova"' in escolha


def test_escolha_negada_sem_criar_fazenda_em_nenhuma_empresa(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['usuario'], cenario.x)
    assert cliente_logado.get('/fazendas/nova/').status_code == 403


def test_escolha_negada_a_quem_nao_tem_empresa(cliente_logado, cenario):
    assert cliente_logado.get('/fazendas/nova/').status_code == 403


def test_plataforma_ve_cadastrar_empresa_e_todas_as_empresas(cliente_logado, conta, cenario):
    conta.pessoa.administrador_plataforma = True
    conta.pessoa.save(update_fields=['administrador_plataforma'])
    html = cliente_logado.get('/empresas/').content.decode()
    assert Empresa.objects.count() == 2
    # Q24: "Cadastrar empresa" saiu da lista e foi para o seletor da casca (o `<main>` não a tem).
    assert 'Cadastrar empresa' not in _conteudo(html)
    assert 'Cadastrar empresa' in html.split('<main')[0]
    assert 'href="/empresas/nova"' in html


def test_pessoa_sem_concessao_nao_recebe_cadastrar_empresa(cliente_logado, cenario):
    html = cliente_logado.get('/empresas/').content.decode()
    assert '/empresas/nova' not in html
    assert 'Cadastrar empresa' not in html


def test_lista_de_empresas_nao_tem_arquivadas_nem_botoes_de_acao(admin_de_x):
    # Arquivadas saiu da lista (Q24): o link fica no seletor, e a lista não repete botão de ação.
    html = _conteudo(admin_de_x.get('/empresas/').content.decode())
    assert 'href="/arquivadas/"' not in html
    assert 'class="acoes-pagina"' not in html
    assert 'ag-mais-acoes' not in html


def test_acoes_da_lista_ficam_no_cabecalho_a_direita_e_nao_abaixo_do_titulo(admin_de_x):
    # Defeito medido no navegador: Exportar e Nova fazenda saíam numa linha abaixo do título. Agora são o bloco de ações do cabeçalho.
    html = admin_de_x.get('/empresas/').content.decode()
    assert html.index('<h1>Fazendas</h1>') < html.index('class="ag-cabecalho-acoes"') < html.index('class="ag-barra-fazendas"')
    bloco = html.split('class="ag-cabecalho-acoes"')[1].split('class="ag-barra-fazendas"')[0]
    assert 'Exportar' in bloco
    assert 'Nova fazenda' in bloco


def test_menu_mais_acoes_da_empresa_fica_no_bloco_de_acoes_do_cabecalho(admin_de_x, cenario):
    html = admin_de_x.get(f'/empresa/{cenario.x.pk}/').content.decode()
    bloco = html.split('class="ag-cabecalho-acoes"')[1].split('class="ag-barra-fazendas"')[0]
    assert 'class="ag-mais-acoes"' in bloco


def test_lista_sem_permissao_de_acao_deixa_o_bloco_de_acoes_vazio(cliente_logado, conta, cenario, conceder_direto):
    # Negativo: técnico não exporta nem cadastra; o bloco do cabeçalho sai sem botão nenhum.
    conceder_direto(conta.pessoa, cenario.cargos_x['tecnico'], cenario.x)
    bloco = cliente_logado.get('/empresas/').content.decode().split('class="ag-cabecalho-acoes"')[1].split('class="ag-barra-fazendas"')[0]
    assert '<a ' not in bloco
    assert 'ag-mais-acoes' not in bloco


def test_municipio_vazio_mostra_sem_dados_e_nao_sem_informacao(admin_de_x):
    html = _conteudo(admin_de_x.get('/empresas/').content.decode())
    assert html.count('<td>Sem dados</td>') == 15
    assert 'Sem informação' not in html


def test_municipio_preenchido_aparece_na_lista_e_so_o_vazio_vira_sem_dados(admin_de_x, cenario):
    Fazenda.objects.filter(pk=cenario.f1.pk).update(municipio='Sorriso')
    html = _conteudo(admin_de_x.get('/empresas/').content.decode())
    assert '<td>Sorriso</td>' in html
    assert html.count('<td>Sem dados</td>') == 14


def test_deslogado_vai_a_entrada_e_senha_temporaria_vai_a_troca(cliente_logado, conta, cenario):
    for caminho in ('/empresas/', f'/empresa/{cenario.x.pk}/'):
        assert Client().get(caminho)['Location'].startswith('/entrar?proximo=')
    conta.pessoa.deve_trocar_senha = True
    conta.pessoa.save(update_fields=['deve_trocar_senha'])
    assert cliente_logado.get('/empresas/')['Location'].startswith('/trocar-senha')


# --- seletor de empresa (`/empresa/<id>/`, até a T4.4a) ---


def test_pagina_da_empresa_lista_so_as_fazendas_dela(admin_de_x, cenario):
    html = admin_de_x.get(f'/empresa/{cenario.x.pk}/').content.decode()
    assert html.count('class="ag-celula-principal"') == 15
    assert 'Empresa X' in html
    assert 'Empresa Y' not in html


def test_acesso_so_a_uma_fazenda_mostra_so_ela(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['usuario'], cenario.f1)
    html = cliente_logado.get(f'/empresa/{cenario.x.pk}/').content.decode()
    assert html.count('class="ag-celula-principal"') == 1
    assert '>F1<' in html
    assert '>F2<' not in html


def test_empresa_de_outro_escopo_e_empresa_inexistente_dao_o_mesmo_404(admin_de_x, cenario):
    de_fora = admin_de_x.get(f'/empresa/{cenario.y.pk}/')
    inexistente = admin_de_x.get('/empresa/999999/')
    assert (de_fora.status_code, inexistente.status_code) == (404, 404)
    assert _sem_nonce(de_fora) == _sem_nonce(inexistente)
    assert b'Empresa Y' not in de_fora.content


def test_pessoa_sem_concessao_recebe_404_na_empresa_por_url_direta(cliente_logado, cenario):
    assert cliente_logado.get(f'/empresa/{cenario.x.pk}/').status_code == 404


def _mais_acoes(html):
    """Só o menu "Mais ações" (o `details`), para o texto da lista não contar como item do menu."""
    return html.split('class="ag-mais-acoes"')[1].split('</details>')[0] if 'class="ag-mais-acoes"' in html else ''


def test_pagina_da_empresa_mostra_trilha_titulo_e_rotulo_de_talhoes(admin_de_x, cenario, conta):
    html = admin_de_x.get(f'/empresa/{cenario.x.pk}/').content.decode()
    assert '<h1>Empresa X</h1>' in html
    assert '<li aria-current="page">Empresa X</li>' in html
    assert '>Nível 2</th>' in html  # sem nome configurado, o nível 2 vira "Nível 2" (niveis.nome_do_nivel)
    NivelDivisao.objects.create(empresa=cenario.x, nivel=2, nome='Talhão')
    assert '>Talhão</th>' in admin_de_x.get(f'/empresa/{cenario.x.pk}/').content.decode()
    assert 'aria-current="true">Fazendas<' not in html  # o item do menu usa href, não texto
    assert 'href="/empresas/" aria-current="true"' in html
    assert html.count('aria-current="page"') == 1


def test_administrador_ve_mais_acoes_da_empresa_com_os_seis_itens(admin_de_x, cenario):
    html = admin_de_x.get(f'/empresa/{cenario.x.pk}/').content.decode()
    menu = _mais_acoes(html)
    assert 'aria-label="Mais ações"' in menu
    for rotulo, destino in (
        ('Cadastrar fazenda', f'/empresa/{cenario.x.pk}/fazenda/nova'),
        ('Pessoas', f'/empresa/{cenario.x.pk}/pessoas/'),
        ('Cargos', f'/empresa/{cenario.x.pk}/cargos/'),
        ('Renomear empresa', reverse('empresa_editar', kwargs={'empresa_id': cenario.x.pk})),
        ('Nomes dos níveis da divisão', reverse('empresa_niveis', kwargs={'empresa_id': cenario.x.pk})),
        ('Arquivar empresa', reverse('empresa_arquivar', kwargs={'empresa_id': cenario.x.pk})),
    ):
        assert f'<a href="{destino}">{rotulo}</a>' in menu


def test_tecnico_na_empresa_nao_ve_renomear_nem_arquivar(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['tecnico'], cenario.x)
    menu = _mais_acoes(cliente_logado.get(f'/empresa/{cenario.x.pk}/').content.decode())
    assert 'Renomear empresa' not in menu
    assert 'Arquivar empresa' not in menu
    assert 'Cadastrar fazenda' not in menu


def test_usuario_na_empresa_nao_ganha_botao_mais_acoes(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_x['usuario'], cenario.x)
    html = cliente_logado.get(f'/empresa/{cenario.x.pk}/').content.decode()
    assert 'class="ag-mais-acoes"' not in html
    assert 'aria-label="Mais ações"' not in html
    assert '>F1<' in html  # a lista continua: `ver` é do cargo


def test_empresa_arquivada_mostra_aviso_e_so_desarquivar(admin_de_x, cenario, conta):
    Empresa.objects.filter(pk=cenario.x.pk).update(arquivada_em=timezone.now(), arquivada_por=conta.pessoa, arquivamento=uuid4())
    html = admin_de_x.get(f'/empresa/{cenario.x.pk}/').content.decode()
    assert 'Esta empresa está arquivada: só leitura.' in html
    menu = _mais_acoes(html)
    assert menu.count('<a href=') == 1
    assert f'<a href="{reverse("empresa_desarquivar", kwargs={"empresa_id": cenario.x.pk})}">Desarquivar</a>' in menu
    assert 'Nova fazenda' not in html
    assert html.count('class="ag-celula-principal"') == 15


def test_empresa_arquivada_sem_permissao_de_desarquivar_nao_mostra_menu(cliente_logado, conta, cenario, conceder_direto):
    Empresa.objects.filter(pk=cenario.x.pk).update(arquivada_em=timezone.now(), arquivada_por=conta.pessoa, arquivamento=uuid4())
    conceder_direto(conta.pessoa, cenario.cargos_x['curador'], cenario.x)
    html = cliente_logado.get(f'/empresa/{cenario.x.pk}/').content.decode()
    assert 'Esta empresa está arquivada' in html
    assert 'class="ag-mais-acoes"' not in html
    assert 'Desarquivar' not in html


def test_empresa_arquivada_mantem_as_fazendas_e_o_filtro_de_arquivadas(admin_de_x, cenario, conta):
    Fazenda.objects.create(empresa=cenario.x, nome='Velha', arquivada_em=timezone.now(), arquivada_por=conta.pessoa, arquivamento=uuid4())
    html = _conteudo(admin_de_x.get(f'/empresa/{cenario.x.pk}/', {'situacao': 'arquivadas'}).content.decode())
    assert '>Velha<' in html
    assert 'Fazenda Teste 00' not in html


def test_nome_hostil_da_empresa_sai_escapado_na_pagina_dela(admin_de_x, cenario):
    Empresa.objects.filter(pk=cenario.x.pk).update(nome='<b>Hostil</b>')
    html = admin_de_x.get(f'/empresa/{cenario.x.pk}/').content.decode()
    assert '<b>Hostil</b>' not in html
    assert '&lt;b&gt;Hostil&lt;/b&gt;' in html


def test_exportar_na_empresa_leva_o_escopo_da_empresa(admin_de_x, cenario):
    html = admin_de_x.get(f'/empresa/{cenario.x.pk}/', {'busca': 'Teste'}).content.decode()
    assert f'href="/fazendas.csv?empresa={cenario.x.pk}&amp;busca=Teste"' in html


def test_busca_da_empresa_tem_nome_acessivel_e_placeholder_sem_rotulo_visivel(admin_de_x, cenario):
    html = admin_de_x.get(f'/empresa/{cenario.x.pk}/').content.decode()
    assert 'aria-label="Buscar fazenda"' in html
    assert 'placeholder="Buscar por nome ou município"' in html
    assert '<label' not in _conteudo(html).split('ag-barra-fazendas')[1].split('</form>')[0]


def test_seletor_da_casca_tem_abrir_empresa_para_quem_ve_as_fazendas(admin_de_x):
    cabecalho = admin_de_x.get('/empresas/').content.decode().split('<main')[0]
    assert 'Abrir empresa' in cabecalho
    assert 'href="/empresas/nova"' not in cabecalho  # administrador de empresa não cadastra empresa


def _escolher_empresa(cliente, empresa):
    """Grava a empresa escolhida na sessão do cliente logado (o mesmo que a rota `escolher_empresa` grava)."""
    sessao = cliente.session
    sessao[CHAVE_EMPRESA] = empresa.pk
    sessao.save()


def _abrir_empresa_do_seletor(cliente):
    """Trecho do seletor da casca que leva a "Abrir empresa": o `<a>` que contém o rótulo; vazio se o item não existe."""
    cabecalho = cliente.get('/empresas/').content.decode().split('<main')[0]
    if 'Abrir empresa' not in cabecalho:
        return ''
    return cabecalho.split('Abrir empresa')[0].rsplit('<a', 1)[-1]


def test_abrir_empresa_leva_a_empresa_lembrada(admin_de_x, cenario):
    # Q24: a única empresa que a administradora alcança é a lembrada; o item vai à página dela.
    assert f'href="/empresa/{cenario.x.pk}/"' in _abrir_empresa_do_seletor(admin_de_x)


def test_abrir_empresa_leva_a_empresa_escolhida_no_seletor(cliente_logado, conta, cenario):
    conta.pessoa.administrador_plataforma = True
    conta.pessoa.save(update_fields=['administrador_plataforma'])
    _escolher_empresa(cliente_logado, cenario.y)
    trecho = _abrir_empresa_do_seletor(cliente_logado)
    assert f'href="/empresa/{cenario.y.pk}/"' in trecho
    assert f'/empresa/{cenario.x.pk}/' not in trecho


def test_abrir_empresa_some_sem_empresa_escolhida(cliente_logado, conta, cenario):
    # Negativo: a plataforma alcança duas empresas e não escolheu nenhuma; o item não aparece, e /empresas/ segue no menu.
    conta.pessoa.administrador_plataforma = True
    conta.pessoa.save(update_fields=['administrador_plataforma'])
    assert _abrir_empresa_do_seletor(cliente_logado) == ''
    assert cliente_logado.get('/empresas/').status_code == 200


def test_abrir_empresa_descarta_escolha_sem_acesso(admin_de_x, cenario):
    # Negativo: a empresa escolhida na sessão não é alcançada por esta pessoa; sai da sessão e o item vai à que ela alcança.
    _escolher_empresa(admin_de_x, cenario.y)
    trecho = _abrir_empresa_do_seletor(admin_de_x)
    assert f'href="/empresa/{cenario.x.pk}/"' in trecho
    assert f'/empresa/{cenario.y.pk}/' not in trecho


def test_seletor_leva_arquivadas_so_a_quem_alcanca_arquivada(admin_de_x, cenario, conta):
    assert 'href="/arquivadas/"' not in admin_de_x.get('/empresas/').content.decode()
    Fazenda.objects.create(empresa=cenario.x, nome='Velha', arquivada_em=timezone.now(), arquivada_por=conta.pessoa, arquivamento=uuid4())
    assert 'href="/arquivadas/"' in admin_de_x.get('/empresas/').content.decode()


def test_seletor_leva_cadastrar_empresa_so_a_plataforma(cliente_logado, conta, cenario):
    assert 'Cadastrar empresa' not in cliente_logado.get('/empresas/').content.decode()
    conta.pessoa.administrador_plataforma = True
    conta.pessoa.save(update_fields=['administrador_plataforma'])
    cabecalho = cliente_logado.get('/empresas/').content.decode().split('<main')[0]
    assert 'Cadastrar empresa' in cabecalho
    assert 'href="/empresas/nova"' in cabecalho


def test_empresa_sem_acesso_nao_mostra_mais_acoes_nem_aviso(cliente_logado, cenario):
    resposta = cliente_logado.get(f'/empresa/{cenario.y.pk}/')
    assert resposta.status_code == 404
    assert b'Mais a' not in resposta.content
    assert b'arquivada' not in resposta.content


# --- botão Exportar na página da empresa (R30): só onde a pessoa exporta ---


def test_exportar_na_empresa_so_onde_a_pessoa_exporta(cliente_logado, conta, cenario, conceder_direto):
    # Curador em X exporta; Usuário em Y não. Os dois 200 vêm antes da asserção de ausência: um 404 também não tem o link.
    conceder_direto(conta.pessoa, cenario.cargos_x['curador'], cenario.x)
    conceder_direto(conta.pessoa, cenario.cargos_y['usuario'], cenario.y)
    em_x = cliente_logado.get(f'/empresa/{cenario.x.pk}/')
    em_y = cliente_logado.get(f'/empresa/{cenario.y.pk}/')
    assert (em_x.status_code, em_y.status_code) == (200, 200)
    assert f'/fazendas.csv?empresa={cenario.x.pk}' in _conteudo(em_x.content.decode())
    assert '/fazendas.csv' not in _conteudo(em_y.content.decode())
    # A rota segue a mesma regra por URL direta: negado, não CSV só com cabeçalho.
    assert cliente_logado.get('/fazendas.csv', {'empresa': cenario.y.pk}).status_code == 403


def test_usuario_sem_exportar_na_empresa_nao_ve_link_nem_rota(cliente_logado, conta, cenario, conceder_direto):
    conceder_direto(conta.pessoa, cenario.cargos_y['usuario'], cenario.y)
    em_y = cliente_logado.get(f'/empresa/{cenario.y.pk}/')
    assert em_y.status_code == 200
    assert '/fazendas.csv' not in _conteudo(em_y.content.decode())
    assert cliente_logado.get('/fazendas.csv', {'empresa': cenario.y.pk}).status_code == 403
