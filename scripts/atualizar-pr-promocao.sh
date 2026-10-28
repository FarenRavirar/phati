#!/usr/bin/env bash
# Cria ou atualiza a PR permanente de revisão dev -> main (AGENTS.md §Git).
# Ambiente: GH_TOKEN, GH_REPO e DONO (dono do repositório); usa o `gh` do PATH.
set -euo pipefail

# --head filtra só pelo nome da branch; o filtro do dono descarta PR vinda de fork com cabeça `dev`.
numero=$(gh pr list \
  --base main \
  --head dev \
  --state open \
  --json number,headRepositoryOwner \
  --jq ".[] | select(.headRepositoryOwner.login == \"$DONO\") | .number" | head -n 1)

titulo="Revisar promoção dev para main"
corpo=$(cat <<'EOF'
PR permanente e automática para revisar o que será promovido de `dev` para `main`.

**Regra crítica:** `main` deve continuar ancestral de `dev` (`main ⊆ dev`).

Não use "Squash and merge", "Create a merge commit" nem "Rebase and merge": os três criam em `main` commits que não existem em `dev` (o rebase reescreve o committer e gera SHAs novos) e quebram o guard.

Promoção aprovada: só o workflow `promover-dev-para-main.yml`, com a confirmação `PROMOTE_DEV_TO_MAIN` e o SHA de `dev` que foi revisado (`sha_aprovado`); se `dev` avançou depois, a promoção para.

Depois da promoção, `main` deve apontar para o mesmo commit de `dev` ou para um commit contido em `dev`.
Promover não é publicar: o deploy é uma etapa à parte.
EOF
)

# Falha ao criar ou editar a PR derruba o job: warning com exit 0 mascararia o erro (AGENTS.md §Escopo).
# Causa conhecida: "Allow GitHub Actions to create and approve pull requests" desligado em
# Settings -> Actions -> General (`gh api repos/<dono>/<repo>/actions/permissions/workflow`).
if [[ -n "$numero" ]]; then
  if gh pr edit "$numero" --title "$titulo" --body "$corpo"; then
    echo "pr_promocao=$numero"
  else
    echo "::error::Não foi possível editar a PR permanente #$numero. Confira se o GitHub Actions pode criar e aprovar PRs (Settings -> Actions -> General)." >&2
    exit 1
  fi
elif gh pr create --base main --head dev --title "$titulo" --body "$corpo"; then
  echo "pr_promocao=criada"
else
  echo "::error::Não foi possível criar a PR permanente dev -> main. Confira se o GitHub Actions pode criar e aprovar PRs (Settings -> Actions -> General)." >&2
  exit 1
fi
