# Imagem do PgBouncer (spec 009 R18). Base `postgres:18` fixada por digest (a mesma do banco), para ter o `psql` do passo `auth`.
# O pacote `pgbouncer` vem do repositório PGDG (apt.postgresql.org), que a imagem oficial do postgres já configura; a versão
# fica fixada. Medido na 1.26.1 (Debian 13, amd64, spec 009 plan.md §PgBouncer). Build local só: a imagem vai à VM
# (arm64 não testado) apenas com aprovação nominal do mantenedor (AGENTS.md, Pausa 1).
FROM postgres:18@sha256:e754b839f447639b7004895f4d8a4bfcb4e9dbe3a1bc035f27f646562a16fd61
RUN apt-get update \
    && apt-get install -y --no-install-recommends pgbouncer=1.26.1-1.pgdg13+1 \
    && rm -rf /var/lib/apt/lists/*
COPY pgbouncer.ini /etc/pgbouncer/modelo.ini
COPY entrypoint.sh /entrypoint.sh
# /cfg é o volume `pgb_cfg`: nasce com o dono do diretório da imagem, o usuário `postgres`, que o `auth` escreve.
RUN mkdir /cfg && chown postgres:postgres /cfg && chmod 0755 /entrypoint.sh
USER postgres
ENTRYPOINT ["/entrypoint.sh"]
