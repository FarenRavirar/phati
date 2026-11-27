"""Componentes base e travas de estilo (R13, R15; A12, A19): cada componente renderiza e o CSS segue os tokens."""

import re
from pathlib import Path

import pytest
from django.template import Context, Template, TemplateSyntaxError
from django.template.loader import render_to_string

from projeto.templatetags.componentes import dentre, repetir, selo_rotulo, selo_tom

RAIZ = Path(__file__).resolve().parent.parent
TEMPLATES = RAIZ / 'templates'
ESTATICOS = RAIZ / 'static' / 'projeto'
AGRION = ESTATICOS / 'agrion'


def _renderizar(modelo, **contexto):
    return render_to_string(modelo, contexto)


def _css_do_projeto():
    # Recursivo (T1.3). `terceiros/` é biblioteca de terceiros, fora desta regra, como antes.
    return sorted(p for p in ESTATICOS.rglob('*.css') if 'terceiros' not in p.relative_to(ESTATICOS).parts)


def _integros_do_pacote():
    # Exceção de cor literal e de !important só para cópia do pacote cujo hash confere (test_agrion_copia.py).
    from projeto.testes.test_agrion_copia import integros_do_pacote

    return integros_do_pacote()


def test_botao():
    html = _renderizar('componentes/botao.html', texto='Salvar', tipo='submit')
    assert '<button class="ag-botao" data-variante="primario" data-tamanho="md" type="submit">Salvar</button>' in html
    assert 'data-variante="secundario"' in _renderizar('componentes/botao.html', texto='x', secundario=True)
    assert ' disabled' in _renderizar('componentes/botao.html', texto='x', desabilitado=True)


def _botoes_sem_estilo(html):
    # Botão ou submit sem `ag-botao` sai com o estilo nativo do navegador (rodada 7: Fixar/Ocultar no Início).
    marcas = re.findall(r'<button\b[^>]*>|<input\b[^>]*type="(?:submit|button)"[^>]*>', html)
    return [m for m in marcas if 'ag-botao' not in m]


def test_botao_sem_ag_botao_e_reprovado_e_botao_do_componente_passa():
    assert _botoes_sem_estilo('<button name="estado" value="fixar">Fixar</button>') == ['<button name="estado" value="fixar">']
    assert _botoes_sem_estilo('<input type="submit" value="Enviar">') == ['<input type="submit" value="Enviar">']
    assert _botoes_sem_estilo('<button class="ag-botao" data-variante="primario">Ok</button>') == []
    assert _botoes_sem_estilo(_renderizar('componentes/botao.html', texto='Salvar', tipo='submit')) == []


def test_todo_botao_de_template_tem_classe_de_estilo():
    # Exceção só para botão de componente que o CSS do próprio componente estiliza (seletor conferido no CSS, não de memória).
    estilo_do_componente = {'componentes/segmentado.html': '.ag-segmentado button'}
    css = ''.join(p.read_text(encoding='utf-8') for p in _css_do_projeto())
    reprovados = []
    for modelo in sorted(TEMPLATES.rglob('*.html')):
        rel = modelo.relative_to(TEMPLATES).as_posix()
        for marca in _botoes_sem_estilo(modelo.read_text(encoding='utf-8')):
            if rel in estilo_do_componente and estilo_do_componente[rel] in css:
                continue
            reprovados.append(f'{rel}: {marca}')
    assert reprovados == []


def test_campo_liga_rotulo_e_erro_ao_controle():
    html = _renderizar('componentes/campo.html', id='cpf', nome='cpf', rotulo='CPF', erro='CPF ou senha incorretos.')
    assert '<label class="ag-rotulo" for="cpf">CPF</label>' in html
    assert 'aria-invalid="true"' in html
    assert 'aria-describedby="cpf-descricao"' in html
    assert 'id="cpf-descricao"' in html
    assert 'CPF ou senha incorretos.' in html
    sem_erro = _renderizar('componentes/campo.html', id='cpf', nome='cpf', rotulo='CPF')
    assert 'aria-invalid' not in sem_erro
    assert 'aria-describedby' not in sem_erro


def test_campo_select_marca_a_opcao_escolhida_e_escapa_o_rotulo():
    opcoes = [{'valor': 1, 'rotulo': 'Usuário'}, {'valor': 2, 'rotulo': '<b>Técnico</b>'}]
    html = _renderizar('componentes/campo.html', id='cargo', nome='cargo', rotulo='Cargo', tipo='select', opcoes=opcoes, valor='2', erro='Escolha um cargo.')
    assert '<select class="ag-controle" id="cargo" name="cargo"' in html
    assert '<option value="2" selected>&lt;b&gt;Técnico&lt;/b&gt;</option>' in html
    assert '<option value="1">Usuário</option>' in html
    assert 'aria-invalid="true"' in html
    assert 'aria-describedby="cargo-descricao"' in html
    assert '<input' not in html


def test_campo_caixas_agrupa_em_fieldset_com_legenda_e_marca_as_escolhidas():
    opcoes = [{'valor': 7, 'rotulo': 'Solo', 'marcada': True}, {'valor': 8, 'rotulo': 'Água', 'marcada': False}]
    html = _renderizar('componentes/campo.html', id='categorias', nome='categorias', rotulo='Categorias', tipo='caixas', opcoes=opcoes, ajuda='Só Técnico e Usuário.')
    assert '<fieldset' in html
    assert '<legend class="ag-rotulo">Categorias</legend>' in html
    assert '<input type="checkbox" name="categorias" value="7" checked>' in html
    assert '<input type="checkbox" name="categorias" value="8">' in html
    assert 'aria-describedby="categorias-descricao"' in html
    assert 'Só Técnico e Usuário.' in html


@pytest.mark.parametrize('tipo', ['erro', 'aviso', 'info', 'sucesso'])
def test_aviso_tem_cor_icone_e_texto(tipo):
    html = _renderizar('componentes/aviso.html', tipo=tipo, texto='Texto do aviso')
    assert f'data-tipo="{tipo}"' in html
    assert '<svg' in html
    assert 'aria-hidden="true"' in html
    assert 'Texto do aviso' in html


def test_aviso_de_erro_e_anunciado_na_hora():
    assert 'role="alert"' in _renderizar('componentes/aviso.html', tipo='erro', texto='x')
    assert 'role="alert"' not in _renderizar('componentes/aviso.html', tipo='info', texto='x')


def test_campo_preserva_zero_e_nao_inventa_valor_ausente():
    # Dado ausente é diferente de zero (AGENTS.md §Código; Codex, Sourcery e Greptile, PR #19).
    assert 'value="0"' in _renderizar('componentes/campo.html', id='n', nome='n', rotulo='N', valor=0)
    assert 'value=' not in _renderizar('componentes/campo.html', id='n', nome='n', rotulo='N')
    assert 'value=' not in _renderizar('componentes/campo.html', id='n', nome='n', rotulo='N', valor=None)


