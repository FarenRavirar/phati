from pathlib import Path

from django.conf import settings

RAIZ = Path(settings.DIRETORIO_BASE)
DOCKERFILE_APP = (RAIZ / 'Dockerfile').read_text(encoding='utf-8')


def test_banco_usa_o_backend_postgis_do_geodjango():
    # D114 (b): GeoDjango exige o backend PostGIS; o backend comum do PostgreSQL não reconhece campos geométricos.
    assert settings.DATABASES['default']['ENGINE'] == 'django.contrib.gis.db.backends.postgis'
    assert settings.DATABASES['app']['ENGINE'] == 'django.contrib.gis.db.backends.postgis'


def test_django_contrib_gis_esta_instalado():
    assert 'django.contrib.gis' in settings.INSTALLED_APPS


def test_imagem_do_app_traz_gdal_geos_proj_do_sistema_e_rede_do_proj_desligada():
    # D114 (b) e D114 (rede): bibliotecas de sistema na imagem do app; PROJ sem rede por configuração explícita.
    assert 'libgdal36' in DOCKERFILE_APP
    assert 'libgeos-c1t64' in DOCKERFILE_APP
    assert 'libproj25' in DOCKERFILE_APP
    assert 'PROJ_NETWORK=OFF' in DOCKERFILE_APP
