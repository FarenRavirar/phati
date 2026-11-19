import re
from pathlib import Path

from django.conf import settings

RAIZ = Path(settings.DIRETORIO_BASE)
COMPOSE = (RAIZ / 'compose.yaml').read_text(encoding='utf-8')
DOCKERFILE = (RAIZ / 'banco' / 'Dockerfile').read_text(encoding='utf-8')
SCRIPT = (RAIZ / 'banco' / 'criar-postgis.sh').read_text(encoding='utf-8')
CI = (RAIZ.parent / '.github' / 'workflows' / 'ci.yml').read_text(encoding='utf-8')


def test_compose_constroi_o_banco_pela_imagem_propria():
    # D048 e D114 (a): o serviço banco é build do Dockerfile do repositório, não imagem de terceiro.
    assert 'build: ./banco' in COMPOSE
    assert 'postgis/postgis' not in COMPOSE


def test_dockerfile_fixa_postgres_por_digest_e_postgis_por_versao():
    assert re.search(r'^FROM postgres:18@sha256:[0-9a-f]{64}$', DOCKERFILE, re.M)
    assert 'postgresql-18-postgis-3=3.6.4+dfsg-2.pgdg13+1' in DOCKERFILE
    # Sem o pacote de scripts fixado, o apt puxa a versão 3.7 e a extensão recusa a biblioteca 3.6 (medido em 2026-11-19).
    assert 'postgresql-18-postgis-3-scripts=3.6.4+dfsg-2.pgdg13+1' in DOCKERFILE


def test_script_cria_postgis_em_template1_e_roda_no_init():
    # Bancos criados depois herdam a extensão de template1; o papel da aplicação não precisa de superusuário.
    assert 'COPY criar-postgis.sh /docker-entrypoint-initdb.d/' in DOCKERFILE
    assert '-d template1' in SCRIPT
    assert 'CREATE EXTENSION IF NOT EXISTS postgis;' in SCRIPT


def test_ci_nao_usa_imagem_de_terceiro_para_o_banco():
    assert 'postgres:18@sha256' not in CI
    assert 'docker build -t phati-banco-ci banco' in CI


def test_ci_instala_gdal_geos_proj_do_sistema_para_geodjango():
    # D114 (b): GeoDjango precisa das mesmas bibliotecas de sistema que a imagem do app.
    assert 'libgdal34t64 libgeos-c1t64 libproj25' in CI
