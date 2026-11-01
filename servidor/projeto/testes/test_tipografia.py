"""Escala tipográfica (003 R3, A3): `h1` e `h2` distinguíveis, medidos nos tokens."""

import re
from pathlib import Path

VARIAVEIS = Path(__file__).resolve().parent.parent / 'static' / 'projeto' / 'tokens.css'
RAZAO_ANTERIOR = 24 / 20  # 1,5rem por 1,25rem, medido na 002


def _razao(css):
    def tamanho(nome):
        return float(re.findall(rf'--fonte-titulo-{nome}:\s*([0-9.]+)rem', css)[0])

    return tamanho(1) / tamanho(2)


def test_h1_e_h2_tem_razao_maior_que_a_anterior():
    assert _razao(VARIAVEIS.read_text(encoding='utf-8')) > RAZAO_ANTERIOR


def test_o_teste_reprova_os_valores_antigos():
    antigo = '--fonte-titulo-2: 1.25rem; --fonte-titulo-1: 1.5rem;'
    assert not _razao(antigo) > RAZAO_ANTERIOR
