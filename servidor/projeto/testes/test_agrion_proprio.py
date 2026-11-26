"""CSS próprio da AgriOn e ligação dos moldes (spec 012, T1.4; R1, R11, R12, R13).

O pacote copiado em agrion/ não traz o alvo de 44 px, a troca do texto terciário nem a proteção de movimento que o
protótipo põe em estilo inline; isso mora em `agrion-proprio.css`, carregado por último pelos moldes.
"""

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ESTATICOS = RAIZ / 'static' / 'projeto'
AGRION = ESTATICOS / 'agrion'
PROPRIO = ESTATICOS / 'agrion-proprio.css'
TEMPLATES = RAIZ / 'templates'


def _sem_comentarios(texto):
    return re.sub(r'/\*.*?\*/', '', texto, flags=re.S)


def _regras(texto):
    """Pares (seletor, corpo) sem comentário. A regra dentro de `@media` sai do mesmo jeito."""
    return re.findall(r'([^{}]+)\{([^{}]*)\}', _sem_comentarios(texto))


def _corpo(texto, seletor):
    """Corpo da regra cujo seletor (uma das partes separadas por vírgula) é `seletor`; None se não existe."""
    for sel, corpo in _regras(texto):
        if seletor in [parte.strip() for parte in sel.split(',')]:
            return corpo
    return None


def _bloco(texto, condicao):
    """Conteúdo de `@media <condicao> { ... }`; None se o bloco não existe."""
    achado = re.search(rf'@media\s*{re.escape(condicao)}\s*\{{((?:[^{{}}]*\{{[^{{}}]*\}})*)\s*\}}', _sem_comentarios(texto))
    return achado.group(1) if achado else None


def _hrefs(texto):
    return re.findall(r"static '(projeto/[^']+\.css)'", texto)


def _alvo_de_44(texto):
    """Botão e campo com 44 px (`--controle-lg`) abaixo de 64rem, e os mesmos nas telas públicas."""
    media = _bloco(texto, '(max-width: 64rem)') or ''
    return all('var(--controle-lg)' in (corpo or '') for corpo in (
        _corpo(media, '.ag-botao'),
        _corpo(media, '.ag-controle'),
        _corpo(texto, '.ag-publica .ag-botao'),
        _corpo(texto, '.ag-publica .ag-controle'),
    ))


def _alvo_de_24_no_desktop(texto):
    """Link de atalho inline-flex com 24 px (`1.5rem`) fora de `@media`: a regra da tela larga, não a da estreita."""
    return re.search(r'\.lista-atalhos a \{[^}]*display:\s*inline-flex[^}]*min-height:\s*1\.5rem', _sem_comentarios(texto)) is not None


def _sem_sobreposicao_estreita(texto):
    """Em tela estreita: camadas na base (40%), ficha abaixo do seletor de fundo e zoom acima do painel."""
    estreita = _bloco(texto, '(max-width: 48rem)') or ''
    return (
        'max-height: 40%' in (_corpo(estreita, '.ag-camadas') or '')
        and 'bottom: 0' in (_corpo(estreita, '.ag-camadas') or '')
        and 'top: calc(var(--espaco-12) + var(--espaco-3))' in (_corpo(estreita, '.ag-ficha-flutuante') or '')
        and 'bottom: calc(40% + var(--espaco-3))' in (_corpo(estreita, '.ag-mapa-zoom') or '')
    )


COR_LITERAL = re.compile(r'#[0-9A-Fa-f]{3,8}\b|\b(rgb|rgba|hsl|hsla)\(')
MOVIMENTO = re.compile(r'\b(transition|animation)\s*:')
PREFERENCIA = r'@media[^{]*prefers-reduced-motion:\s*no-preference[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}'


def _violacoes_de_estilo(texto):
    """Cor literal, `!important` e movimento fora de `no-preference` num CSS próprio."""
    limpo = _sem_comentarios(texto)
    achados = []
    if COR_LITERAL.search(limpo):
        achados.append('cor literal')
    if '!important' in limpo:
        achados.append('!important')
    if MOVIMENTO.search(re.sub(PREFERENCIA, '', limpo)):
        achados.append('movimento fora de no-preference')
    return achados


def _variaveis_sem_definicao(textos_usados, textos_todos):
    definidas = {nome for texto in textos_todos for nome in re.findall(r'(--[A-Za-z0-9-]+)\s*:', _sem_comentarios(texto))}
    usadas = {nome for texto in textos_usados for nome in re.findall(r'var\((--[A-Za-z0-9-]+)\)', _sem_comentarios(texto))}
    return sorted(usadas - definidas)


def _css_do_projeto():
    return sorted(p for p in ESTATICOS.rglob('*.css') if 'terceiros' not in p.relative_to(ESTATICOS).parts)


def _integros():
    from projeto.testes.test_agrion_copia import integros_do_pacote

    return integros_do_pacote()


def test_css_proprio_existe_e_o_tokens_antigo_saiu():
    assert PROPRIO.is_file()
    assert not (ESTATICOS / 'tokens.css').exists()
    for molde in ('casca.html', 'publica.html'):
        assert 'projeto/tokens.css' not in _hrefs((TEMPLATES / molde).read_text(encoding='utf-8'))


def test_nenhuma_variavel_usada_fica_sem_definicao():
    # Nome antigo (`--cor-primaria`, `--fonte-titulo-1`) sobrando num arquivo nosso quebraria o estilo sem erro visível.
    integros = _integros()
    todos = [p.read_text(encoding='utf-8') for p in _css_do_projeto()]
    usados = [p.read_text(encoding='utf-8') for p in _css_do_projeto() if p not in integros]
    assert _variaveis_sem_definicao(usados, todos) == []


