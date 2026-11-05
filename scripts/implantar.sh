#!/usr/bin/env bash
# Implantação na VM (spec 006 R5, R7, R8). Roda na VM, chamada pela chave SSH de deploy (comando forçado em
# `authorized_keys`): o pedido do cliente chega em SSH_ORIGINAL_COMMAND e é só "<sha>" ou "<sha> --sem-migracao".
# Uso direto: implantar.sh <sha> [--sem-migracao]
# Variáveis: PHATI_DIR (padrão /opt/phati, com `.env` e `repo/`), PHATI_REF (padrão origin/main), DOCKER (para teste),
# PHATI_TENTATIVAS e PHATI_ESPERA (espera pela saúde do app).
# Ordem: confere o SHA, backup do banco, build, para o app, migra, estáticos, sobe o app, espera a saúde, sobe nginx e túnel.
# Falha em qualquer passo para tudo. Rollback é rodar de novo com o SHA anterior e `--sem-migracao` (e `restaurar.sh`
# se a migração não tiver volta).
set -euo pipefail

if [[ $# -gt 0 ]]; then
  sha="${1:-}"
  opcao="${2:-}"
else
  read -r sha opcao <<<"${SSH_ORIGINAL_COMMAND:-}" || true
  sha="${sha:-}"
  opcao="${opcao:-}"
fi

dir="${PHATI_DIR:-/opt/phati}"
ref="${PHATI_REF:-origin/main}"
docker="${DOCKER:-docker}"
registro="$dir/implantacoes.log"

registrar() { printf '%s %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${sha:-sem-sha}" "$*" >> "$registro" 2>/dev/null || true; }
erro() {
  echo "ERRO: $*" >&2
  registrar "FALHOU: $*"
  exit 1
}

# O único dado vindo de fora é o SHA: nada dele chega a um shell além desta regra de 40 hexadecimais.
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || erro "informe o SHA completo (40 caracteres hexadecimais)"
[[ -z "$opcao" || "$opcao" == "--sem-migracao" ]] || erro "opção desconhecida: só --sem-migracao"
[[ -f "$dir/.env" ]] || erro "$dir/.env ausente (segredos ficam só na VM)"
[[ -d "$dir/repo/.git" ]] || erro "$dir/repo não é um clone do repositório"

cd "$dir/repo"
git fetch -q origin
git cat-file -e "$sha^{commit}" 2>/dev/null || erro "o SHA $sha não existe no repositório"
git merge-base --is-ancestor "$sha" "$ref" || erro "o SHA $sha não é ancestral de $ref: só entra o que foi promovido"
anterior="$(git rev-parse HEAD 2>/dev/null || echo nenhum)"
git checkout -q --detach "$sha"
# O script em execução é a cópia instalada fora do clone; avisa se a do repositório mudou e precisa ser reinstalada.
if [[ -f scripts/implantar.sh && -f "$0" ]] && ! cmp -s scripts/implantar.sh "$0"; then
  echo "AVISO: o implantar.sh instalado difere do repositório; reinstale como administrador" >&2
fi

export COMPOSE_PROJECT_NAME=phati
compor() { (cd servidor && "$docker" compose --env-file "$dir/.env" -f compose.yaml -f compose.implantacao.yaml "$@"); }

passo=inicio
trap 'erro "falhou no passo: $passo"' ERR
registrar "inicio anterior=${anterior:0:12}"

passo=backup
if [[ -n "$(compor ps -q banco 2>/dev/null)" ]]; then
  mkdir -p "$dir/backups"
  arquivo="$dir/backups/phati-$(date -u +%Y%m%dT%H%M%SZ)-${anterior:0:12}.dump"
  # As credenciais ficam no ambiente do contêiner do banco; nada delas passa por este script nem pela saída.
  (umask 077; compor exec -T banco sh -c 'PGPASSWORD="$PHATI_BANCO_DONO_SENHA" pg_dump -h 127.0.0.1 -U "$PHATI_BANCO_DONO_USUARIO" -Fc "$PHATI_BANCO_NOME"' > "$arquivo")
  [[ -s "$arquivo" ]] || erro "backup vazio: $arquivo"
  ls -1t "$dir"/backups/*.dump | tail -n +15 | xargs -r rm -f --
else
  echo "sem banco no ar: primeira implantação, sem backup"
fi

passo=build
compor build
passo=parar-app
compor stop app
passo=banco
compor up -d --wait banco
if [[ "$opcao" != "--sem-migracao" ]]; then
  passo=migracao
  compor run --rm migracao
fi
passo=estaticos
compor run --rm --no-deps estaticos
passo=app
compor up -d --no-deps app

estado=""
for _ in $(seq "${PHATI_TENTATIVAS:-60}"); do
  estado="$("$docker" inspect -f '{{.State.Health.Status}}' "$(compor ps -q app)" 2>/dev/null || true)"
  [[ "$estado" == healthy ]] && break
  sleep "${PHATI_ESPERA:-2}"
done
passo=saude
[[ "$estado" == healthy ]] || erro "o app não ficou saudável (estado: ${estado:-desconhecido})"

passo=nginx-e-tunel
compor up -d --no-deps nginx cloudflared
trap - ERR
registrar "OK"
echo "implantado=${sha:0:12}"
