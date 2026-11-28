#!/usr/bin/env bash
# Backup do banco (spec 006 R8, R11): pg_dump do papel dono em formato custom, fora do volume do banco, modo 0600 e 14 cópias.
# Uso: backup.sh [rótulo]   (o rótulo entra no nome do arquivo; padrão "cron"). Imprime o caminho do dump.
# Variáveis: PHATI_DIR (padrão /opt/phati, com `.env`, `repo/` e `backups/`), DOCKER (para teste) e PHATI_BACKUP_LIMITE
# (segundos do pg_dump; padrão 1800) e PHATI_BACKUP_ABATE (segundos até o KILL depois do prazo; padrão 10).
# Quem chama: implantar.sh, antes de migrar (já sob a trava), e o cron diário do usuário de implantação, que roda sob
# `flock -w 3600 /opt/phati/.trava` (o mesmo limite do implantar.sh) para não correr com uma implantação. Banco parado é
# erro: o backup não sobe nada. Troca de banco interrompida (marcador `troca-banco-em-curso`) recusa antes do Docker, e o
# destino do compose (`PHATI_BANCO_DESTINO`) segue o `banco-ativo` (spec 009 R15). O valor lido do `.env` passa por `valor_env`
# (aspas e ` #comentário` saem como no Compose) antes da comparação com banco_novo.
set -Eeuo pipefail

dir="${PHATI_DIR:-/opt/phati}"
docker="${DOCKER:-docker}"
rotulo="${1:-cron}"

erro() { echo "ERRO: $*" >&2; exit 1; }
[[ "$rotulo" =~ ^[A-Za-z0-9_-]{1,20}$ ]] || erro "rótulo inválido: só letras, números, _ e -, até 20"
[[ -f "$dir/.env" ]] || erro "$dir/.env ausente (segredos ficam só na VM)"
# X4: ambiente, `.env` da VM, padrão $dir/alvo (como implantar.sh): o compose exige a variável (`${PHATI_ALVO_DIR:?}`).
alvo_dir="${PHATI_ALVO_DIR:-}"
[[ -n "$alvo_dir" ]] || alvo_dir="$(grep -m1 '^PHATI_ALVO_DIR=' "$dir/.env" 2>/dev/null | cut -d= -f2- || true)"
export PHATI_ALVO_DIR="${alvo_dir:-$dir/alvo}"

