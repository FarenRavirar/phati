#!/usr/bin/env bash
# Guarda do workflow de implantação (spec 006 R5): só roda em `main`, em repositório público (o Environment com revisor
# obrigatório é ignorado se o repositório virar privado, doc do GitHub) e para um SHA que já esteja em `origin/main`.
# Uso: guardar-implantacao.sh <ref> <privado:true|false> <sha> [remoto]
set -euo pipefail

ref="${1:-}"
privado="${2:-}"
sha="${3:-}"
remoto="${4:-origin}"

[[ "$ref" == "refs/heads/main" ]] || { echo "ERRO: a implantação só roda em refs/heads/main (veio: $ref)" >&2; exit 1; }
[[ "$privado" == "false" ]] || { echo "ERRO: o repositório precisa ser público para o revisor do Environment valer" >&2; exit 1; }
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "ERRO: informe o SHA completo (40 caracteres)" >&2; exit 1; }
git cat-file -e "$sha^{commit}" 2>/dev/null || { echo "ERRO: o SHA $sha não existe neste clone" >&2; exit 1; }
git merge-base --is-ancestor "$sha" "$remoto/main" || { echo "ERRO: o SHA $sha não está em $remoto/main" >&2; exit 1; }
echo "implantacao_guardada=${sha:0:12}"