def test_vazio_e_cabecalho_e_tabela():
    assert 'Sem camadas ainda.' in _renderizar('componentes/vazio.html', texto='Sem camadas ainda.')
    assert '<h1>Fazendas</h1>' in _renderizar('componentes/cabecalho_pagina.html', titulo='Fazendas')
    html = _renderizar('componentes/tabela.html', legenda='Fazendas', colunas=['Nome'], linhas=[['F1'], ['F2']])
    assert 'class="ag-tabela-wrap"' in html
    assert '<th scope="col">Nome</th>' in html
    assert '<td>F2</td>' in html


def test_vazio_so_mostra_a_acao_quando_a_view_a_passa():
    assert '<a ' not in _renderizar('componentes/vazio.html', texto='Sem sub-áreas.')
    com = _renderizar('componentes/vazio.html', texto='Sem sub-áreas.', acao_rotulo='Cadastrar', acao_destino='/x/')
    assert '<a class="ag-botao" data-variante="primario" data-tamanho="md" href="/x/">Cadastrar</a>' in com
    assert '<a ' not in _renderizar('componentes/vazio.html', texto='x', acao_rotulo='Cadastrar')  # rótulo sem destino não vira link


def test_lista_de_convites_tem_aceitar_e_recusar_com_csrf_e_data_brasileira():
    from datetime import datetime, timezone

    convites = [{'id': 7, 'empresa_nome': 'Empresa X', 'cargo_nome': 'Técnico', 'expira_em': datetime(2026, 11, 5, 15, tzinfo=timezone.utc)}]
    html = render_to_string('componentes/lista_convites.html', {'convites': convites}, request=_requisicao())
    assert 'action="/convites/7/aceitar"' in html
    assert 'action="/convites/7/recusar"' in html
    assert html.count('csrfmiddlewaretoken') == 2
    assert '05/11/2026' in html  # A21: dd/mm/aaaa no fuso local


def _requisicao():
    from django.test import RequestFactory

    return RequestFactory().get('/')


def test_cor_so_existe_no_arquivo_de_variaveis():
    cor = r'#[0-9A-Fa-f]{6}\b|\brgba?\(|\bhsla?\('
    integros = _integros_do_pacote()
    achados = [
        arquivo.name
        for arquivo in [*_css_do_projeto(), *TEMPLATES.rglob('*.html')]
        if arquivo.name != 'camadas.css' and arquivo not in integros
        and re.search(cor, arquivo.read_text(encoding='utf-8'))
    ]
    assert achados == []
    # camadas.css pode ter cor só dentro do bloco `:root`: fora dele, uma regra com cor literal reabriria o problema.
    fora_do_root = re.sub(r':root\s*\{[^}]*\}', '', (ESTATICOS / 'camadas.css').read_text(encoding='utf-8'))
    assert not re.search(cor, re.sub(r'/\*.*?\*/', '', fora_do_root, flags=re.S))


def test_template_nao_tem_script_inline_nem_estilo_inline():
    for arquivo in TEMPLATES.rglob('*.html'):
        texto = arquivo.read_text(encoding='utf-8')
        assert not re.search(r'<script\b(?![^>]*\bsrc=)', texto, re.IGNORECASE), arquivo.name
        assert not re.search(r'<style\b|\sstyle=', texto), arquivo.name


def _etiquetas_sem_nonce(texto):
    # IGNORECASE: `<LINK>` ou `<SCRIPT>` em maiúsculas também é etiqueta e precisa de nonce (alerta py/bad-tag-filter).
    return [e for e in re.findall(r'<(?:script|link)\b[^>]*>', texto, re.IGNORECASE) if '{% csp_nonce_attr %}' not in e]


def test_todo_script_e_link_de_estilo_dos_moldes_leva_nonce():
    for molde in ('casca.html', 'publica.html'):
        texto = (TEMPLATES / molde).read_text(encoding='utf-8')
        assert _etiquetas_sem_nonce(texto) == [], molde


def test_etiqueta_sem_nonce_reprova_inclusive_em_maiuscula():
    assert _etiquetas_sem_nonce('<LINK rel="stylesheet" href="a.css">') == ['<LINK rel="stylesheet" href="a.css">']
    assert _etiquetas_sem_nonce('<SCRIPT src="a.js"></SCRIPT>') == ['<SCRIPT src="a.js">']
    assert _etiquetas_sem_nonce('<script {% csp_nonce_attr %} src="a.js"></script>') == []


def test_outline_none_so_com_substituto():
    for arquivo in _css_do_projeto():
        texto = arquivo.read_text(encoding='utf-8')
        if re.search(r'outline:\s*(none|0)\b', texto):
            assert ':focus-visible' in texto, arquivo.name
    assert ':focus-visible' in (ESTATICOS / 'base.css').read_text(encoding='utf-8')


def test_movimento_so_dentro_da_preferencia_por_movimento():
    # WCAG 2.3.3: `transition` e `animation` só existem dentro de `@media (prefers-reduced-motion: no-preference)`.
    # Comentário não conta (o texto da regra aparece nele); o bloco permitido é removido e nada pode sobrar.
    bloco = r'@media[^{]*prefers-reduced-motion:\s*no-preference[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}'
    integros = _integros_do_pacote()
    for arquivo in _css_do_projeto():
        # Cópia íntegra do pacote fica de fora: o movimento dela é zerado por `prefers-reduced-motion: reduce` (test_agrion_proprio.py).
        if arquivo in integros:
            continue
        texto = re.sub(r'/\*.*?\*/', '', arquivo.read_text(encoding='utf-8'), flags=re.S)
        fora_do_bloco = re.sub(bloco, '', texto)
        assert not re.search(r'\b(transition|animation)\s*:', fora_do_bloco), arquivo.name


def test_o_teste_de_movimento_detecta_movimento_sem_a_protecao():
    bloco = r'@media[^{]*prefers-reduced-motion:\s*no-preference[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}'
    sem = '.x { transition: all 1s; }'
    com = '@media (prefers-reduced-motion: no-preference) { .x { transition: all 1s; } }'
    assert re.search(r'\b(transition|animation)\s*:', re.sub(bloco, '', sem))
    assert not re.search(r'\b(transition|animation)\s*:', re.sub(bloco, '', com))


def test_nenhum_important_no_css():
    integros = _integros_do_pacote()
    for arquivo in _css_do_projeto():
        if arquivo not in integros:
            assert '!important' not in arquivo.read_text(encoding='utf-8'), arquivo.name


def test_logo_tem_largura_proporcional_ao_viewbox_e_nao_zero():
    # Logo na altura de 26 px: a largura é a do SVG nessa altura (viewBox 1460×400 → 95 px). `width="0"` seria errado.
    svg = (AGRION / 'logo' / 'agrion-horizontal.svg').read_text(encoding='utf-8')
    viewbox = re.search(r'viewBox="([^"]+)"', svg)
    assert viewbox is not None
    _, _, largura_svg, altura_svg = map(float, viewbox.group(1).split())
    casca = (TEMPLATES / 'casca.html').read_text(encoding='utf-8')
    img = re.search(r'alt="AgriOn" width="(\d+)" height="26"', casca)
    assert img is not None, 'logo sem width numérico na altura de 26'
    assert int(img.group(1)) == round(26 * largura_svg / altura_svg) == 95


