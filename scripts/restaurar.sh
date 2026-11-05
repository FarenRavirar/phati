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

# Uma implantação ou restauração por vez (o workflow já serializa, mas o SSH direto e o restaurar.sh não). O script roda
# de novo dentro de `flock -w <limite> -E 75 <arquivo> comando`: o sistema solta a trava quando o processo morre, sem trava
# presa e sem corrida na limpeza (Greptile, PR #46; a versão com `mkdir` e `kill -0` apagava a trava nova de quem a
# tinha acabado de tomar). O comando `flock` vem de PHATI_FLOCK (os testes trocam por um dublê); o 75 marca "ocupado".
# shortcut: sem `flock` (só o Git Bash dos testes locais) segue sem trava e avisa; a VM e o CI são Linux e o têm.
travar() {
  local flock_cmd="${PHATI_FLOCK:-flock}" rc=0
  [[ -z "${PHATI_TRAVADO:-}" ]] || return 0
  if ! command -v "$flock_cmd" >/dev/null 2>&1; then
    echo "AVISO: sem flock neste sistema; seguindo sem trava" >&2
    return 0
  fi
  export PHATI_TRAVADO=1
  "$flock_cmd" -w "${PHATI_TRAVA_LIMITE:-3600}" -E 75 "$dir/.trava" bash "$0" "$@" || rc=$?
  if [[ "$rc" == 75 ]]; then
    echo "ERRO: outra implantação ou restauração segue rodando (trava em $dir/.trava)" >&2
    exit 1
  fi
  exit "$rc"
}
travar "$@"

export COMPOSE_PROJECT_NAME=phati
compor() { "$docker" compose --env-file "$dir/.env" -f "$dir/repo/servidor/compose.yaml" -f "$dir/repo/servidor/compose.implantacao.yaml" "$@"; }

passo=inicio
# A transação única só protege até o `psql`: falha depois dele deixa o banco já restaurado e o app parado.
trap 'if [[ "$passo" == subir-app ]]; then echo "ERRO: o banco foi restaurado, mas o app não subiu; suba com: docker compose up -d --no-deps app" >&2; else echo "ERRO: a restauração falhou no passo $passo; o banco ficou como estava (transação única) e o app segue parado" >&2; fi' ERR

passo=parar-app
compor stop app
passo=banco
compor up -d --wait banco
passo=restaurar-dump
# `pg_restore -f` falhando (dump inválido) para antes do `psql`, que só então apaga e recria o schema. O GRANT devolve o
# USAGE que o schema `public` novo não tem e o papel `app` precisa. O SQL temporário (com dado) é apagado ao sair.
compor exec -T banco sh -c 'set -e; trap "rm -f /tmp/restaurar-dump.sql /tmp/restaurar-total.sql" EXIT; export PGPASSWORD="$PHATI_BANCO_DONO_SENHA"; pg_restore --no-owner -f /tmp/restaurar-dump.sql; { echo "DROP SCHEMA public CASCADE;"; echo "CREATE SCHEMA public;"; echo "GRANT USAGE ON SCHEMA public TO PUBLIC;"; cat /tmp/restaurar-dump.sql; } > /tmp/restaurar-total.sql; psql -q -v ON_ERROR_STOP=1 --single-transaction -h 127.0.0.1 -U "$PHATI_BANCO_DONO_USUARIO" -d "$PHATI_BANCO_NOME" -f /tmp/restaurar-total.sql' < "$arquivo"
passo=subir-app
compor up -d --no-deps app
echo "restaurado=$(basename "$arquivo")"
