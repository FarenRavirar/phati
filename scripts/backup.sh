#!/usr/bin/env bash
# Backup do banco (spec 006 R8, R11): pg_dump do papel dono em formato custom, fora do volume do banco, modo 0600 e 14 cópias.
# Uso: backup.sh [rótulo]   (o rótulo entra no nome do arquivo; padrão "cron"). Imprime o caminho do dump.
# Variáveis: PHATI_DIR (padrão /opt/phati, com `.env`, `repo/` e `backups/`), DOCKER (para teste) e PHATI_BACKUP_LIMITE
# (segundos do pg_dump; padrão 1800).
# Quem chama: implantar.sh, antes de migrar (já sob a trava), e o cron diário do usuário de implantação, que roda sob
# `flock -w 3600 /opt/phati/.trava` (o mesmo limite do implantar.sh) para não correr com uma implantação. Banco parado é
# erro: o backup não sobe nada.
set -Eeuo pipefail

dir="${PHATI_DIR:-/opt/phati}"
docker="${DOCKER:-docker}"
rotulo="${1:-cron}"

erro() { echo "ERRO: $*" >&2; exit 1; }
[[ "$rotulo" =~ ^[A-Za-z0-9_-]{1,20}$ ]] || erro "rótulo inválido: só letras, números, _ e -, até 20"
[[ -f "$dir/.env" ]] || erro "$dir/.env ausente (segredos ficam só na VM)"

export COMPOSE_PROJECT_NAME=phati
mkdir -p "$dir/backups"
# Grava num arquivo parcial e só o promove ao nome final se o dump deu certo: uma falha nunca apaga um dump válido que
# tenha o mesmo nome (mesmo segundo e rótulo), e o parcial não casa com `*.dump` da retenção nem do restaurar.sh.
parcial="$(mktemp "$dir/backups/.parcial.XXXXXX")"
trap 'rm -f -- "$parcial"' EXIT
arquivo="$dir/backups/phati-$(date -u +%Y%m%dT%H%M%SZ)-$rotulo.dump"
# As credenciais ficam no ambiente do contêiner do banco; nada delas passa por este script nem pela saída.
# O prazo evita que um Docker ou banco travado segure a trava da implantação para sempre.
if ! timeout "${PHATI_BACKUP_LIMITE:-1800}" "$docker" compose --env-file "$dir/.env" -f "$dir/repo/servidor/compose.yaml" -f "$dir/repo/servidor/compose.implantacao.yaml" exec -T banco sh -c 'PGPASSWORD="$PHATI_BANCO_DONO_SENHA" pg_dump -h 127.0.0.1 -U "$PHATI_BANCO_DONO_USUARIO" -Fc "$PHATI_BANCO_NOME"' > "$parcial"; then
  erro "pg_dump falhou ou passou do prazo (banco parado?)"
fi
[[ -s "$parcial" ]] || erro "backup vazio: $arquivo"
mv -f -- "$parcial" "$arquivo"
# Leitura linha a linha (não xargs): caminho com espaço não vira dois argumentos.
ls -1t "$dir"/backups/*.dump | tail -n +15 | while IFS= read -r antigo; do rm -f -- "$antigo"; done
echo "$arquivo"
