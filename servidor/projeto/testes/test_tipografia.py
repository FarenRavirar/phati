"""Escala tipográfica (003 R3, A3; spec 012 T1.4): `h1` e `h2` distinguíveis, medidos nos tokens do pacote AgriOn."""

import re
from pathlib import Path

VARIAVEIS = Path(__file__).resolve().parent.parent / 'static' / 'projeto' / 'agrion' / 'tokens' / 'typography.css'
RAZAO_ANTERIOR = 1.5 / 1.25  # 1,5rem por 1,25rem, medido na 002


def _razao(css):
    def tamanho(nome):
        return float(re.findall(rf'--texto-{nome}:\s*([0-9.]+)rem', css)[0])

    # h1 é `--texto-2xl` (24 px) e h2 é `--texto-lg` (18 px), como em agrion/styles/base.css.
    return tamanho('2xl') / tamanho('lg')


def test_h1_e_h2_tem_razao_maior_que_a_anterior():
    assert _razao(VARIAVEIS.read_text(encoding='utf-8')) > RAZAO_ANTERIOR


def test_o_teste_reprova_os_valores_antigos():
    antigo = '--texto-2xl: 1.25rem; --texto-lg: 1.125rem;'
    assert not _razao(antigo) > RAZAO_ANTERIOR
