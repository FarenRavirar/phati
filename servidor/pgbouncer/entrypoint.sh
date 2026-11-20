#!/bin/sh
# Entrada do PgBouncer (spec 009 R18). Sem argumento: sobe a instância `PGB_INSTANCIA` com o modelo copiado para o
# próprio diretório (socket, pid e log por instância). `auth`: grava /cfg/userlist.txt com o verificador SCRAM do papel
# do app, sem imprimir nada. PGB_RAIZ, PGB_CFG, PGB_MODELO, PGB_BIN e PGB_PSQL existem só para o teste.
set -eu

raiz="${PGB_RAIZ:-/tmp/pgb}"  # na camada do contêiner, não tmpfs: sobrevive a `docker start` (medido, ver compose)
cfg="${PGB_CFG:-/cfg}"
modelo="${PGB_MODELO:-/etc/pgbouncer/modelo.ini}"

# Só minúsculas, dígitos e `_`: o valor entra no .ini e no caminho do socket, então nada que escape disso passa.
nome_valido() {
    case "$1" in
        ''|*[!a-z0-9_]*) return 1 ;;
        *) return 0 ;;  # só o que sobra é válido: explícito para o `case` não depender de cair fora dele
    esac
}

if [ "${1:-}" = auth ]; then
    nome_valido "${PHATI_BANCO_APP_USUARIO:-}" || { echo "auth: PHATI_BANCO_APP_USUARIO inválido" >&2; exit 1; }
    tmp="$cfg/userlist.tmp"
    umask 0137  # arquivo final 0640: o pgbouncer roda como postgres, o mesmo dono
    if ! "${PGB_PSQL:-psql}" -X -q -At -v ON_ERROR_STOP=1 -v app="$PHATI_BANCO_APP_USUARIO" -f - > "$tmp" <<'SQL'
SELECT '"'||rolname||'" "'||rolpassword||'"' FROM pg_authid WHERE rolname = :'app';
SQL
    then
        rm -f "$tmp"
        echo "auth: a consulta ao banco falhou" >&2
        exit 1
    fi
    # Papel sem senha dá linha vazia (NULL), e senha que não é SCRAM não serve ao PgBouncer: nada disso vira arquivo.
    if [ "$(wc -l < "$tmp" | tr -d ' ')" -ne 1 ] || ! grep -Eq '^"[^"]+" "SCRAM-SHA-256\$[^"]+"$' "$tmp"; then
        rm -f "$tmp"
        echo "auth: o papel do app não tem verificador SCRAM" >&2
        exit 1
    fi
    mv "$tmp" "$cfg/userlist.txt"
    exit 0
fi

instancia="${PGB_INSTANCIA:-}"
nome_valido "$instancia" || { echo "PGB_INSTANCIA inválida" >&2; exit 1; }
nome_valido "${PHATI_BANCO_NOME:-}" || { echo "PHATI_BANCO_NOME inválido" >&2; exit 1; }

dir="$raiz/$instancia"
mkdir -p "$dir"
# Restos de execução anterior (pid e socket) impedem o novo processo de subir: some antes de iniciar.
rm -f "$dir"/*.pid "$dir"/.s.PGSQL.*
sed -e "s|@BANCO@|$PHATI_BANCO_NOME|g" -e "s|@DIR@|$dir|g" "$modelo" > "$dir/pgbouncer.ini"
exec "${PGB_BIN:-pgbouncer}" "$dir/pgbouncer.ini"
