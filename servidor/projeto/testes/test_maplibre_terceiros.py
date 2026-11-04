"""MapLibre embutido (004 R2, A2): versão exata, hash fixo aqui dentro e nenhum endereço de rede além dos que a T1.3 registrou.

O hash mora neste arquivo, não em outro texto que se edite junto: um teste que lê o hash do mesmo arquivo que se altera
passaria sempre. Pacote `maplibre-gl@6.16.0` (BSD-3-Clause), integridade conferida com `npm view` na T0.3.
"""

import hashlib
import re
from pathlib import Path

import pytest

PASTA = Path(__file__).resolve().parents[1] / 'static' / 'projeto' / 'terceiros' / 'maplibre'
SHA256 = {
    'LICENSE.txt': 'ee5fc05a0677eaf69601d2c7db0d9ecd6cc27c3abc1d0733bc9ed34707cf8ef2',
    'maplibre-gl.css': 'a90798a1953017790e590f7e1bd35ff103a8a4263972cb47290b78adf86f8c20',
    'maplibre-gl.mjs': 'fbbdf8ddd9a48e49059a4be6795a4f214a711314bb5809f72d3730b48e7897e3',
    'maplibre-gl-worker.mjs': '0bf06492bdb7ba3d4132b78e435621bfba60d5250967991c02b1a73affea8cd5',
}
# Endereços literais dentro dos arquivos (T1.3): namespaces XML, links de erro e de licença, nenhum carregado em execução.
ENDERECOS_ESPERADOS = {
    'maplibre-gl.mjs': {
        'http://www.w3.org/1999/xhtml', 'http://www.w3.org/2000/svg',
        'https://github.com/mapbox/mapbox-gl-js/issues/2907', 'https://github.com/maplibre/maplibre-gl-js/blob/v6.16.0/LICENSE.txt',
        'https://maplibre.invalid/', 'https://maplibre.org/', 'https://wiki.openstreetmap.org/wiki/This_map_requires_WebGL',
    },
    'maplibre-gl-worker.mjs': {
        'https://github.com/mapbox/mapbox-gl-js/issues/2907', 'https://github.com/maplibre/maplibre-gl-js/blob/v6.16.0/LICENSE.txt',
    },
    'maplibre-gl.css': {'http://www.w3.org/2000/svg'},
}


def _sha256(conteudo):
    return hashlib.sha256(conteudo).hexdigest()


@pytest.mark.parametrize('nome', sorted(SHA256))
def test_arquivo_embutido_tem_o_hash_fixado(nome):
    assert _sha256((PASTA / nome).read_bytes()) == SHA256[nome]


def test_alterar_um_byte_muda_o_hash():
    # Prova de que a comparação detecta adulteração: o mesmo conteúdo com um byte a mais não tem o hash fixado.
    original = (PASTA / 'maplibre-gl.css').read_bytes()
    assert _sha256(original + b' ') != SHA256['maplibre-gl.css']


def test_a_pasta_so_tem_os_quatro_arquivos_fixados():
    assert {p.name for p in PASTA.iterdir()} == set(SHA256)


@pytest.mark.parametrize('nome', sorted(ENDERECOS_ESPERADOS))
def test_enderecos_literais_sao_so_os_registrados(nome):
    texto = (PASTA / nome).read_text(encoding='utf-8')
    achados = {a.rstrip('`.,;') for a in re.findall(r"https?://[^\"'\s)\\`]+", texto)}
    assert achados == ENDERECOS_ESPERADOS[nome]