def _estilo_inline(texto):
    # Atributo `style=` no markup (HTML ou string JS, inclusive escapado `\"`), `.cssText =` e `setAttribute('style')`.
    # `element.style.setProperty` e `elemento.style.propriedade = ...` são permitidos e não casam.
    return re.findall(r'\sstyle\s*=\s*\\?["\'`]|\.cssText\s*=|setAttribute\(\s*["\']style["\']', texto)


def _js_proprio():
    return sorted(p for p in ESTATICOS.rglob('*.js') if 'terceiros' not in p.relative_to(ESTATICOS).parts and not p.name.endswith('.test.js'))


def test_detector_de_estilo_inline_pega_o_atributo_e_deixa_setproperty():
    assert _estilo_inline('<p style="color:red">') != []
    assert _estilo_inline("html = '<p style=\\\"x\\\">'") != []
    assert _estilo_inline("el.setAttribute('style', 'x')") != []
    assert _estilo_inline('el.style.cssText = "x"') != []
    assert _estilo_inline("el.style.setProperty('--cor', 'x')") == []
    assert _estilo_inline("amostra.style.backgroundColor = cor; const estilo = montar(); new maplibre.Map({ style: estilo })") == []


def test_js_proprio_nao_monta_markup_com_estilo_inline():
    assert _js_proprio(), 'nenhum JS próprio encontrado: o teste estaria vazio'
    for arquivo in _js_proprio():
        assert _estilo_inline(arquivo.read_text(encoding='utf-8')) == [], arquivo.name


def test_atributo_hidden_vence_o_display_de_qualquer_componente():
    # O botão do menu nasce `hidden` e o `.botao` é `inline-flex`: sem a regra, o botão apareceria em tela larga.
    assert 'html [hidden] { display: none; }' in (ESTATICOS / 'base.css').read_text(encoding='utf-8')


def _sem_where(seletor):
    """Tira cada `:where(...)` com os parênteses balanceados: por spec (CSS Selectors 4) ele tem especificidade zero."""
    while (inicio := seletor.find(':where(')) >= 0:
        fim, profundidade = inicio + len(':where('), 1
        while profundidade and fim < len(seletor):
            profundidade += {'(': 1, ')': -1}.get(seletor[fim], 0)
            fim += 1
        seletor = seletor[:inicio] + seletor[fim:]
    return seletor


def _ofensores_de_especificidade(texto):
    """Seletores com `display` e mais de uma classe, atributo ou pseudo, exceto as regras `html <seletor>[hidden]`."""
    achados = []
    for seletor, corpo in re.findall(r'([^{}]+)\{([^{}]*)\}', re.sub(r'/\*.*?\*/', '', texto, flags=re.S)):
        if re.search(r'(^|;|\s)display\s*:', corpo):
            for parte in _sem_where(seletor).split(','):
                parte = parte.strip()
                if re.fullmatch(r'html .+\[hidden\]', parte):
                    continue
                if len(re.findall(r'[.#\[:]', re.sub(r'::?is\(', '', parte))) > 1:
                    achados.append(parte)
    return achados


def _seletores_hidden(texto):
    """Seletores `html <algo>[hidden]` do CSS com o corpo de cada um: a regra que devolve o `hidden` ao ofensor."""
    achados = {}
    for seletor, corpo in re.findall(r'([^{}]+)\{([^{}]*)\}', re.sub(r'/\*.*?\*/', '', texto, flags=re.S)):
        for parte in seletor.split(','):
            if re.fullmatch(r'html .+\[hidden\]', parte.strip()):
                achados[parte.strip()] = corpo
    return achados


def _sem_regra_hidden(ofensores, texto_proprio):
    """Ofensores de cópia íntegra sem `html <ofensor>[hidden]` que declare `display: none` no CSS próprio."""
    existentes = _seletores_hidden(texto_proprio)
    return [
        ofensor for ofensor in ofensores
        if not re.search(r'(^|;|\s)display\s*:\s*none\b', existentes.get(f'html {ofensor}[hidden]', ''))
    ]


def test_nenhum_componente_tem_especificidade_maior_que_a_regra_de_hidden():
    # `html [hidden]` (0,1,1) vence toda regra com `display` de uma classe. Cópia íntegra pode ter seletor mais específico
    # só com a regra `html <seletor>[hidden]` correspondente no CSS próprio (agrion-proprio.css); o resto não pode.
    integros = _integros_do_pacote()
    proprio = ''.join(p.read_text(encoding='utf-8') for p in _css_do_projeto() if p not in integros)
    for arquivo in _css_do_projeto():
        texto = arquivo.read_text(encoding='utf-8')
        if arquivo in integros:
            assert _sem_regra_hidden(_ofensores_de_especificidade(texto), proprio) == [], arquivo.name
        else:
            assert _ofensores_de_especificidade(texto) == [], arquivo.name


def test_o_teste_de_especificidade_reprova_seletor_sem_regra_hidden():
    assert _ofensores_de_especificidade('.a .b { display: grid; }') == ['.a .b']
    assert _ofensores_de_especificidade('html .a .b[hidden] { display: none; }') == []
    assert _sem_regra_hidden(['.a .b'], '') == ['.a .b']
    assert _sem_regra_hidden(['.a .b'], 'html .a .b[hidden] { display: none; }') == []
    # Compensação sem `display: none` no corpo não cobre o ofensor (o `hidden` continuaria perdendo para o `display`).
    assert _sem_regra_hidden(['.a .b'], 'html .a .b[hidden] { display: grid; }') == ['.a .b']
    assert _sem_regra_hidden(['.a .b'], 'html .a .b[hidden] { color: red; }') == ['.a .b']


def test_where_tem_especificidade_zero_no_teste_de_especificidade():
    # `:where(...)` não conta, inclusive com `:not([open])` e lista de seletores dentro (parênteses aninhados e vírgula).
    assert _ofensores_de_especificidade(':where(.a:not([open])) > .b { display: none; }') == []
    assert _ofensores_de_especificidade(':where(.a, .c) .b { display: grid; }') == []
    # Com o `:where` tirado, o que sobra ainda é contado: dois elementos de classe fora dele reprovam.
    assert _ofensores_de_especificidade(':where(.a) .b .c { display: grid; }') == ['.b .c']
    # Sem `:where`, o mesmo seletor continua reprovado: o teste não relaxou o cálculo para tudo.
    assert _ofensores_de_especificidade('.a:not([open]) > .b { display: none; }') == ['.a:not([open]) > .b']
    assert _ofensores_de_especificidade('.a:where(.b) { display: none; }') == []
    assert _ofensores_de_especificidade('.a:where(.b .c) { display: none; }') == []