# Nome do projeto Compose: `phati` na VM; `PHATI_PROJETO` só troca no ensaio local (spec 009, X4a). Valor inválido para antes do Docker.
projeto="${PHATI_PROJETO:-phati}"
[[ "$projeto" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || erro "PHATI_PROJETO inválido: use minúsculas, números, _ e -, começando por letra ou número"
export COMPOSE_PROJECT_NAME="$projeto"
# Banco ativo (spec 009 R15, T5.4c): `banco` até a troca, `banco_novo` depois. Valor fora da lista vira nome de serviço: recusa.
banco_srv=banco
if [[ -f "$dir/banco-ativo" ]]; then banco_srv="$(cat "$dir/banco-ativo")"; fi
[[ "$banco_srv" == banco || "$banco_srv" == banco_novo ]] || erro "$dir/banco-ativo tem valor inválido"
# O serviço `banco_novo` só existe com o profile da troca: sem ele o compose não o enxerga.
if [[ "$banco_srv" == banco_novo ]]; then export COMPOSE_PROFILES=troca-banco; fi
# Troca de banco interrompida: recusa antes do Docker (o trocar-banco.sh faz o backup dele antes de gravar o marcador).
[[ ! -e "$dir/troca-banco-em-curso" ]] || erro "troca de banco interrompida (marcador $dir/troca-banco-em-curso): reconcilie antes de implantar"
# Destino do compose igual ao `banco-ativo` (ver implantar.sh): banco_novo vai ao ambiente; divergência recusa. Só essa chave é lida.
# Valor do `.env` como o Compose o lê: aspas que cercam o valor saem e " #comentário" depois dele é cortado.
valor_env() {
  local v="$1"
  v="${v#"${v%%[![:space:]]*}"}"
  if [[ "$v" =~ ^\"([^\"]*)\" || "$v" =~ ^\'([^\']*)\' ]]; then v="${BASH_REMATCH[1]}"; else v="${v%%[[:space:]]#*}"; v="${v%"${v##*[![:space:]]}"}"; fi
  printf '%s' "$v"
}
# Precedência do Compose (doc: https://docs.docker.com/compose/how-tos/environment-variables/envvars-precedence/; medido com o
# Docker 29.10.1): variável do shell vence o `.env`, mesmo vazia (vazia cai no padrão banco); no `.env` a última linha vence.
destino_arq="$(valor_env "$(grep '^PHATI_BANCO_DESTINO=' "$dir/.env" 2>/dev/null | tail -n 1 | cut -d= -f2- || true)")"
if [[ -n "${PHATI_BANCO_DESTINO+x}" ]]; then
  [[ "${PHATI_BANCO_DESTINO:-banco}" == "$banco_srv" ]] || erro "estado de banco divergente: ambiente aponta ${PHATI_BANCO_DESTINO:-banco}, banco-ativo $banco_srv"
fi
if [[ "$banco_srv" == banco_novo ]]; then
  [[ -z "$destino_arq" || "$destino_arq" == banco_novo ]] || erro "estado de banco divergente: .env aponta $destino_arq, banco-ativo banco_novo"
else
  [[ "$destino_arq" != banco_novo ]] || erro "estado de banco divergente: .env aponta banco_novo, banco-ativo não"
  [[ -z "$destino_arq" || "$destino_arq" == banco ]] || erro "estado de banco divergente: .env aponta $destino_arq, banco-ativo banco"
fi
# O valor conferido é o que o compose recebe: o ambiente exportado vence o `.env` também lá.
export PHATI_BANCO_DESTINO="$banco_srv"
# Modo lógico concluído (banco-logico, spec 009 E5): o override wal_level entra em todo compose, como no implantar.sh.
extra_logica=()
if [[ -f "$dir/banco-logico" ]]; then
  [[ -f "$dir/repo/servidor/compose.troca-logica.yaml" ]] || erro "banco-logico existe, mas $dir/repo/servidor/compose.troca-logica.yaml não está no clone"
  extra_logica=(-f "$dir/repo/servidor/compose.troca-logica.yaml")
fi
mkdir -p "$dir/backups"
# Grava num arquivo parcial e só o promove ao nome final se o dump deu certo: uma falha nunca apaga um dump válido que
# tenha o mesmo nome (mesmo segundo e rótulo), e o parcial não casa com `*.dump` da retenção nem do restaurar.sh.
parcial="$(mktemp "$dir/backups/.parcial.XXXXXX")"
trap 'rm -f -- "$parcial"' EXIT
arquivo="$dir/backups/phati-$(date -u +%Y%m%dT%H%M%SZ)-$rotulo.dump"
# As credenciais ficam no ambiente do contêiner do banco; nada delas passa por este script nem pela saída.
# O prazo evita que um Docker ou banco travado segure a trava da implantação para sempre; `-k` mata de vez quem ignorar o TERM.
if ! timeout -k "${PHATI_BACKUP_ABATE:-10}" "${PHATI_BACKUP_LIMITE:-1800}" "$docker" compose --env-file "$dir/.env" -f "$dir/repo/servidor/compose.yaml" -f "$dir/repo/servidor/compose.implantacao.yaml" ${extra_logica[@]+"${extra_logica[@]}"} exec -T "$banco_srv" sh -c 'PGPASSWORD="$PHATI_BANCO_DONO_SENHA" pg_dump -h 127.0.0.1 -U "$PHATI_BANCO_DONO_USUARIO" -Fc "$PHATI_BANCO_NOME"' > "$parcial"; then
  erro "pg_dump falhou ou passou do prazo (banco parado?)"
fi
[[ -s "$parcial" ]] || erro "backup vazio: $arquivo"
mv -f -- "$parcial" "$arquivo"
# Leitura linha a linha (não xargs): caminho com espaço não vira dois argumentos.
ls -1t "$dir"/backups/*.dump | tail -n +15 | while IFS= read -r antigo; do rm -f -- "$antigo"; done
echo "$arquivo"
