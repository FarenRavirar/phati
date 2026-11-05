#!/usr/bin/env bash
# Restaura um backup do banco na VM (spec 006 R8). Destrutivo: troca os dados atuais pelos do arquivo.
# Uso: restaurar.sh <arquivo.dump> RESTAURAR
# Para o app, valida o dump (gera o SQL antes de apagar qualquer coisa) e troca o schema `public` inteiro numa transação
# única: objetos criados depois do dump somem junto, e qualquer erro desfaz tudo e deixa o banco como estava. O app só
# sobe de novo se a restauração terminar; a saúde, quem chamou confere.
set -Eeuo pipefail

arquivo="${1:-}"
confirmacao="${2:-}"
dir="${PHATI_DIR:-/opt/phati}"
docker="${DOCKER:-docker}"

[[ "$confirmacao" == "RESTAURAR" ]] || { echo "ERRO: a confirmação precisa ser RESTAURAR" >&2; exit 1; }
[[ -n "$arquivo" && -s "$arquivo" ]] || { echo "ERRO: informe um arquivo de backup existente e não vazio" >&2; exit 1; }
[[ "$arquivo" == "$dir"/backups/*.dump && "$arquivo" != *..* ]] || { echo "ERRO: só restaura arquivo de $dir/backups" >&2; exit 1; }
[[ -f "$dir/.env" ]] || { echo "ERRO: $dir/.env ausente" >&2; exit 1; }

# Uma implantação ou restauração por vez (o workflow já serializa, mas o SSH direto e o restaurar.sh não): trava por
# diretório, que o `mkdir` cria de forma atômica em qualquer sistema. Trava de processo morto é desfeita; a espera é de 1 h.
# shortcut: `mkdir` no lugar de `flock`, que o Git Bash dos testes locais não tem; trocar por `flock` se a VM passar a ter só Linux.
travar() {
  local trava="$dir/.trava" limite=$((SECONDS + ${PHATI_TRAVA_LIMITE:-3600}))
  until mkdir "$trava" 2>/dev/null; do
    if [[ -f "$trava/pid" ]] && ! kill -0 "$(cat "$trava/pid")" 2>/dev/null; then
      rm -rf "$trava"
      continue
    fi
    (( SECONDS < limite )) || { echo "ERRO: outra implantação ou restauração segue rodando (trava em $trava)" >&2; exit 1; }
    sleep "${PHATI_ESPERA_TRAVA:-5}"
  done
  echo $$ > "$trava/pid"
  trap 'rm -rf "$dir/.trava"' EXIT
}
travar

export COMPOSE_PROJECT_NAME=phati
compor() { "$docker" compose --env-file "$dir/.env" -f "$dir/repo/servidor/compose.yaml" -f "$dir/repo/servidor/compose.implantacao.yaml" "$@"; }

trap 'echo "ERRO: a restauração falhou; o banco ficou como estava (transação única) e o app segue parado" >&2' ERR

compor stop app
compor up -d --wait banco
# `pg_restore -f` falhando (dump inválido) para antes do `psql`, que só então apaga e recria o schema. O GRANT devolve o
# USAGE que o schema `public` novo não tem e o papel `app` precisa. O SQL temporário (com dado) é apagado ao sair.
compor exec -T banco sh -c 'set -e; trap "rm -f /tmp/restaurar-dump.sql /tmp/restaurar-total.sql" EXIT; export PGPASSWORD="$PHATI_BANCO_DONO_SENHA"; pg_restore --no-owner -f /tmp/restaurar-dump.sql; { echo "DROP SCHEMA public CASCADE;"; echo "CREATE SCHEMA public;"; echo "GRANT USAGE ON SCHEMA public TO PUBLIC;"; cat /tmp/restaurar-dump.sql; } > /tmp/restaurar-total.sql; psql -q -v ON_ERROR_STOP=1 --single-transaction -h 127.0.0.1 -U "$PHATI_BANCO_DONO_USUARIO" -d "$PHATI_BANCO_NOME" -f /tmp/restaurar-total.sql' < "$arquivo"
compor up -d --no-deps app
echo "restaurado=$(basename "$arquivo")"