def test_menu_mais_acoes_fechado_esconde_a_lista_com_especificidade_zero():
    # Regra do menu fechado com `:where` (0,1,0). Só ela declara `display` em `.ag-mais-acoes-lista`: nenhuma outra
    # regra pode concorrer com a ordem de cascata.
    css = (ESTATICOS / 'agrion-proprio.css').read_text(encoding='utf-8')
    assert ':where(.ag-mais-acoes:not([open])) > .ag-mais-acoes-lista { display: none; }' in css
    declaracoes = [corpo for seletor, corpo in re.findall(r'([^{}]+)\{([^{}]*)\}', re.sub(r'/\*.*?\*/', '', css, flags=re.S))
                   if any(parte.strip().endswith('.ag-mais-acoes-lista') for parte in seletor.split(',')) and re.search(r'(^|;|\s)display\s*:', corpo)]
    assert len(declaracoes) == 1


def test_campo_com_teclado_leva_inputmode_e_sem_corretor():
    html = _renderizar('componentes/campo.html', id='cpf', nome='cpf', rotulo='CPF', teclado='numeric')
    assert 'inputmode="numeric" spellcheck="false"' in html
    assert 'inputmode' not in _renderizar('componentes/campo.html', id='cpf', nome='cpf', rotulo='CPF')


def _declaracoes(seletor):
    css = (ESTATICOS / 'componentes.css').read_text(encoding='utf-8')
    achado = re.search(rf'(?m)^{re.escape(seletor)}\s*\{{([^}}]*)\}}', css)
    assert achado is not None, seletor
    return achado.group(1)


def _declaracoes_do_pacote(seletor):
    # A árvore é do pacote (agrion/styles): a aninhada leva recuo e linha guia.
    css = (AGRION / 'styles' / 'componentes.css').read_text(encoding='utf-8')
    achado = re.search(rf'(?m)^{re.escape(seletor)}\s*\{{([^}}]*)\}}', css)
    assert achado is not None, seletor
    return achado.group(1)


def test_lista_de_fazendas_em_grade_e_arvore_aninhada_leva_recuo_e_linha_guia():
    # Sem o recuo e a linha, a árvore de 3 níveis vira uma lista plana (R11); a estrutura HTML sozinha não pega isso.
    assert 'display: grid' in _declaracoes('.lista-fazendas, .lista-atalhos')
    aninhada = _declaracoes_do_pacote('.ag-arvore .ag-arvore')
    for declaracao in ('margin-left:', 'padding-left:', 'border-left:'):
        assert declaracao in aninhada


def test_abas_marcam_a_aberta_com_aria_current_e_zero_aparece_sem_contador_ausente():
    abas = [
        {'valor': 'mapa', 'rotulo': 'Mapa', 'icone': 'map'},
        {'valor': 'camadas', 'rotulo': 'Camadas', 'contador': 3},
        {'valor': 'vazio', 'rotulo': 'Vazia', 'contador': 0},
    ]
    html = _renderizar('componentes/abas.html', abas=abas, atual='camadas', rotulo='Seções da fazenda')
    assert '<a class="ag-aba" href="?aba=camadas" aria-current="page">Camadas<span class="ag-aba-contador">3</span></a>' in html
    assert '<a class="ag-aba" href="?aba=mapa">' in html  # a aba fechada não leva aria-current
    assert '<span class="ag-aba-contador">0</span>' in html  # zero é contagem real
    assert html.count('aria-current') == 1
    assert 'aria-label="Seções da fazenda"' in html
    assert html.count('ag-aba-contador') == 2  # Mapa não tem contador: nada aparece


def test_abas_vazias_ou_sem_aba_aberta_nao_marcam_nada():
    assert '<nav class="ag-abas" aria-label="R"' in _renderizar('componentes/abas.html', abas=[], atual='x', rotulo='R')
    sem_aberta = _renderizar('componentes/abas.html', abas=[{'valor': 'a', 'rotulo': 'A'}], atual='zzz', rotulo='R')
    assert 'aria-current' not in sem_aberta


def test_abas_rotulo_hostil_sai_escapado():
    html = _renderizar('componentes/abas.html', abas=[{'valor': 'a', 'rotulo': HOSTIL}], atual='a', rotulo='R')
    assert HOSTIL not in html
    assert '&lt;script&gt;alert(1)&lt;/script&gt;' in html


def test_arvore_no_com_destino_e_link_e_o_atual_leva_aria_current():
    nos = [
        {'id': 1, 'nome': 'Norte', 'destino': '/a/1', 'filhos': [{'id': 2, 'nome': 'Talhão 1', 'destino': '/a/2'}]},
        {'id': 3, 'nome': 'Sul', 'destino': None},
    ]
    html = _renderizar('componentes/arvore.html', nos=nos, atual=2)
    assert '<a class="ag-arvore-no" href="/a/2" aria-current="true">' in html
    assert '<a class="ag-arvore-no" href="/a/1">' in html
    assert '<span class="ag-arvore-no"><span class="ag-arvore-seta" data-sem-filhos="">' in html  # sem destino: texto, não link
    assert html.count('aria-current') == 1
    assert 'data-aberto=""' in html  # Norte tem filhos
    assert html.count('data-sem-filhos') == 2  # Talhão 1 e Sul


def test_arvore_vazia_meta_e_nome_hostil():
    assert '<ul class="ag-arvore">' in _renderizar('componentes/arvore.html', nos=[])
    assert '<li' not in _renderizar('componentes/arvore.html', nos=[])
    html = _renderizar('componentes/arvore.html', nos=[{'nome': HOSTIL, 'meta': '', 'destino': None}])
    assert HOSTIL not in html
    assert '&lt;script&gt;' in html
    assert 'ag-arvore-meta' not in html  # meta vazia não aparece


def test_avatar_mostra_iniciais_de_duas_palavras_e_respeita_tamanho():
    assert '<span class="ag-avatar" data-tamanho="md" aria-hidden="true">AM</span>' in _renderizar('componentes/avatar.html', nome='ana maria souza')
    assert 'data-tamanho="lg"' in _renderizar('componentes/avatar.html', nome='Ana', tamanho='lg')
    assert 'data-tamanho="md"' in _renderizar('componentes/avatar.html', nome='Ana', tamanho='xl')  # fora da lista cai no padrão


def test_avatar_ausente_nao_inventa_letra_e_hostil_sai_escapado():
    assert 'aria-hidden="true"></span>' in _renderizar('componentes/avatar.html', nome=None)
    assert 'aria-hidden="true"></span>' in _renderizar('componentes/avatar.html', nome='')
    html = _renderizar('componentes/avatar.html', nome=HOSTIL)
    assert HOSTIL not in html
    assert '&lt;' in html


def test_cabecalho_com_trilha_marca_o_ultimo_item_como_pagina_atual():
    trilha = [{'nome': 'Fazendas', 'href': '/f/'}, {'nome': 'Fazenda A', 'href': '/f/1'}]
    html = _renderizar('componentes/cabecalho_pagina.html', titulo='Fazenda A', subtitulo='Atualizada hoje', trilha=trilha)
    assert '<a href="/f/">Fazendas</a>' in html
    assert '<span aria-current="page">Fazenda A</span>' in html
    assert '<span aria-hidden="true">/</span>' in html
    assert '<h1>Fazenda A</h1>' in html
    assert '<p class="ag-cabecalho-descricao">Atualizada hoje</p>' in html


