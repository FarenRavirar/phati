"""PMTiles embutido (004b R7, T0.4): versão exata, hash fixo aqui dentro e nenhum endereço de rede carregado em execução.

O hash mora neste arquivo, não em outro texto que se edite junto (mesmo critério de `test_maplibre_terceiros.py`).
Pacote `pmtiles@4.5.0` (BSD-3-Clause), `dist/pmtiles.js` com a fflate embutida; a integridade do tarball está em `ORIGEM.txt`.
"""

import hashlib
import re
from pathlib import Path

PASTA = Path(__file__).resolve().parents[1] / 'static' / 'projeto' / 'terceiros' / 'pmtiles'
SHA256 = 'caf981bc46f6327ee7e65d5dc964d89d38a69f60edca2bd4c5c890c21b554c6c'


def _sha256(conteudo):
    return hashlib.sha256(conteudo).hexdigest()


def test_arquivo_embutido_tem_o_hash_fixado():
    assert _sha256((PASTA / 'pmtiles.js').read_bytes()) == SHA256


def test_alterar_um_byte_muda_o_hash():
    assert _sha256((PASTA / 'pmtiles.js').read_bytes() + b' ') != SHA256


def test_a_pasta_so_tem_o_script_e_a_origem():
    assert {p.name for p in PASTA.iterdir()} == {'pmtiles.js', 'ORIGEM.txt'}


def test_o_unico_endereco_literal_e_o_link_de_documentacao():
    texto = (PASTA / 'pmtiles.js').read_text(encoding='utf-8')
    achados = {a.rstrip('`.,;') for a in re.findall(r"https?://[^\"'\s)\`]+", texto)}
    assert achados == {'https://github.com/protomaps/PMTiles/tree/main/js'}
