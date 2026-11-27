"""Telas públicas no molde AgriOn (spec 012, T3.1 e T3.2; R18, R5): título de aba, painel de marca, rodapé e CSS antigo fora."""

import re
from pathlib import Path

from django.template.loader import get_template
from django.test import Client

RAIZ = Path(__file__).resolve().parents[1]
TEMPLATES = RAIZ / 'templates'
ESTATICOS = RAIZ / 'static' / 'projeto'

TELAS = ('entrar.html', 'esqueci_senha.html', 'redefinir_senha.html', 'trocar_senha.html', 'termos.html',
         '400.html', '403.html', '403_csrf.html', '404.html', '500.html')


def test_toda_tela_publica_usa_o_molde_publica():
    for tela in TELAS:
        assert '{% extends "publica.html" %}' in (TEMPLATES / tela).read_text(encoding='utf-8'), tela


def test_titulo_de_aba_e_favicon_da_agrion():
    for caminho, titulo in (('/entrar', 'Entrar'), ('/esqueci-senha', 'Esqueci a senha')):
        html = Client().get(caminho).content.decode()
        assert f'<title>{titulo} · AgriOn</title>' in html, caminho
        assert 'projeto/agrion/logo/agrion-simbolo.svg' in html, caminho


def test_painel_de_marca_fica_fora_da_leitura_e_tem_o_texto_do_readme():
    html = Client().get('/entrar').content.decode()
    # Achado do Sourcery (PR #98): o texto tem de estar dentro do próprio aside oculto, não em qualquer ponto da página.
    painel = re.search(r'(<aside class="ag-publica-marca"[^>]*>)(.*?)</aside>', html, re.DOTALL)
    assert painel is not None
    abertura, conteudo = painel.group(1), painel.group(2)
    assert 'aria-hidden="true"' in abertura
    assert 'Gestão e inteligência territorial para o agro.' in conteudo
    assert 'agrion-simbolo-branco.svg' in conteudo


def test_sem_foto_de_satelite_por_ora():
    # Decisão do mantenedor: o painel só tem o degradê; a imagem de fundo (Q21) espera aprovação.
    html = Client().get('/entrar').content.decode()
    assert 'ag-publica-marca-imagem' not in html


def test_rodape_sem_texto_de_termos_nao_tem_link(settings):
    settings.TERMOS_ARQUIVO = ''
    settings.AMBIENTE = 'producao'
    html = Client().get('/entrar').content.decode()
    assert '© AgriOn' in html
    assert 'href="/termos"' not in html
    assert 'href="/privacidade"' not in html


def test_marca_phati_nao_aparece_nas_telas_publicas():
    for caminho in ('/entrar', '/esqueci-senha'):
        assert 'phati' not in Client().get(caminho).content.decode().lower(), caminho


def test_500_renderiza_sem_contexto_de_requisicao():
    html = get_template('500.html').render({})
    assert '<title>Erro no servidor · AgriOn</title>' in html
    assert '<h1>Erro no servidor</h1>' in html
    assert 'Voltar ao início' in html


def test_css_antigo_publica_saiu_da_casca_e_do_proprio():
    for arquivo in ESTATICOS.glob('*.css'):
        assert not re.search(r'\.publica(?![\w-])', arquivo.read_text(encoding='utf-8')), arquivo.name


def test_o_teste_de_css_antigo_reprova_regra_publica():
    # Caso negativo: a regra antiga, se voltar, faz o teste acima reprovar.
    assert re.search(r'\.publica(?![\w-])', '.publica { display: grid; }')
    assert not re.search(r'\.publica(?![\w-])', '.ag-publica { display: grid; }')