def test_cabecalho_sem_trilha_nem_descricao_e_titulo_hostil_escapado():
    html = _renderizar('componentes/cabecalho_pagina.html', titulo='Início')
    assert '<h1>Início</h1>' in html
    assert 'ag-trilha' not in html
    assert 'ag-cabecalho-descricao' not in html
    assert HOSTIL not in _renderizar('componentes/cabecalho_pagina.html', titulo=HOSTIL)


def test_cabecalho_item_sem_href_vira_texto_e_nao_link_vazio():
    # Regressão: item sem href saía como <a href=""> (chave `trilha` sem href); o atual vira texto.
    html = _renderizar('componentes/cabecalho_pagina.html', titulo='Fazenda A', trilha=[{'nome': 'Fazendas'}, {'nome': 'Fazenda A'}])
    assert 'href=""' not in html
    assert '<span>Fazendas</span>' in html
    assert '<span aria-current="page">Fazenda A</span>' in html


def test_cabecalho_com_acoes_template_poe_o_parcial_depois_do_titulo():
    html = _renderizar('componentes/cabecalho_pagina.html', titulo='Fazendas', acoes_template='componentes/botao.html', texto='Exportar', href='/x.csv')
    assert html.index('<h1>Fazendas</h1>') < html.index('<div class="ag-cabecalho-acoes">')
    assert 'Exportar' in html.split('<div class="ag-cabecalho-acoes">')[1]


def test_cabecalho_sem_acoes_template_nao_tem_bloco_de_acoes():
    assert 'ag-cabecalho-acoes' not in _renderizar('componentes/cabecalho_pagina.html', titulo='Início')


def test_cabecalho_com_acoes_template_inexistente_falha_em_vez_de_sair_calado():
    # Negativo: nome de parcial errado é erro de programação; não pode sair um cabeçalho sem ações sem aviso.
    from django.template import TemplateDoesNotExist

    with pytest.raises(TemplateDoesNotExist):
        _renderizar('componentes/cabecalho_pagina.html', titulo='Fazendas', acoes_template='componentes/nao_existe.html')


def test_cabecalho_com_texto_puro_em_vez_de_item_nao_gera_link_vazio():
    # Regressão: lista de texto (forma de trilha_do_topo) passada como `trilha` não vira <a href=""></a>.
    html = _renderizar('componentes/cabecalho_pagina.html', titulo='Fazenda A', trilha=['Fazendas', 'Fazenda A'])
    assert '<a href=""' not in html
    assert 'href=""' not in html


def _controles_sem_id(html):
    # `aria-controls` cujo id não existe no mesmo HTML (WCAG 4.1.2).
    return [alvo for alvo in re.findall(r'aria-controls="([^"]+)"', html) if f'id="{alvo}"' not in html]


def test_aria_controls_da_casca_aponta_id_que_existe():
    texto = (TEMPLATES / 'casca.html').read_text(encoding='utf-8')
    assert re.findall(r'aria-controls="', texto)  # não vazio: a casca tem controles
    assert _controles_sem_id(texto) == []


def test_aria_controls_sem_id_correspondente_e_detectado():
    # Caminho infeliz: o detector acusa o controle que aponta para id ausente.
    assert _controles_sem_id('<button aria-controls="nao-existe">x</button><div id="outro"></div>') == ['nao-existe']


def test_etapas_marcam_feita_atual_e_futura_com_check_de_traco_forte():
    etapas = ['Enviar arquivo', 'Conferir prévia', 'Publicar']
    html = _renderizar('componentes/etapas.html', etapas=etapas, atual=1)
    assert html.count('data-estado="feita"') == 1
    assert '<li class="ag-etapa" data-estado="atual" aria-current="step">' in html
    assert html.count('data-estado="futura"') == 1
    assert 'stroke-width="2.5"' in html  # o check da etapa feita usa traço 2.5 (COMPONENTES.md)


def test_etapas_padrao_zero_e_lista_vazia_nao_marcam_feita():
    html = _renderizar('componentes/etapas.html', etapas=['Um', 'Dois'])
    assert '<li class="ag-etapa" data-estado="atual" aria-current="step">' in html
    assert 'data-estado="feita"' not in html
    assert 'class="ag-etapa"' not in _renderizar('componentes/etapas.html', etapas=[], atual=0)


def test_ficha_tem_os_campos_com_data_campo_e_modelo_vazio_para_o_mapa():
    ficha = {campo: 'Sem informação' for campo in ('camada', 'atributo', 'valor', 'origem', 'metodo', 'fonte', 'data', 'situacao', 'ressalva')}
    html = _renderizar('componentes/ficha.html', ficha=ficha)
    assert html.count('data-campo=') == 9
    assert '<dl class="ag-ficha">' in html
    modelo = _renderizar('componentes/ficha.html', ficha=None)
    assert '<dd data-campo="camada"></dd>' in modelo  # o mapa.js preenche pelo data-campo


def test_ficha_com_texto_hostil_sai_escapado():
    ficha = {campo: HOSTIL for campo in ('camada', 'atributo', 'valor', 'origem', 'metodo', 'fonte', 'data', 'situacao', 'ressalva')}
    html = _renderizar('componentes/ficha.html', ficha=ficha)
    assert HOSTIL not in html
    assert '&lt;script&gt;' in html


def test_indicador_com_zero_mostra_zero_e_nao_sem_dados():
    html = _renderizar('componentes/indicador.html', rotulo='Talhões', valor=0, unidade='ha', icone='map')
    assert '<span class="ag-indicador-valor">0<small>ha</small></span>' in html
    assert 'data-sem-dado' not in html
    assert 'Sem dados' not in html
    assert _icone('map', 16) in html


def test_indicador_ausente_mostra_sem_dados_nunca_zero():
    for ausente in (None, ''):
        html = _renderizar('componentes/indicador.html', rotulo='Área', valor=ausente, unidade='ha')
        assert '<span class="ag-indicador-valor" data-sem-dado="">Sem dados</span>' in html
        assert '>0<' not in html


def test_indicador_com_rodape_e_texto_hostil_escapado():
    html = _renderizar('componentes/indicador.html', rotulo='Camadas', valor=HOSTIL, rodape='Revisar agora')
    assert HOSTIL not in html
    assert '&lt;script&gt;' in html
    assert '<span class="ag-indicador-rodape">Revisar agora</span>' in html
    assert 'ag-indicador-rodape' not in _renderizar('componentes/indicador.html', rotulo='X', valor=1)


