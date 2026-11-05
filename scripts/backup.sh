#!/usr/bin/env bash
# Backup do banco (spec 006 R8, R11): pg_dump do papel dono em formato custom, fora do volume do banco, modo 0600 e 14 cópias.
# Uso: backup.sh [rótulo]   (o rótulo entra no nome do arquivo; padrão "cron"). Imprime o caminho do dump.
# Variáveis: PHATI_DIR (padrão /opt/phati, com `.env`, `repo/` e `backups/`) e DOCKER (para teste).
# Quem chama: implantar.sh, antes de migrar (já sob a trava), e o cron diário do usuário de implantação, que roda sob
# `flock -w 600 /opt/phati/.trava` para não correr com uma implantação. Banco parado é erro: o backup não sobe nada.
set -Eeuo pipefail

dir="${PHATI_DIR:-/opt/phati}"
docker="${DOCKER:-docker}"
rotulo="${1:-cron}"

erro() { echo "ERRO: $*" >&2; exit 1; }
[[ "$rotulo" =~ ^[A-Za-z0-9_-]{1,20}$ ]] || erro "rótulo inválido: só letras, números, _ e -, até 20"
[[ -f "$dir/.env" ]] || erro "$dir/.env ausente (segredos ficam só na VM)"

export COMPOSE_PROJECT_NAME=phati
mkdir -p "$dir/backups"
arquivo="$dir/backups/phati-$(date -u +%Y%m%dT%H%M%SZ)-$rotulo.dump"
# As credenciais ficam no ambiente do contêiner do banco; nada delas passa por este script nem pela saída.
if ! (umask 077; "$docker" compose --env-file "$dir/.env" -f "$dir/repo/servidor/compose.yaml" -f "$dir/repo/servidor/compose.implantacao.yaml" exec -T banco sh -c 'PGPASSWORD="$PHATI_BANCO_DONO_SENHA" pg_dump -h 127.0.0.1 -U "$PHATI_BANCO_DONO_USUARIO" -Fc "$PHATI_BANCO_NOME"' > "$arquivo"); then
  rm -f -- "$arquivo"
  erro "pg_dump falhou (banco parado?)"
fi
[[ -s "$arquivo" ]] || { rm -f -- "$arquivo"; erro "backup vazio: $arquivo"; }
ls -1t "$dir"/backups/*.dump | tail -n +15 | xargs -r rm -f --
echo "$arquivo"
