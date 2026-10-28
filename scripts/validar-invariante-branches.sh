#!/usr/bin/env bash
# Invariante do AGENTS.md §Git: `main` é ancestral de `dev`. Usado pela promoção e pelo guard.
set -euo pipefail

ref_main="${1:-origin/main}"
ref_dev="${2:-origin/dev}"

if ! git merge-base --is-ancestor "$ref_main" "$ref_dev"; then
  echo "ERRO: invariante quebrada: $ref_main não é ancestral de $ref_dev." >&2
  echo "Produção bloqueada: promova main para dev ou reconcilie dev." >&2
  exit 1
fi

echo "invariante_branches_ok=true"