def test_lista_de_convites_vazia_nao_tem_item_e_ausente_vira_sem_informacao():
    assert 'class="ag-convite"' not in _renderizar('componentes/lista_convites.html', convites=[])
    convites = [{'id': 9, 'empresa_nome': 'Empresa B', 'cargo_nome': '', 'expira_em': None}]
    html = _renderizar('componentes/lista_convites.html', convites=convites)
    assert 'Cargo: Sem informação · válido até Sem informação' in html
    assert '<span class="ag-avatar" data-tamanho="md" aria-hidden="true">EB</span>' in html
    assert html.index('Recusar') < html.index('Aceitar')  # Recusar secundário antes do Aceitar primário, como no protótipo


def test_lista_de_convites_com_empresa_hostil_sai_escapada():
    convites = [{'id': 1, 'empresa_nome': HOSTIL, 'cargo_nome': 'Técnico', 'expira_em': None}]
    html = _renderizar('componentes/lista_convites.html', convites=convites)
    assert HOSTIL not in html
    assert '&lt;script&gt;' in html


def test_painel_com_titulo_acoes_e_corpo_nomeado():
    html = _renderizar(
        'componentes/painel.html', titulo='Convites', subtitulo='2 aguardando', corpo='componentes/vazio.html', texto='Sem nada',
        acoes=[{'rotulo': 'Ver todas', 'destino': '/f/', 'variante': 'fantasma'}],
    )
    assert '<h2>Convites</h2>' in html
    assert '<p class="ag-painel-sub">2 aguardando</p>' in html
    assert 'href="/f/"' in html
    assert 'Ver todas' in html
    assert 'Sem nada' in html  # o corpo vem do template nomeado


def test_painel_acao_sem_destino_nao_vira_botao_e_sem_titulo_nao_tem_topo():
    html = _renderizar('componentes/painel.html', acoes=[{'rotulo': 'Sem destino'}])
    assert 'Sem destino' not in html
    assert '<a ' not in html  # botão sem ação não pode aparecer
    vazio = _renderizar('componentes/painel.html')
    assert 'ag-painel-topo' not in vazio
    assert 'data-sem-margem' in _renderizar('componentes/painel.html', sem_margem=True)


def test_tabela_primeira_celula_vira_link_so_com_destino():
    colunas = ['Nome', 'Área']
    linhas = [['F1', '10'], ['F2', '20']]
    html = _renderizar('componentes/tabela.html', legenda='Fazendas', colunas=colunas, linhas=linhas, destinos=['/f/1', None])
    assert '<a href="/f/1">F1</a>' in html
    assert html.count('data-clicavel=""') == 1
    assert '<td>F2</td>' in html
    assert '<td>20</td>' in html
    assert '<a href="/f/2"' not in html


def test_tabela_sem_linhas_e_com_celula_hostil_escapada():
    vazia = _renderizar('componentes/tabela.html', legenda='Fazendas', colunas=['Nome'], linhas=[])
    assert '<td>' not in vazia
    assert '<th scope="col">Nome</th>' in vazia
    html = _renderizar('componentes/tabela.html', legenda='F', colunas=['Nome'], linhas=[[HOSTIL]], destinos=['/f/1'])
    assert HOSTIL not in html
    assert '&lt;script&gt;' in html


def test_legenda_cor_valida_entra_por_data_cor_e_invalida_fica_sem_cor():
    itens = [{'rotulo': 'APP', 'cor': '2'}, {'rotulo': 'Sem cor', 'cor': '9'}]
    html = _renderizar('componentes/legenda.html', itens=itens, titulo='Legenda')
    assert '<i data-cor="2"></i>APP' in html
    assert '<i data-cor=""></i>Sem cor' in html  # cor fora de 1 a 6 não ganha cor inventada
    assert '<p class="ag-camadas-grupo ag-legenda-titulo">Legenda</p>' in html


def test_legenda_sem_itens_nao_aparece_e_rotulo_hostil_sai_escapado():
    assert _renderizar('componentes/legenda.html', itens=[]).strip() == ''
    html = _renderizar('componentes/legenda.html', itens=[{'rotulo': HOSTIL, 'cor': '1'}])
    assert HOSTIL not in html
    assert '&lt;script&gt;' in html


def test_painel_de_camadas_visivel_oculta_e_opacidade():
    grupos = [{'nome': 'Divisão', 'camadas': [
        {'id': 1, 'nome': 'Talhões', 'detalhe': '3 polígonos', 'cor': '1', 'visivel': True, 'opacidade': 60},
        {'id': 2, 'nome': 'Pivôs', 'cor': '3', 'visivel': False, 'opacidade': None},
    ]}]
    html = _renderizar('componentes/painel_camadas.html', grupos=grupos)
    assert '<span class="ag-camada-amostra" data-cor="1"></span>' in html
    assert '<span class="so-leitor">Ocultar Talhões</span>' in html
    assert 'aria-pressed="true"' in html
    assert '<span class="so-leitor">Mostrar Pivôs</span>' in html
    assert 'aria-pressed="false"' in html
    assert 'data-oculta=""' in html  # Pivôs está oculta
    assert html.count('type="range"') == 1  # só a camada visível com opacidade tem o controle
    assert '<span class="ag-camada-opacidade-valor">60%</span>' in html
    assert 'hidden><span class="so-leitor">Recolher camadas</span>' in html  # depende de JS: nasce oculto


def test_painel_de_camadas_cor_invalida_grupo_vazio_e_nome_hostil():
    grupos = [{'nome': 'G', 'camadas': [{'id': 1, 'nome': HOSTIL, 'cor': '9', 'visivel': True, 'opacidade': None}]}]
    html = _renderizar('componentes/painel_camadas.html', grupos=grupos)
    assert 'data-cor=""' in html
    assert HOSTIL not in html
    assert '&lt;script&gt;' in html
    assert 'type="range"' not in html  # ausente não ganha controle de opacidade
    assert 'class="ag-camada"' not in _renderizar('componentes/painel_camadas.html', grupos=[])


def test_filtros_iniciais_e_na_posicao_tratam_ausente_e_fora_da_lista():
    from projeto.templatetags.componentes import iniciais, na_posicao

    assert iniciais('ana maria souza') == 'AM'
    assert iniciais('  ') == ''
    assert iniciais(None) == ''
    assert iniciais(12) == ''
    assert na_posicao(['a', None], 0) == 'a'
    assert na_posicao(['a', None], 1) is None
    assert na_posicao(['a'], 3) == ''
    assert na_posicao(None, 0) == ''
    assert na_posicao(['a'], '0') == ''



# Componentes da spec 012 (COMPONENTES.md): uma variante ou estado por teste, com caso infeliz e valor hostil.
HOSTIL = '<script>alert(1)</script>'


def _icone(nome, tamanho):
    # O SVG da tag não leva o nome; compara-se com a saída da própria tag para o mesmo nome e tamanho.
    return Template('{% icone nome tamanho=t %}').render(Context({'nome': nome, 't': tamanho}))


def test_botao_variante_e_tamanho_do_protótipo():
    html = _renderizar('componentes/botao.html', texto='x', variante='fantasma', tamanho='lg')
    assert 'data-variante="fantasma" data-tamanho="lg"' in html
    assert 'data-variante="perigo" data-tamanho="md"' in _renderizar('componentes/botao.html', texto='x', variante='perigo')


