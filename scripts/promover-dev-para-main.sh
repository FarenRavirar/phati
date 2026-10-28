#!/usr/bin/env bash
# Promoção dev -> main por fast-forward (AGENTS.md §Git). Só move o ponteiro Git, sem build nem deploy.
# Uso: promover-dev-para-main.sh <confirmacao> [remoto]
set -euo pipefail

confirmacao="${1:-}"
remoto="${2:-origin}"

if [ "$confirmacao" != "PROMOTE_DEV_TO_MAIN" ]; then
  echo "ERRO: a confirmação precisa ser PROMOTE_DEV_TO_MAIN" >&2
  exit 1
fi

bash "$(dirname "$0")/validar-invariante-ramos.sh" "$remoto"

git push "$remoto" "refs/remotes/$remoto/dev:refs/heads/main"
echo "ref_promovida=$(git rev-parse --short "$remoto/dev")"
