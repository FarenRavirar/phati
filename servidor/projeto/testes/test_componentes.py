"""Componentes base e travas de estilo (R13, R15; A12, A19): cada componente renderiza e o CSS segue os tokens."""

import re
from pathlib import Path

import pytest
from django.template.loader import render_to_string

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
    assert '<button class="botao" type="submit">Salvar</button>' in html
    assert 'botao-secundario' in _renderizar('componentes/botao.html', texto='x', secundario=True)
    assert ' disabled' in _renderizar('componentes/botao.html', texto='x', desabilitado=True)


def test_campo_liga_rotulo_e_erro_ao_controle():
    html = _renderizar('componentes/campo.html', id='cpf', nome='cpf', rotulo='CPF', erro='CPF ou senha incorretos.')
    assert '<label class="campo-rotulo" for="cpf">CPF</label>' in html
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
    assert '<select class="campo-controle" id="cargo" name="cargo"' in html
    assert '<option value="2" selected>&lt;b&gt;Técnico&lt;/b&gt;</option>' in html
    assert '<option value="1">Usuário</option>' in html
    assert 'aria-invalid="true"' in html
    assert 'aria-describedby="cargo-descricao"' in html
    assert '<input' not in html


def test_campo_caixas_agrupa_em_fieldset_com_legenda_e_marca_as_escolhidas():
    opcoes = [{'valor': 7, 'rotulo': 'Solo', 'marcada': True}, {'valor': 8, 'rotulo': 'Água', 'marcada': False}]
    html = _renderizar('componentes/campo.html', id='categorias', nome='categorias', rotulo='Categorias', tipo='caixas', opcoes=opcoes, ajuda='Só Técnico e Usuário.')
    assert '<fieldset' in html
    assert '<legend class="campo-rotulo">Categorias</legend>' in html
    assert '<input type="checkbox" name="categorias" value="7" checked>' in html
    assert '<input type="checkbox" name="categorias" value="8">' in html
    assert 'aria-describedby="categorias-descricao"' in html
    assert 'Só Técnico e Usuário.' in html


@pytest.mark.parametrize('tipo', ['erro', 'aviso', 'info', 'sucesso'])
def test_aviso_tem_cor_icone_e_texto(tipo):
    html = _renderizar('componentes/aviso.html', tipo=tipo, texto='Texto do aviso')
    assert f'aviso-{tipo}' in html
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
    assert 'class="tabela-rolavel"' in html
    assert '<th scope="col">Nome</th>' in html
    assert '<td>F2</td>' in html


def test_vazio_so_mostra_a_acao_quando_a_view_a_passa():
    assert '<a ' not in _renderizar('componentes/vazio.html', texto='Sem sub-áreas.')
    com = _renderizar('componentes/vazio.html', texto='Sem sub-áreas.', acao_rotulo='Cadastrar', acao_destino='/x/')
    assert '<a class="botao" href="/x/">Cadastrar</a>' in com
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


def test_atributo_hidden_vence_o_display_de_qualquer_componente():
    # O botão do menu nasce `hidden` e o `.botao` é `inline-flex`: sem a regra, o botão apareceria em tela larga.
    assert 'html [hidden] { display: none; }' in (ESTATICOS / 'base.css').read_text(encoding='utf-8')


def _ofensores_de_especificidade(texto):
    """Seletores com `display` e mais de uma classe, atributo ou pseudo, exceto as regras `html <seletor>[hidden]`."""
    achados = []
    for seletor, corpo in re.findall(r'([^{}]+)\{([^{}]*)\}', re.sub(r'/\*.*?\*/', '', texto, flags=re.S)):
        if re.search(r'(^|;|\s)display\s*:', corpo):
            for parte in seletor.split(','):
                parte = parte.strip()
                if re.fullmatch(r'html .+\[hidden\]', parte):
                    continue
                if len(re.findall(r'[.#\[:]', re.sub(r'::?(where|is)\(', '', parte))) > 1:
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


def test_campo_com_teclado_leva_inputmode_e_sem_corretor():
    html = _renderizar('componentes/campo.html', id='cpf', nome='cpf', rotulo='CPF', teclado='numeric')
    assert 'inputmode="numeric" spellcheck="false"' in html
    assert 'inputmode' not in _renderizar('componentes/campo.html', id='cpf', nome='cpf', rotulo='CPF')


def _declaracoes(seletor):
    css = (ESTATICOS / 'componentes.css').read_text(encoding='utf-8')
    achado = re.search(rf'(?m)^{re.escape(seletor)}\s*\{{([^}}]*)\}}', css)
    assert achado is not None, seletor
    return achado.group(1)


def test_arvore_e_lista_de_fazendas_em_grade_e_a_aninhada_leva_recuo_e_linha_guia():
    # Sem o recuo e a linha, a árvore de 3 níveis vira uma lista plana (R11); a estrutura HTML sozinha não pega isso.
    assert 'display: grid' in _declaracoes('.lista-fazendas, .lista-atalhos, .arvore')
    aninhada = _declaracoes('.arvore .arvore')
    for declaracao in ('margin:', 'padding-left:', 'border-left:'):
        assert declaracao in aninhada