def test_botao_variante_e_tamanho_desconhecidos_caem_no_padrao():
    html = _renderizar('componentes/botao.html', texto='x', variante='inventada', tamanho='gigante')
    assert 'data-variante="primario" data-tamanho="md"' in html


def test_botao_carregando_tem_giro_aria_busy_e_desabilitado():
    html = _renderizar('componentes/botao.html', texto='Entrar', tipo='submit', carregando=True)
    assert 'class="ag-giro"' in html
    assert 'aria-busy="true"' in html
    assert ' disabled' in html
    assert 'Entrar' in html


def test_botao_so_icone_marca_data_icone_e_rotulo():
    html = _renderizar('componentes/botao.html', so_icone=True, icone='x', rotulo='Fechar')
    assert 'data-icone=""' in html
    assert '<span class="so-leitor">Fechar</span>' in html
    assert _icone('x', 16) in html


def test_botao_como_link_desabilitado_usa_aria_disabled():
    html = _renderizar('componentes/botao.html', texto='Voltar', href='/inicio/', desabilitado=True)
    assert html.startswith('<a class="ag-botao"')
    assert 'href="/inicio/"' in html
    assert 'aria-disabled="true"' in html


def test_botao_escapa_texto_hostil():
    html = _renderizar('componentes/botao.html', texto=HOSTIL)
    assert HOSTIL not in html
    assert '&lt;script&gt;' in html


def test_caixa_marcada_com_descricao():
    html = _renderizar('componentes/caixa.html', rotulo='Enviar camada', descricao='Envia arquivos.', marcada=True, nome='p', valor='1')
    assert '<input type="checkbox" name="p" value="1" checked>' in html
    assert '<span class="ag-caixa-descricao">Envia arquivos.</span>' in html


def test_caixa_sem_marcacao_e_desabilitada():
    html = _renderizar('componentes/caixa.html', rotulo='x', desabilitada=True)
    assert 'checked' not in html
    assert ' disabled' in html


@pytest.mark.parametrize('tipo', ['text', 'password', 'email', 'search', 'number', 'date'])
def test_campo_de_texto_por_tipo(tipo):
    assert f'type="{tipo}"' in _renderizar('componentes/campo.html', id='c', rotulo='C', tipo=tipo)


def test_campo_tipo_desconhecido_vira_texto():
    assert 'type="text"' in _renderizar('componentes/campo.html', id='c', rotulo='C', tipo='script')


def test_campo_textarea_linhas_padrao_e_outra():
    assert 'rows="3"' in _renderizar('componentes/campo.html', id='t', rotulo='T', tipo='textarea')
    assert 'rows="5"' in _renderizar('componentes/campo.html', id='t', rotulo='T', tipo='textarea', linhas=5)


def test_campo_opcional_e_ajuda_ligada_ao_controle():
    html = _renderizar('componentes/campo.html', id='o', rotulo='Obs', opcional=True, ajuda='Até 200 caracteres.')
    assert '<span class="ag-rotulo-opcional"> (opcional)</span>' in html
    assert 'class="ag-ajuda" id="o-descricao"' in html
    assert 'aria-describedby="o-descricao"' in html
    assert 'aria-invalid' not in html


def test_campo_erro_tem_icone_e_marca_invalido():
    html = _renderizar('componentes/campo.html', id='e', rotulo='E', erro='Campo obrigatório.')
    assert 'data-invalido=""' in html
    assert 'class="ag-erro-texto" id="e-descricao"' in html
    assert 'aria-invalid="true"' in html
    assert _icone('circle-alert', 14) in html


def test_campo_escapa_rotulo_e_valor_hostis():
    html = _renderizar('componentes/campo.html', id='h', rotulo=HOSTIL, valor=HOSTIL)
    assert HOSTIL not in html


def test_aviso_tipo_desconhecido_cai_em_info_sem_papel():
    html = _renderizar('componentes/aviso.html', tipo='inventado', texto='x')
    assert 'data-tipo="info"' in html
    assert 'role=' not in html


@pytest.mark.parametrize(('tipo', 'icone'), [('erro', 'circle-alert'), ('aviso', 'triangle-alert'), ('info', 'info'), ('sucesso', 'circle-check')])
def test_aviso_icone_por_tipo(tipo, icone):
    assert _icone(icone, 18) in _renderizar('componentes/aviso.html', tipo=tipo, texto='x')


def test_aviso_sucesso_anuncia_como_status():
    assert 'role="status"' in _renderizar('componentes/aviso.html', tipo='sucesso', texto='x')


def test_aviso_fechavel_nasce_escondido_com_rotulo():
    html = _renderizar('componentes/aviso.html', tipo='aviso', texto='x', fechavel=True)
    assert 'class="ag-botao ag-aviso-fechar"' in html
    assert 'hidden><span class="so-leitor">Fechar aviso</span>' in html


def test_aviso_sem_fechavel_nao_tem_botao():
    assert 'ag-aviso-fechar' not in _renderizar('componentes/aviso.html', tipo='info', texto='x')


def test_aviso_oculto_com_texto_vazio_para_o_js_preencher():
    html = _renderizar('componentes/aviso.html', tipo='erro', texto='', id='m', oculto=True)
    assert 'id="m" hidden>' in html
    assert '<p class="ag-aviso-texto"></p>' in html


def test_aviso_escapa_titulo_e_texto_hostis():
    html = _renderizar('componentes/aviso.html', tipo='info', titulo=HOSTIL, texto=HOSTIL)
    assert HOSTIL not in html


def test_vazio_icone_padrao_inbox_e_icone_desconhecido_quebra_alto():
    assert _icone('inbox', 20) in _renderizar('componentes/vazio.html', texto='Nada.')
    with pytest.raises(TemplateSyntaxError):
        _renderizar('componentes/vazio.html', texto='x', icone='nao-existe')


def test_vazio_com_titulo_moldura_e_sem_texto_nao_imprime_paragrafo():
    html = _renderizar('componentes/vazio.html', titulo='Sem camadas', moldura=True)
    assert 'data-moldura=""' in html
    assert 'class="ag-vazio-titulo"' in html
    assert 'ag-vazio-texto' not in html


def test_vazio_texto_vazio_mantem_o_paragrafo_para_o_js():
    assert '<p class="ag-vazio-texto"></p>' in _renderizar('componentes/vazio.html', texto='')


def test_vazio_acao_so_aparece_com_destino():
    assert 'ag-vazio-acoes' not in _renderizar('componentes/vazio.html', texto='x', acao_rotulo='Cadastrar')
    assert 'ag-vazio-acoes' in _renderizar('componentes/vazio.html', texto='x', acao_rotulo='Cadastrar', acao_destino='/x/')


def test_selo_situacao_mapeia_tom_e_texto():
    html = _renderizar('componentes/selo.html', situacao='em_analise')
    assert 'data-tom="aviso"' in html
    assert 'Em análise' in html


def test_selo_sem_ponto_quando_pedido():
    assert 'ag-selo-ponto' not in _renderizar('componentes/selo.html', texto='x', ponto=False)


