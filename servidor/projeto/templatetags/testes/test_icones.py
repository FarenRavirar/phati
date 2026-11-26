"""Tag `{% icone %}` (spec 012, R4 e R12): caminho feliz, entrada inválida e leitura confinada à pasta de ícones."""

import pytest
from django.template import Context, Template, TemplateSyntaxError

from projeto.templatetags import icones

PASTA = icones.PASTA_ICONES


def _renderizar(trecho, **contexto):
    # Sem `{% load %}`: a tag vem de `builtins` em settings.py. Sem o registro, o engine recusa o bloco.
    return Template(trecho).render(Context(contexto))


@pytest.fixture(autouse=True)
def _cache_limpo():
    icones._conteudo.cache_clear()
    yield
    icones._conteudo.cache_clear()


def test_padrao_traco_175_16px_e_decorativo():
    html = _renderizar('{% icone "house" %}')
    assert html.startswith('<svg class="ag-icone" width="16" height="16"')
    assert 'stroke-width="1.75"' in html
    assert 'aria-hidden="true"' in html
    assert 'role=' not in html
    assert 'style=' not in html
    assert '<path' in html


def test_tamanho_e_traco_viram_atributos_svg():
    html = _renderizar('{% icone "chevron-right" tamanho=12 traco=2.5 %}')
    assert 'width="12" height="12"' in html
    assert 'stroke-width="2.5"' in html


@pytest.mark.parametrize('tamanho', [12, 14, 16, 18, 20, 36])
def test_todo_tamanho_permitido_renderiza(tamanho):
    html = _renderizar('{% icone "house" tamanho=tamanho %}', tamanho=tamanho)
    assert f'width="{tamanho}" height="{tamanho}"' in html


def test_rotulo_vira_imagem_com_nome_escapado_e_sem_aria_hidden():
    html = _renderizar('{% icone "log-out" rotulo=valor %}', valor='Sair "agora" <b>')
    assert 'role="img"' in html
    assert 'aria-label="Sair &quot;agora&quot; &lt;b&gt;"' in html
    assert 'aria-hidden' not in html
    assert '<b>' not in html


def test_rotulo_hostil_nao_injeta_marcacao():
    html = _renderizar('{% icone "house" rotulo=valor %}', valor='"><script>alert(1)</script>')
    assert '<script>' not in html
    assert '&lt;script&gt;' in html


def test_classe_extra_entra_depois_da_base_e_e_escapada():
    html = _renderizar('{% icone "house" classe=valor %}', valor='extra" onload="x')
    assert 'class="ag-icone extra&quot; onload=&quot;x"' in html
    # Aspa sem escape fecharia o valor e abriria um atributo `onload`.
    assert 'extra" onload' not in html


def test_todos_os_arquivos_da_pasta_renderizam_svg_valido():
    arquivos = sorted(PASTA.glob('*.svg'))
    assert arquivos, 'a pasta de ícones não tem SVG'
    for arquivo in arquivos:
        html = icones.icone(arquivo.stem)
        assert html.startswith('<svg ') and html.endswith('</svg>'), arquivo.name


@pytest.mark.parametrize('nome', ['../segredo', '..', '', 'a/b', 'House', 'casa.svg', 'x y', None, 7])
def test_nome_invalido_levanta_erro_sem_ler_o_disco(nome):
    with pytest.raises(TemplateSyntaxError):
        icones.icone(nome)


def test_nome_com_traversal_nao_le_arquivo_fora_da_pasta(tmp_path, monkeypatch):
    # Arquivo real fora da pasta de ícones: sem a validação, `../segredo` o leria e renderizaria.
    pasta = tmp_path / 'icones'
    pasta.mkdir()
    (tmp_path / 'segredo.svg').write_text('<svg viewBox="0 0 24 24"><path d="M0 0"/></svg>', encoding='utf-8')
    monkeypatch.setattr(icones, 'PASTA_ICONES', pasta)
    with pytest.raises(TemplateSyntaxError):
        _renderizar('{% icone "../segredo" %}')


def test_nome_inexistente_levanta_erro():
    with pytest.raises(TemplateSyntaxError, match='inexistente'):
        _renderizar('{% icone "nao-existe" %}')


@pytest.mark.parametrize('tamanho', [13, 0, '16', 16.0, True, None])
def test_tamanho_fora_da_lista_levanta_erro(tamanho):
    with pytest.raises(TemplateSyntaxError, match='tamanho'):
        icones.icone('house', tamanho=tamanho)


@pytest.mark.parametrize('traco', [0, -1, 5, True, '2.5', None])
def test_traco_invalido_levanta_erro(traco):
    with pytest.raises(TemplateSyntaxError, match='traço'):
        icones.icone('house', traco=traco)


def test_cache_evita_reler_o_arquivo():
    icones.icone('house')
    icones.icone('house', tamanho=12)
    assert icones._conteudo.cache_info().hits == 1
    assert icones._conteudo.cache_info().misses == 1
