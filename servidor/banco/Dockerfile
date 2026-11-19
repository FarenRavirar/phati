# Imagem do banco (D048): PostgreSQL 18 oficial, fixado por digest multi-arquitetura (amd64 e arm64), mais PostGIS 3.6.4
# do repositório PGDG, versão fixada. A imagem `postgis/postgis` publica só amd64 e a VM é arm64 (spec 006).
FROM postgres:18@sha256:e754b839f447639b7004895f4d8a4bfcb4e9dbe3a1bc035f27f646562a16fd61
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-18-postgis-3=3.6.4+dfsg-2.pgdg13+1 \
        postgresql-18-postgis-3-scripts=3.6.4+dfsg-2.pgdg13+1 \
    && rm -rf /var/lib/apt/lists/*
# Roda só na criação do volume: `template1` ganha o PostGIS, e todo banco criado depois herda a extensão (inclusive o de teste do Django).
COPY criar-postgis.sh /docker-entrypoint-initdb.d/00-criar-postgis.sh
