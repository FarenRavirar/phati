#!/usr/bin/env bash
# Restaura um backup do banco na VM (spec 006 R8). Destrutivo: troca os dados atuais pelos do arquivo.
# Uso: restaurar.sh <arquivo.dump> RESTAURAR
# Para o app, restaura com o papel dono (`--clean --if-exists`) e sobe o app de novo; a saúde quem chamou confere.
set -euo pipefail

arquivo="${1:-}"
confirmacao="${2:-}"
dir="${PHATI_DIR:-/opt/phati}"
docker="${DOCKER:-docker}"

[[ "$confirmacao" == "RESTAURAR" ]] || { echo "ERRO: a confirmação precisa ser RESTAURAR" >&2; exit 1; }
[[ -n "$arquivo" && -s "$arquivo" ]] || { echo "ERRO: informe um arquivo de backup existente e não vazio" >&2; exit 1; }
[[ "$arquivo" == "$dir"/backups/*.dump && "$arquivo" != *..* ]] || { echo "ERRO: só restaura arquivo de $dir/backups" >&2; exit 1; }
[[ -f "$dir/.env" ]] || { echo "ERRO: $dir/.env ausente" >&2; exit 1; }

export COMPOSE_PROJECT_NAME=phati
compor() { (cd "$dir/repo/servidor" && "$docker" compose --env-file "$dir/.env" -f compose.yaml -f compose.implantacao.yaml "$@"); }

compor stop app
compor up -d --wait banco
compor exec -T banco sh -c 'PGPASSWORD="$PHATI_BANCO_DONO_SENHA" pg_restore --clean --if-exists --no-owner -h 127.0.0.1 -U "$PHATI_BANCO_DONO_USUARIO" -d "$PHATI_BANCO_NOME"' < "$arquivo"
compor up -d --no-deps app
echo "restaurado=$(basename "$arquivo")"
