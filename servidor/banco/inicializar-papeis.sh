#!/bin/sh
# Roda uma vez, na criação do volume (docker-entrypoint-initdb.d): cria papéis e banco.
# As senhas chegam pelo ambiente do contêiner; o papeis.sql as lê com \getenv.
set -eu
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres -f /papeis.sql