def test_selo_tom_e_texto_sem_situacao():
    html = _renderizar('componentes/selo.html', tom='marca', texto='Administrador')
    assert 'data-tom="marca"' in html
    assert 'Administrador' in html
    assert 'ag-selo-ponto' in html


def test_selo_situacao_desconhecida_cai_no_tom():
    assert 'data-tom="erro"' in _renderizar('componentes/selo.html', situacao='inventada', tom='erro', texto='x')


def test_selo_tom_inventado_vira_neutro():
    assert 'data-tom="neutro"' in _renderizar('componentes/selo.html', tom='roxo', texto='x')


OPCOES_DO_SEGMENTADO = [{'valor': 'satelite', 'rotulo': 'Satélite', 'icone': 'satellite'}, {'valor': 'ruas', 'rotulo': 'Ruas'}]


def test_segmentado_marca_a_opcao_ativa_e_o_grupo():
    html = _renderizar('componentes/segmentado.html', opcoes=OPCOES_DO_SEGMENTADO, valor='ruas', rotulo='Fundo do mapa')
    assert '<fieldset class="ag-segmentado">' in html
    assert '<legend class="so-leitor">Fundo do mapa</legend>' in html
    assert 'aria-pressed="true"' in html
    assert 'aria-pressed="false"' in html


def test_segmentado_com_href_vira_link_e_so_a_ativa_tem_aria_current():
    opcoes = [{'valor': 'todas', 'rotulo': 'Todas', 'href': '?'}, {'valor': 'ativas', 'rotulo': 'Ativas', 'href': '?situacao=ativas'}]
    html = _renderizar('componentes/segmentado.html', opcoes=opcoes, valor='ativas', rotulo='Filtrar fazendas')
    assert '<a href="?situacao=ativas" data-valor="ativas" aria-current="true">Ativas</a>' in html
    assert '<a href="?" data-valor="todas">Todas</a>' in html
    assert '<button' not in html


def test_segmentado_com_href_sem_opcao_ativa_nao_marca_nenhuma():
    html = _renderizar('componentes/segmentado.html', opcoes=[{'valor': 'a', 'rotulo': 'A', 'href': '?x=a'}], valor='outra')
    assert 'aria-current' not in html


def test_segmentado_sem_opcoes_nao_tem_botao():
    assert '<button' not in _renderizar('componentes/segmentado.html', opcoes=[], valor='x')


def test_esqueleto_ultima_linha_curta_com_mais_de_uma():
    html = _renderizar('componentes/esqueleto.html', linhas=3)
    assert html.count('<span class="ag-esqueleto"') + html.count('<span class="ag-esqueleto ag-esqueleto-curto"') == 3
    assert html.count('ag-esqueleto-curto') == 1


def test_esqueleto_uma_linha_nao_e_curta():
    html = _renderizar('componentes/esqueleto.html', linhas=1)
    assert 'ag-esqueleto-curto' not in html
    assert html.count('class="ag-esqueleto"') == 1


@pytest.mark.parametrize('linhas', [0, -2, 21, '3'])
def test_esqueleto_linhas_invalidas_nao_geram_nada(linhas):
    html = _renderizar('componentes/esqueleto.html', linhas=linhas)
    assert '<span class="ag-esqueleto"' not in html
    assert 'ag-esqueleto-curto' not in html


def test_envio_arquivo_e_label_com_entrada_escondida():
    html = _renderizar('componentes/envio_arquivo.html', aceita='.zip,.kml', ajuda='Até 50 MB', id='arq', nome='arquivo')
    assert '<label class="ag-envio">' in html
    assert 'role="button"' not in html
    assert '<input type="file" class="so-leitor" id="arq" name="arquivo" accept=".zip,.kml">' in html
    assert 'Até 50 MB' in html


def test_envio_arquivo_titulo_padrao_sem_ajuda():
    html = _renderizar('componentes/envio_arquivo.html')
    assert 'Arraste o arquivo ou clique para escolher' in html
    assert 'class="ag-ajuda"' not in html


def test_envio_arquivo_escapa_aceita_hostil():
    html = _renderizar('componentes/envio_arquivo.html', aceita='"><script>alert(1)</script>')
    assert HOSTIL not in html


def test_dialogo_nasce_fechado_e_liga_titulo_e_descricao():
    html = _renderizar('componentes/dialogo.html', id='convidar', titulo='Convidar pessoa', descricao='Envia o convite.')
    assert '<dialog class="ag-dialogo" id="convidar"' in html
    assert 'open' not in html.split('>', 1)[0]
    assert 'aria-labelledby="convidar-titulo"' in html
    assert '<h2 id="convidar-titulo">Convidar pessoa</h2>' in html
    assert 'data-dialogo-fechar' in html


def test_dialogo_corpo_e_rodape_vem_de_template_do_codigo():
    html = _renderizar('componentes/dialogo.html', id='d', titulo='T', corpo='componentes/vazio.html')
    assert 'class="ag-vazio"' in html


def test_dialogo_sem_corpo_fica_vazio_e_titulo_hostil_e_escapado():
    html = _renderizar('componentes/dialogo.html', id='d', titulo=HOSTIL)
    assert '<div class="ag-dialogo-corpo"></div>' in html
    assert HOSTIL not in html



def test_dentre_devolve_a_variante_conhecida():
    assert dentre('secundario', 'primario secundario fantasma perigo') == 'secundario'


def test_dentre_devolve_vazio_para_variante_desconhecida_e_para_valor_ausente():
    assert dentre('inventada', 'primario secundario') == ''
    assert dentre(None, 'primario secundario') == ''
    assert dentre(1, 'primario secundario') == ''  # não-texto nunca casa com a lista
    assert dentre('', 'primario secundario') == ''


def test_dentre_nao_casa_parte_de_palavra():
    # `in` sobre a string casaria "ai" dentro de "aviso"; a lista é por palavra.
    assert dentre('ai', 'erro aviso info sucesso') == ''


def test_selo_tom_e_rotulo_seguem_o_mapeamento_de_governanca():
    assert (selo_tom('em_analise'), selo_rotulo('em_analise')) == ('aviso', 'Em análise')
    assert (selo_tom('vigente'), selo_rotulo('vigente')) == ('sucesso', 'Vigente')
    assert (selo_tom('arquivada'), selo_rotulo('arquivada')) == ('neutro', 'Arquivada')


@pytest.mark.parametrize('situacao', ['desconhecida', '', None, 3])
def test_selo_situacao_desconhecida_ou_ausente_nao_inventa_tom(situacao):
    assert selo_tom(situacao) == ''
    assert selo_rotulo(situacao) == ''


def test_repetir_gera_as_linhas_do_esqueleto():
    assert list(repetir(3)) == [0, 1, 2]


@pytest.mark.parametrize('quantidade', [0, -1, 21, 10**9, '3', None, True, 2.0])
def test_repetir_recusa_quantidade_invalida_ou_hostil(quantidade):
    assert list(repetir(quantidade)) == []
