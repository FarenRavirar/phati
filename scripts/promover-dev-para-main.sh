#!/usr/bin/env bash
# Promoção dev -> main por fast-forward (AGENTS.md §Git). Só move o ponteiro Git, sem build nem deploy.
# Uso: promover-dev-para-main.sh <confirmacao> <sha_aprovado> [remoto]
# O SHA aprovado é o commit de dev que o mantenedor revisou: se dev avançou depois, a promoção para.
set -euo pipefail

confirmacao="${1:-}"
sha_aprovado="${2:-}"
remoto="${3:-origin}"

if [[ "$confirmacao" != "PROMOTE_DEV_TO_MAIN" ]]; then
  echo "ERRO: a confirmação precisa ser PROMOTE_DEV_TO_MAIN" >&2
  exit 1
fi

if [[ -z "$sha_aprovado" ]]; then
  echo "ERRO: informe o SHA de dev aprovado para a promoção" >&2
  exit 1
fi

bash "$(dirname "$0")/validar-invariante-ramos.sh" "$remoto"

aprovado=$(git rev-parse --verify --quiet "$sha_aprovado^{commit}") || {
  echo "ERRO: o SHA $sha_aprovado não existe neste repositório" >&2
  exit 1
}
atual=$(git rev-parse "$remoto/dev")
if [[ "$aprovado" != "$atual" ]]; then
  echo "ERRO: dev avançou: o SHA aprovado é $aprovado e dev está em $atual. Revise e promova de novo." >&2
  exit 1
fi

git push "$remoto" "$aprovado:refs/heads/main"

# O push feito com o GITHUB_TOKEN não dispara outros workflows (doc "GITHUB_TOKEN"): o guard de
# ancestralidade roda aqui, explicitamente.
bash "$(dirname "$0")/validar-invariante-ramos.sh" "$remoto"
echo "ref_promovida=$(git rev-parse --short "$aprovado")"
