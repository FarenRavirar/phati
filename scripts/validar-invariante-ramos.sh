#!/usr/bin/env bash
# Invariante do AGENTS.md §Git: `main` é ancestral de `dev`. Busca as duas branches no remoto e confere.
# Usado pela promoção e pelo guard. Uso: validar-invariante-ramos.sh [remoto]
set -euo pipefail

remoto="${1:-origin}"

git fetch --no-tags --prune "$remoto" \
  "+refs/heads/main:refs/remotes/$remoto/main" \
  "+refs/heads/dev:refs/remotes/$remoto/dev"

if ! git merge-base --is-ancestor "$remoto/main" "$remoto/dev"; then
  echo "ERRO: invariante quebrada: $remoto/main não é ancestral de $remoto/dev." >&2
  echo "Produção bloqueada: promova main para dev ou reconcilie dev." >&2
  exit 1
fi

echo "invariante_ramos_ok=true"
