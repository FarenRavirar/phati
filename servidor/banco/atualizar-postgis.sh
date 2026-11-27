#!/bin/sh
# Garante o PostGIS em volume que já existia: o init da imagem só roda em volume vazio. Roda como superusuário, no serviço
# `banco_extensoes` do compose e antes de parar o app na implantação (scripts/implantar.sh). Idempotente: CREATE EXTENSION IF NOT EXISTS
# e postgis_extensions_upgrade() (PostGIS da imagem, versão em POSTGIS_VERSAO no servidor/banco/Dockerfile: extensão de versão antiga em volume existente vira a versão da biblioteca).
# Conexão por PGHOST, PGUSER e PGPASSWORD do ambiente; o banco da aplicação vem de PHATI_BANCO_NOME (padrão phati).
set -eu
banco="${PHATI_BANCO_NOME:-phati}"
# template1 primeiro: bancos criados depois herdam a extensão; depois o banco da aplicação, que já pode existir.
for base in template1 "$banco"; do
  psql -v ON_ERROR_STOP=1 -X -d "$base" -c 'CREATE EXTENSION IF NOT EXISTS postgis;'
  # Depois do CREATE, porque o upgrade só age sobre extensão que existe na base. Notas da release do PostGIS: https://postgis.net/docs/release_notes.html .
  psql -v ON_ERROR_STOP=1 -X -d "$base" -c 'SELECT postgis_extensions_upgrade();'
  # unaccent: busca sem acento (spec 012 T4.0). Também no template1, para o banco de teste herdar.
  psql -v ON_ERROR_STOP=1 -X -d "$base" -c 'CREATE EXTENSION IF NOT EXISTS unaccent;'
done
