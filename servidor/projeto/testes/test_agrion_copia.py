"""Cópia do pacote AgriOn em static/projeto/agrion/ (T1.3, spec 012, R1 a R5).

O CI não lê o pacote de design (repo privado). Por isso a igualdade com o pacote é a igualdade, arquivo a arquivo,
com o hash gravado em `agrion_manifesto.sha256` (origem descrita no cabeçalho do manifesto).
"""

import hashlib
import re
import shutil
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ESTATICOS = RAIZ / 'static' / 'projeto'
AGRION = ESTATICOS / 'agrion'
TEMPLATES = RAIZ / 'templates'
MANIFESTO = Path(__file__).resolve().parent / 'agrion_manifesto.sha256'


def _manifesto(caminho=MANIFESTO):
    entradas = {}
    for linha in caminho.read_text(encoding='utf-8').splitlines():
        if linha and not linha.startswith('#'):
            digest, _, relativo = linha.partition('  ')
            entradas[relativo] = digest
    return entradas


def _sha256(arquivo):
    return hashlib.sha256(arquivo.read_bytes()).hexdigest()


def divergencias(raiz, manifesto):
    """Lista o que difere da árvore em `raiz`: alterado, falta ou sobra, em relação ao manifesto."""
    presentes = {p.relative_to(raiz).as_posix(): p for p in raiz.rglob('*') if p.is_file()}
    achados = []
    for relativo, digest in manifesto.items():
        if relativo not in presentes:
            achados.append(f'falta: {relativo}')
        elif _sha256(presentes[relativo]) != digest:
            achados.append(f'alterado: {relativo}')
    achados += [f'sobra: {relativo}' for relativo in presentes if relativo not in manifesto]
    return achados


def integros_do_pacote():
    """Arquivos de agrion/ cujo hash confere: só estes ficam isentos de cor literal e de !important (R2, R13)."""
    manifesto = _manifesto()
    return {
        AGRION / relativo
        for relativo, digest in manifesto.items()
        if (AGRION / relativo).is_file() and _sha256(AGRION / relativo) == digest
    }


def test_copia_bate_com_o_manifesto_arquivo_a_arquivo():
    assert divergencias(AGRION, _manifesto()) == []


def test_tokens_copiados_sao_exatamente_os_tres_do_pacote():
    tokens = sorted(r for r in _manifesto() if r.startswith('tokens/'))
    assert tokens == ['tokens/colors.css', 'tokens/spacing.css', 'tokens/typography.css']
    # fonts.css e styles.css do pacote importam Google Fonts e não entram (R1).
    assert 'tokens/fonts.css' not in _manifesto()
    assert 'styles.css' not in _manifesto()


def test_estilos_e_kit_copiados_sao_os_listados():
    estilos = sorted(r for r in _manifesto() if r.startswith('styles/') or r.startswith('ui_kits/'))
    assert estilos == ['styles/base.css', 'styles/casca.css', 'styles/componentes.css', 'styles/mapa.css', 'ui_kits/web/kit.css']


def test_fontes_icones_e_logos_sao_os_usados():
    manifesto = _manifesto()
    assert sorted(r for r in manifesto if r.startswith('fontes/')) == sorted(
        [f'fontes/Geist-{n}.woff2' for n in ('Bold', 'Medium', 'Regular', 'SemiBold')]
        + ['fontes/GeistMono-Medium.woff2', 'fontes/GeistMono-Regular.woff2', 'fontes/LICENSE-geist.txt']
    )
    icones = [r for r in manifesto if r.startswith('icones/') and r.endswith('.svg')]
    assert len(icones) == 43  # lista de telas.md §8
    assert sorted(r for r in manifesto if r.startswith('logo/')) == [
        'logo/agrion-horizontal.svg', 'logo/agrion-simbolo-branco.svg', 'logo/agrion-simbolo.svg',
    ]


def test_arquivo_alterado_em_um_byte_falha(tmp_path):
    copia = tmp_path / 'agrion'
    shutil.copytree(AGRION, copia)
    alvo = copia / 'tokens' / 'colors.css'
    dados = bytearray(alvo.read_bytes())
    dados[0] ^= 0x01
    alvo.write_bytes(bytes(dados))
    assert divergencias(copia, _manifesto()) == ['alterado: tokens/colors.css']


def test_arquivo_faltando_falha(tmp_path):
    copia = tmp_path / 'agrion'
    shutil.copytree(AGRION, copia)
    (copia / 'icones' / 'x.svg').unlink()
    assert divergencias(copia, _manifesto()) == ['falta: icones/x.svg']


def test_arquivo_sobrando_falha(tmp_path):
    copia = tmp_path / 'agrion'
    shutil.copytree(AGRION, copia)
    (copia / 'icones' / 'extra.svg').write_text('<svg/>', encoding='utf-8')
    assert divergencias(copia, _manifesto()) == ['sobra: icones/extra.svg']


URL_EM_CSS = re.compile(r'@import|url\(\s*[\'"]?\s*(https?:)?//|url\(\s*[\'"]?https?:', re.IGNORECASE)
URL_EM_SVG = re.compile(r'\b(href|src)\s*=\s*["\']\s*(https?:)?//|url\(\s*[\'"]?https?:', re.IGNORECASE)
URL_EM_HTML = re.compile(r'<(link|script|img|iframe|source)\b[^>]*\b(href|src)\s*=\s*["\']\s*(https?:)?//', re.IGNORECASE)


def _alvos_de_fonte_ou_cdn():
    css = [p for p in [*ESTATICOS.glob('*.css'), *AGRION.rglob('*.css')]]
    svg = list(AGRION.rglob('*.svg'))
    html = list(TEMPLATES.rglob('*.html'))
    return css, svg, html


def test_nenhuma_url_externa_de_fonte_ou_cdn():
    css, svg, html = _alvos_de_fonte_ou_cdn()
    assert [p.name for p in css if URL_EM_CSS.search(p.read_text(encoding='utf-8'))] == []
    # xmlns de SVG (namespace, não requisição) fica de fora; só href, src e url() contam.
    assert [p.name for p in svg if URL_EM_SVG.search(p.read_text(encoding='utf-8'))] == []
    assert [p.name for p in html if URL_EM_HTML.search(p.read_text(encoding='utf-8'))] == []


def test_detector_de_url_externa_pega_fonte_de_cdn_e_nao_pega_xmlns():
    assert URL_EM_CSS.search("@import url('https://fonts.googleapis.com/css2?family=Geist');")
    assert URL_EM_CSS.search("@font-face { src: url(https://cdn.exemplo.org/a.woff2) }")
    assert URL_EM_HTML.search('<link rel="stylesheet" href="https://cdn.exemplo.org/x.css">')
    assert URL_EM_SVG.search('<image href="https://exemplo.org/a.png"/>')
    assert not URL_EM_SVG.search('<svg xmlns:c2pa="http://c2pa.org/manifest"></svg>')
    assert not URL_EM_CSS.search('.x { background: url(agrion/logo/a.svg); }')


def test_fontes_locais_existem_no_disco():
    css = (ESTATICOS / 'fontes.css').read_text(encoding='utf-8')
    alvos = re.findall(r'url\("([^"]+)"\)', css)
    assert len(alvos) == 6
    assert [a for a in alvos if not (ESTATICOS / a).is_file()] == []
    assert 'Geist Mono' in css
    assert 'Geist' in css
    assert not URL_EM_CSS.search(css)
