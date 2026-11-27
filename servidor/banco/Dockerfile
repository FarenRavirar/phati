# Imagem do banco (D048): PostgreSQL 18 oficial, fixado por digest multi-arquitetura (amd64 e arm64), mais PostGIS
# do repositório PGDG, versão fixada. A imagem `postgis/postgis` publica só amd64 e a VM é arm64 (spec 006).
FROM postgres:18@sha256:e754b839f447639b7004895f4d8a4bfcb4e9dbe3a1bc035f27f646562a16fd61
# Versão do PostGIS: ÚNICO lugar a mudar. compose.yaml, ci.yml e os scripts não repetem o número.
ARG POSTGIS_VERSAO=3.7.0+dfsg-2.pgdg13+1
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-18-postgis-3="${POSTGIS_VERSAO}" \
        postgresql-18-postgis-3-scripts="${POSTGIS_VERSAO}" \
    && rm -rf /var/lib/apt/lists/*
# Roda só na criação do volume: `template1` ganha o PostGIS, e todo banco criado depois herda a extensão (inclusive o de teste do Django).
COPY criar-postgis.sh /docker-entrypoint-initdb.d/00-criar-postgis.sh
# Não rodar como root: o apt-get acima é a única parte que precisa dele. Medido: volume novo em /var/lib/postgresql nasce
# postgres:postgres e o PGDATA (/var/lib/postgresql/18/docker) é criado pelo próprio postgres.
USER postgres