def test_o_teste_de_variavel_reprova_nome_antigo_sem_definicao():
    assert _variaveis_sem_definicao(['.x { color: var(--cor-primaria); }'], [':root { --acao-primaria: #1B5E3C; }']) == ['--cor-primaria']


def test_moldes_carregam_pacote_fontes_e_o_proprio_por_ultimo():
    for molde in ('casca.html', 'publica.html'):
        hrefs = _hrefs((TEMPLATES / molde).read_text(encoding='utf-8'))
        assert hrefs[-1] == 'projeto/agrion-proprio.css', molde
        assert hrefs.index('projeto/agrion/tokens/colors.css') < hrefs.index('projeto/base.css'), molde
        assert hrefs.index('projeto/fontes.css') < hrefs.index('projeto/base.css'), molde


def test_casca_carrega_toda_copia_do_pacote():
    hrefs = set(_hrefs((TEMPLATES / 'casca.html').read_text(encoding='utf-8')))
    copias = {f'projeto/{p.relative_to(ESTATICOS).as_posix()}' for p in AGRION.rglob('*.css')}
    assert copias
    assert copias <= hrefs, sorted(copias - hrefs)


def test_o_teste_de_ordem_reprova_proprio_antes_do_pacote():
    # Medido no mesmo caminho dos moldes: com o próprio antes do base, a ordem da regra falha.
    ordem_certa = _hrefs("{% static 'projeto/base.css' %}{% static 'projeto/agrion-proprio.css' %}")
    ordem_errada = _hrefs("{% static 'projeto/agrion-proprio.css' %}{% static 'projeto/base.css' %}")
    assert ordem_certa[-1] == 'projeto/agrion-proprio.css'
    assert ordem_errada[-1] != 'projeto/agrion-proprio.css'


def test_css_proprio_sem_cor_literal_important_nem_movimento_solto():
    assert _violacoes_de_estilo(PROPRIO.read_text(encoding='utf-8')) == []


def test_o_teste_de_estilo_reprova_cor_important_e_movimento_solto():
    assert _violacoes_de_estilo('.x { color: #fff !important; }') == ['cor literal', '!important']
    assert _violacoes_de_estilo('.x { transition: all 1s; }') == ['movimento fora de no-preference']
    assert _violacoes_de_estilo('@media (prefers-reduced-motion: no-preference) { .x { transition: all 1s; } }') == []


def test_html_hidden_e_links_sublinhados():
    texto = PROPRIO.read_text(encoding='utf-8')
    assert 'html [hidden] { display: none; }' in texto
    assert 'text-decoration: underline' in (_corpo(texto, 'a') or '')
    sem_sublinhado = _corpo('a { color: red; }', 'a')
    assert sem_sublinhado is not None
    assert 'underline' not in sem_sublinhado


def test_meta_da_arvore_troca_para_o_texto_secundario_no_hover_e_no_selecionado():
    texto = PROPRIO.read_text(encoding='utf-8')
    for seletor in ('.ag-arvore-no:hover .ag-arvore-meta', '.ag-arvore-no[aria-current="true"] .ag-arvore-meta'):
        assert 'color: var(--texto-secundario)' in (_corpo(texto, seletor) or ''), seletor
    assert _corpo('.x { }', '.ag-arvore-meta') is None


def test_alvo_de_44_px_abaixo_de_64rem_e_nas_telas_publicas():
    assert _alvo_de_44(PROPRIO.read_text(encoding='utf-8'))
    assert not _alvo_de_44('@media (max-width: 64rem) { .ag-botao { --h: 36px; } .ag-controle { height: 36px; } }')


def test_link_de_atalho_e_alvo_de_24_px_e_44_abaixo_de_64rem():
    # Link inline não tem altura de alvo: com 14 px de corpo a medição deu 113x18 e axe reprovou (target-size).
    texto = PROPRIO.read_text(encoding='utf-8')
    assert _alvo_de_24_no_desktop(texto)
    assert 'var(--controle-lg)' in (_corpo(_bloco(texto, '(max-width: 64rem)') or '', '.lista-atalhos a') or '')
    # Ordem: a regra de 24 px vem antes do @media; depois dele venceria a de 44 px só na tela larga (regra de cascata).
    limpo = _sem_comentarios(texto)
    assert limpo.index('.lista-atalhos a {') < limpo.index('@media (max-width: 64rem)')
    # Caso negativo: link inline sem altura mínima, como estava antes da correção, reprova.
    assert not _alvo_de_24_no_desktop('.lista-atalhos a { display: inline; }')


def test_mapa_sem_sobreposicao_em_tela_estreita():
    assert _sem_sobreposicao_estreita(PROPRIO.read_text(encoding='utf-8'))
    assert not _sem_sobreposicao_estreita('@media (max-width: 48rem) { .ag-camadas { bottom: 0; } }')


def test_pacote_zera_movimento_com_reduced_motion():
    # Cópia íntegra: o movimento dela é coberto aqui, por isso test_componentes não a cobra no no-preference.
    def zera(texto):
        return re.search(r'@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{[^}]*animation-duration[^}]*transition-duration', texto) is not None

    assert zera((AGRION / 'styles' / 'base.css').read_text(encoding='utf-8'))
    assert not zera('.x { transition: all 1s; }')
