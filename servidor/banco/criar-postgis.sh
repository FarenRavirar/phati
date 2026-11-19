#!/bin/sh
# Roda uma vez, na criação do volume (docker-entrypoint-initdb.d), como superusuário. `template1` recebe a extensão;
# bancos criados depois dele herdam a extensão, então o papel da aplicação não precisa de superusuário para usá-la.
set -eu
psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d template1 -c 'CREATE EXTENSION IF NOT EXISTS postgis;'
