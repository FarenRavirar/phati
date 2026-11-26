"""Classes próprias que os templates usam precisam de regra CSS (regressão da casca, spec 012).

A reescrita da casca tirou do CSS `.publica*`, `.convite*`, `.lista-convites` e `.rodape-termos`, e os templates continuaram
usando essas classes. A lista é das classes que o `origin/dev` estilizava e que os templates ainda usam.
"""

import re
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
CLASSES_PROPRIAS = (
    'publica', 'publica-caixa', 'publica-produto', 'convite', 'convite-titulo', 'convite-detalhe', 'convite-acoes',
    'lista-convites', 'rodape-termos',
)


def _usa(marcacao, classe):
    return re.search(rf'class="[^"]*(?<![\w-]){re.escape(classe)}(?![\w-])[^"]*"', marcacao) is not None


def _tem_regra(css, classe):
    return re.search(rf'\.{re.escape(classe)}(?![\w-])', css) is not None


def sem_regra(marcacao, css):
    """Classes da lista que o template usa e o CSS não estiliza."""
    return [classe for classe in CLASSES_PROPRIAS if _usa(marcacao, classe) and not _tem_regra(css, classe)]


def _marcacao():
    return '\n'.join(p.read_text(encoding='utf-8') for p in (RAIZ / 'templates').rglob('*.html'))


def _css():
    return '\n'.join(p.read_text(encoding='utf-8') for p in (RAIZ / 'static').rglob('*.css'))


@pytest.mark.parametrize('classe', CLASSES_PROPRIAS)
def test_classe_propria_usada_em_template_tem_regra_css(classe):
    assert classe not in sem_regra(_marcacao(), _css())


def test_uso_sem_regra_e_reprovado():
    assert sem_regra('<p class="convite-titulo">x</p>', '.outra { color: red; }') == ['convite-titulo']


def test_nome_parecido_na_regra_nao_conta_como_regra():
    # `.convite-titulo` não estiliza `.convite`: a regra precisa ser da classe exata.
    assert sem_regra('<li class="convite">', '.convite-titulo { margin: 0; }') == ['convite']


def test_classe_fora_da_lista_ou_sem_uso_nao_reprova():
    assert sem_regra('<p class="outro">x</p>', '') == []
    assert sem_regra('<p class="convite-titulo">x</p>', '.convite-titulo { margin: 0; }') == []
