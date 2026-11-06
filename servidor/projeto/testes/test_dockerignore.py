"""`.dockerignore` (review da PR #52, Greptile P1): o Dockerfile faz `COPY . .`, então segredo no contexto vira camada da imagem."""

from pathlib import Path

DOCKERIGNORE = Path(__file__).resolve().parents[2] / '.dockerignore'


def _linhas():
    """Entradas do `.dockerignore`, sem comentário nem linha vazia."""
    return [linha.strip() for linha in DOCKERIGNORE.read_text(encoding='utf-8').splitlines() if linha.strip() and not linha.startswith('#')]


def test_pasta_de_segredos_fica_fora_do_contexto_de_build():
    assert 'segredos' in _linhas()
    assert '**/segredos' in _linhas()


def test_env_continua_fora_do_contexto_de_build():
    assert '.env' in _linhas()


def test_o_volume_de_segredos_do_compose_aponta_para_a_pasta_ignorada():
    compose = (DOCKERIGNORE.parent / 'compose.yaml').read_text(encoding='utf-8')
    assert '${PHATI_SEGREDOS_DIR:-./segredos}:/segredos:ro' in compose
