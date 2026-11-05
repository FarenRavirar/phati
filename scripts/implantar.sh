#!/usr/bin/env bash
# Implantação na VM (spec 006 R5, R7, R8). Roda na VM, chamada pela chave SSH de deploy (comando forçado em
# `authorized_keys`): o pedido do cliente chega em SSH_ORIGINAL_COMMAND e é só "<sha>" ou "<sha> --sem-migracao".
# Uso direto: implantar.sh <sha> [--sem-migracao]
# Variáveis: PHATI_DIR (padrão /opt/phati, com `.env` e `repo/`), PHATI_REF (padrão origin/main), DOCKER (para teste),
# PHATI_TENTATIVAS e PHATI_ESPERA (espera pela saúde do app).
# Ordem: confere o SHA, backup do banco, build, para o app, migra, estáticos, sobe o app, espera a saúde, sobe nginx e túnel.
# Falha em qualquer passo para tudo. Rollback é rodar de novo com o SHA anterior e `--sem-migracao` (e `restaurar.sh`
# se a migração não tiver volta).
# -E: o trap ERR vale dentro de funções; sem ele, falha do Docker sairia calada, sem mensagem nem registro.
set -Eeuo pipefail

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
parado=0
erro() {
  echo "ERRO: $*" >&2
  # Falhar fechado é de propósito: depois de parar o app, o código novo contra o banco antigo (ou meio migrado) é pior do
  # que o site fora do ar (T4.7 da 001: worker antigo não assina o contexto de RLS).
  if [[ "$parado" == 1 ]]; then
    echo "AVISO: o app pode estar parado. Recupere com 'implantar.sh <sha anterior> --sem-migracao' ou com restaurar.sh." >&2
  fi
  registrar "FALHOU: $*"
  exit 1
}

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

# O único dado vindo de fora é o SHA: nada dele chega a um shell além desta regra de 40 hexadecimais.
[[ "$sha" =~ ^[0-9a-f]{40}$ ]] || erro "informe o SHA completo (40 caracteres hexadecimais)"
[[ -z "$opcao" || "$opcao" == "--sem-migracao" ]] || erro "opção desconhecida: só --sem-migracao"
[[ -f "$dir/.env" ]] || erro "$dir/.env ausente (segredos ficam só na VM)"
[[ -d "$dir/repo/.git" ]] || erro "$dir/repo não é um clone do repositório"
travar "$@"

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
compor() { "$docker" compose --env-file "$dir/.env" -f "$dir/repo/servidor/compose.yaml" -f "$dir/repo/servidor/compose.implantacao.yaml" "$@"; }

passo=inicio
trap 'erro "falhou no passo: $passo"' ERR
registrar "inicio anterior=${anterior:0:12}"

passo=backup
# Banco parado com volume é instalação existente, não a primeira: sobe o banco e tira o backup antes de migrar.
tem_dados=0
if [[ -n "$(compor ps -q banco 2>/dev/null)" ]] || "$docker" volume inspect "${COMPOSE_PROJECT_NAME}_dados_banco" >/dev/null 2>&1; then
  tem_dados=1
fi
if [[ "$tem_dados" == 1 ]]; then
  compor up -d --wait banco
  mkdir -p "$dir/backups"
  arquivo="$dir/backups/phati-$(date -u +%Y%m%dT%H%M%SZ)-${anterior:0:12}.dump"
  # As credenciais ficam no ambiente do contêiner do banco; nada delas passa por este script nem pela saída.
  (umask 077; compor exec -T banco sh -c 'PGPASSWORD="$PHATI_BANCO_DONO_SENHA" pg_dump -h 127.0.0.1 -U "$PHATI_BANCO_DONO_USUARIO" -Fc "$PHATI_BANCO_NOME"' > "$arquivo")
  [[ -s "$arquivo" ]] || erro "backup vazio: $arquivo"
  ls -1t "$dir"/backups/*.dump | tail -n +15 | xargs -r rm -f --
else
  echo "sem banco nem volume: primeira implantação, sem backup"
fi

passo=build
compor build
passo=parar-app
parado=1
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
# Sempre recria o nginx (Codex, PR #46): ele resolve `app` ao carregar a configuração e seguiria no IP do app antigo (502), e
# o `git checkout` troca o inode do `default.conf` montado como arquivo, então nem `reload` nem `up` sem recriar o veriam mudar.
compor up -d --no-deps --force-recreate nginx
compor up -d --no-deps cloudflared
trap - ERR
registrar "OK"
echo "implantado=${sha:0:12}"
