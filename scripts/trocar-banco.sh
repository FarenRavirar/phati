#!/usr/bin/env bash
# Troca de banco (spec 009 R15, R17, R18, R8). Roda na VM, como o implantar.sh: `trocar-banco.sh <preparar|trocar>`.
# `preparar`: precondições, backup verificado (R8), papel `replicador`, PAUSE nos dois PgBouncer, banco recriado com
# `wal_level=logical` (decisões 2 e 12 do plan.md §Registro R15), RESUME.
# `trocar`: sobe o `banco_novo`, backup verificado, esquema (só se o destino não tem tabelas de usuário), publicação com
# lista explícita (sem tabelas de extensão do PostGIS), assinatura lógica, espera sincronia, verificador SCRAM do papel do app
# copiado da origem (o PgBouncer autentica pelo `userlist.txt` gerado com o verificador da origem; salt diferente no destino),
# PAUSE, lag zero, DISABLE, sequências com margem, host novo nos dois PgBouncer, RESUME, DROP SUBSCRIPTION, DROP PUBLICATION
# na origem e gravação do destino.
# O RESUME roda sempre que o script pausou (trap ERR e EXIT): a app não pode ficar presa em PAUSE.
# Sem rollback automático depois do RESUME da troca: o host novo já atende a app; falha depois disso vira AVISO com o
# comando de recuperação. Antes desse RESUME, qualquer falha restaura o `host=` anterior, remove a assinatura e a
# publicação e sai rc 1.
# Variáveis: PHATI_DIR (padrão /opt/phati, com `.env`, `repo/` e `backups/`), DOCKER (para teste), PHATI_PROJETO, PHATI_FLOCK,
# PHATI_TRAVA_LIMITE (padrão 3600), PHATI_ESPERA e PHATI_TENTATIVAS (esperas), PHATI_MARGEM_SEQ (padrão 1000).
# Nenhum argumento além do subcomando.
# Segredo: a senha do `replicador` vai só ao ambiente do `exec` (`-e NOME`, sem valor na linha de comando) e ao `\getenv`
# do psql; nunca à saída nem ao registro. O stderr do psql é descartado porque ele pode ecoar a instrução com a senha.
# -E: o trap ERR vale dentro de funções; sem ele, falha do Docker sairia calada.
set -Eeuo pipefail

sub="${1:-}"
dir="${PHATI_DIR:-/opt/phati}"
docker="${DOCKER:-docker}"
registro="$dir/implantacoes.log"
ORIG=banco
NOVO=banco_novo
PUB=phati_troca_pub
SUB=phati_troca_sub
# Tabelas de public que são do usuário: exclui as de extensão (PostGIS, spatial_ref_sys) pelo pg_depend (deptype 'e').
FROM_TABELAS="FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind IN ('r','p') AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')"
# Estado do passo atual (usado na mensagem do trap ERR) e do PAUSE (RESUME garantido por `resumir_pgb`).
passo=inicio
pausado=0
pausa_t0=0
estado=""
backup_arquivo=""
ja_logical=0
# Estado da troca: host reescrito nos PgBouncer, assinatura criada no destino, publicação criada na origem, ponto sem volta
# (RESUME da troca).
host_trocado=0
assinatura=0
publicacao=0
comitado=0

registrar() {
  printf '%s troca-banco %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$sub" "$*" >> "$registro" 2>/dev/null || true
}
erro() {
  echo "ERRO: $*" >&2
  restaurar_host
  resumir_pgb
  limpar_assinatura
  limpar_publicacao
  registrar "FALHOU: $*"
  exit 1
}
# Compose com os mesmos arquivos do implantar.sh. O `PHATI_ALVO_DIR` é exigido pelo compose (monta o nginx), então é exportado.
compor() { "$docker" compose --env-file "$dir/.env" -f "$dir/repo/servidor/compose.yaml" -f "$dir/repo/servidor/compose.implantacao.yaml" "$@"; }
# Ordem: ambiente, `.env` da VM, padrão $dir/alvo (igual ao implantar.sh e ao backup.sh).
alvo_dir="${PHATI_ALVO_DIR:-}"
[[ -n "$alvo_dir" ]] || alvo_dir="$(grep -m1 '^PHATI_ALVO_DIR=' "$dir/.env" 2>/dev/null | cut -d= -f2- || true)"
export PHATI_ALVO_DIR="${alvo_dir:-$dir/alvo}"

saudavel_agora() {
  local id
  id="$(compor ps -q "$1" 2>/dev/null || true)"
  [[ -n "$id" && "$("$docker" inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || true)" == healthy ]]
}
# Espera a saúde por laço de `docker inspect`, como o implantar.sh (não usa `up --wait`: espera o projeto inteiro).
esperar_saude() {
  local _ id
  estado=""
  for _ in $(seq "${PHATI_TENTATIVAS:-60}"); do
    id="$(compor ps -q "$1" 2>/dev/null || true)"
    [[ -z "$id" ]] || estado="$("$docker" inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || true)"
    [[ "$estado" == healthy ]] && return 0
    sleep "${PHATI_ESPERA:-2}"
  done
  return 1
}
# Valor de `wal_level` do banco (só leitura). Falha do exec sai com rc diferente de 0.
consultar_wal() {
  compor exec -T banco sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -At -h 127.0.0.1 -U postgres -d postgres -c "SHOW wal_level"'
}
# psql no banco do serviço $1 com as opções seguintes. SQL vai por `-c` (leitura) ou por stdin (`-f -`). Stderr descartado:
# o psql pode ecoar a instrução, e ela leva a senha do replicador na criação da assinatura.
sql_em() {
  local svc="$1"
  shift
  compor exec -T "$svc" sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -U postgres -d phati "$@"' sh "$@" 2>/dev/null
}
# Console admin do PgBouncer de uma instância ($1), por `psql` no próprio contêiner. O socket é `/tmp/pgb/<instância>`, o padrão
# do entrypoint.sh (PGB_RAIZ não vem no compose). `-U pgbouncer` é obrigatório: sem ele o psql falha (medido no ensaio).
pgb_console() {
  compor exec -T "$1" psql -X -q -h "/tmp/pgb/$1" -p 6432 -U pgbouncer pgbouncer -c "$2" >/dev/null
}
# Reescreve a linha `host=` do pgbouncer.ini da instância $1 (gerado pelo entrypoint.sh em /tmp/pgb/<instância>).
pgb_sed() {
  compor exec -T "$1" sed -i "$2" "/tmp/pgb/$1/pgbouncer.ini"
}
# RESUME nos dois processos sempre que o script pausou. Não chama `erro` (evita laço): quem chama decide. Falha aparece em AVISO.
resumir_pgb() {
  [[ "$pausado" == 1 ]] || return 0
  local svc falhou=""
  for svc in pgb1 pgb2; do
    pgb_console "$svc" RESUME || falhou+=" $svc"
  done
  if [[ -z "$falhou" ]]; then
    pausado=0
  else
    echo "AVISO: RESUME falhou em:$falhou; o PgBouncer pode seguir em PAUSE: rode RESUME nos dois processos à mão" >&2
  fi
}
pausar_pgb() {
  pausado=1
  pgb_console pgb1 PAUSE || erro "não consegui pausar pgb1 pelo console"
  pgb_console pgb2 PAUSE || erro "não consegui pausar pgb2 pelo console"
  pausa_t0="$(date +%s%3N)"
}
# Antes do RESUME da troca: devolve o `host=` anterior nos dois PgBouncer e recarrega. Depois do RESUME não há rollback.
restaurar_host() {
  [[ "$host_trocado" == 1 && "$comitado" == 0 ]] || return 0
  local svc ok=1
  for svc in pgb1 pgb2; do pgb_sed "$svc" "s/host=$NOVO /host=$ORIG /" || ok=0; done
  for svc in pgb1 pgb2; do pgb_console "$svc" RELOAD || ok=0; done
  if [[ "$ok" == 1 ]]; then
    host_trocado=0
  else
    echo "AVISO: não consegui restaurar host=$ORIG nos PgBouncer: confira pgbouncer.ini e rode RELOAD" >&2
  fi
}
# Remove a assinatura do destino (e o slot na origem) quando a troca não chegou ao RESUME.
limpar_assinatura() {
  [[ "$assinatura" == 1 && "$comitado" == 0 ]] || return 0
  if sql_em "$NOVO" -f - >/dev/null 2>&1 <<SQL
ALTER SUBSCRIPTION $SUB DISABLE;
DROP SUBSCRIPTION $SUB;
SQL
  then
    assinatura=0
  else
    echo "AVISO: não consegui remover a assinatura no $NOVO: rode ALTER SUBSCRIPTION $SUB DISABLE; e DROP SUBSCRIPTION $SUB;" >&2
  fi
}
# Remove a publicação da origem (aborto e fim com sucesso). Idempotente (IF EXISTS). Falha vira AVISO: não derruba a troca.
limpar_publicacao() {
  [[ "$publicacao" == 1 ]] || return 0
  if sql_em "$ORIG" -f - >/dev/null 2>&1 <<SQL
DROP PUBLICATION IF EXISTS $PUB;
SQL
  then
    publicacao=0
  else
    echo "AVISO: não consegui remover a publicação $PUB no $ORIG: rode DROP PUBLICATION IF EXISTS $PUB; no $ORIG" >&2
  fi
}

# Trava igual à do implantar.sh: uma operação por vez. O script roda de novo sob `flock`; 75 vira erro com mensagem.
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
    echo "ERRO: outra operação de banco ou implantação segue rodando (trava em $dir/.trava)" >&2
    registrar "FALHOU: trava ocupada"
    exit 1
  fi
  exit "$rc"
}

# Precondições da VM (comuns a preparar e trocar): `.env` com a senha, clone, compose e PgBouncer/banco saudáveis.
checar_vm() {
  [[ -f "$dir/.env" ]] || erro "$dir/.env ausente (segredos ficam só na VM)"
  # Checa só o nome: `grep -q` não imprime nada. O valor vai ao `exec` pela variável exportada logo abaixo.
  grep -q '^PHATI_BANCO_REPLICADOR_SENHA=.' "$dir/.env" || erro "PHATI_BANCO_REPLICADOR_SENHA ausente ou vazia no .env"
  PHATI_BANCO_REPLICADOR_SENHA="$(grep -m1 '^PHATI_BANCO_REPLICADOR_SENHA=' "$dir/.env" | cut -d= -f2-)"
  export PHATI_BANCO_REPLICADOR_SENHA
  [[ -d "$dir/repo/.git" ]] || erro "$dir/repo não é um clone do repositório"
  [[ -f "$dir/repo/servidor/compose.implantacao.yaml" ]] || erro "compose de implantação ausente no clone"
  [[ -f "$dir/repo/servidor/banco/papeis.sql" ]] || erro "papeis.sql ausente no clone"
  saudavel_agora pgb1 && saudavel_agora pgb2 || erro "PgBouncer indisponível: pgb1 e pgb2 precisam estar saudáveis antes da troca"
  saudavel_agora banco || erro "banco não está saudável: nada foi feito"
}
# Backup verificado antes de qualquer alteração (R8). O backup.sh ignora o argumento `preparar-troca` (não tem despacho).
backup_verificado() {
  backup_arquivo="$(PHATI_DIR="$dir" DOCKER="$docker" bash "$(dirname "$0")/backup.sh" preparar-troca)" || erro "backup verificado falhou: nada foi alterado"
  [[ -s "$backup_arquivo" ]] || erro "backup ausente ou vazio: nada foi alterado"
}

preparar() {
  passo=precondicoes
  checar_vm
  wal="$(consultar_wal)" || erro "não consegui ler wal_level do banco"
  [[ "$wal" == logical ]] && ja_logical=1

  passo=backup
  backup_verificado

  passo=replicador
  compor exec -T -e PHATI_BANCO_REPLICADOR_SENHA banco sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -U postgres -d postgres -f -' < "$dir/repo/servidor/banco/papeis.sql" >/dev/null 2>&1 \
    || erro "SQL do papel replicador falhou (saída suprimida: contém a senha)"

  if [[ "$ja_logical" == 1 ]]; then
    registrar "OK ja_logical=1"
    echo "preparar_ok ja_logical=1"
    return 0
  fi

  passo=pausa
  pausar_pgb
  passo=banco-reinicio
  compor up -d --no-deps banco >/dev/null || erro "não consegui recriar o banco com wal_level=logical"
  esperar_saude banco || erro "banco não voltou saudável depois do reinício (estado: ${estado:-desconhecido})"
  passo=wal-level
  wal="$(consultar_wal)" || erro "não consegui ler wal_level depois do reinício"
  [[ "$wal" == logical ]] || erro "wal_level não virou logical (valor: $wal)"
  passo=resume
  resumir_pgb
  [[ "$pausado" == 0 ]] || erro "RESUME falhou no PgBouncer"
  pausa_ms=$(( $(date +%s%3N) - pausa_t0 ))
  registrar "OK pausa_ms=$pausa_ms"
  echo "preparar_ok pausa_ms=$pausa_ms"
}

# Espera o `srsubstate` = 'r' em todas as tabelas da assinatura (e exige ao menos uma).
esperar_sincronia() {
  local _ r
  for _ in $(seq "${PHATI_TENTATIVAS:-60}"); do
    r="$(sql_em "$NOVO" -At -c "SELECT count(*) FILTER (WHERE rel.srsubstate = 'r') || '/' || count(*) FROM pg_subscription_rel rel JOIN pg_subscription s ON s.oid = rel.srsubid WHERE s.subname = '$SUB'" || true)"
    if [[ "$r" =~ ^([0-9]+)/([0-9]+)$ ]] && (( BASH_REMATCH[2] > 0 && BASH_REMATCH[1] == BASH_REMATCH[2] )); then
      return 0
    fi
    sleep "${PHATI_ESPERA:-2}"
  done
  return 1
}
# Espera o destino passar o LSN $1 da origem (com PAUSE ativo, o lag tem de chegar a zero).
esperar_lag() {
  local _ ok
  for _ in $(seq "${PHATI_TENTATIVAS:-60}"); do
    ok="$(sql_em "$NOVO" -At -c "SELECT pg_wal_lsn_diff(latest_end_lsn, '$1') >= 0 AND pg_wal_lsn_diff(received_lsn, '$1') >= 0 FROM pg_stat_subscription WHERE subname = '$SUB'" || true)"
    [[ "$ok" == t ]] && return 0
    sleep "${PHATI_ESPERA:-2}"
  done
  return 1
}
# Grava o destino no `.env` de forma atômica: arquivo temporário no mesmo diretório, com o modo e o dono do `.env`.
gravar_env_destino() {
  local tmp
  tmp="$(mktemp "$dir/.env.XXXXXX")"
  chmod --reference="$dir/.env" "$tmp"
  chown --reference="$dir/.env" "$tmp" 2>/dev/null || true
  { grep -v '^PHATI_BANCO_DESTINO=' "$dir/.env" || true; printf 'PHATI_BANCO_DESTINO=%s\n' "$NOVO"; } > "$tmp" || { rm -f "$tmp"; erro "não consegui gravar o .env"; }
  mv -f "$tmp" "$dir/.env"
}
gravar_banco_ativo() {
  local tmp
  tmp="$(mktemp "$dir/.banco-ativo.XXXXXX")"
  printf '%s\n' "$NOVO" > "$tmp" && mv -f "$tmp" "$dir/banco-ativo" || { rm -f "$tmp"; erro "não consegui gravar banco-ativo"; }
}

# Hash sha256 do verificador SCRAM do papel $2 no serviço $1 (só leitura: o valor não sai do banco). Vazio = sem senha.
hash_verificador() {
  sql_em "$1" -At -v "papel=$2" -f - <<'SQL'
SELECT encode(sha256(convert_to(rolpassword, 'UTF8')), 'hex') FROM pg_authid WHERE rolname = :'papel';
SQL
}
# O PgBouncer autentica o papel do app pelo verificador SCRAM da origem (userlist.txt gravado por pgb_auth, com o salt da
# origem). O destino criou o papel pelo init com outro salt: copia o verificador para o destino e confere o hash. Roda depois
# da sincronia e antes do PAUSE; falha aborta. O verificador vai da origem ao destino por pipe: nunca em variável, argumento
# ou saída.
copiar_verificador() {
  local papel="$1" h_origem h_novo
  h_origem="$(hash_verificador "$ORIG" "$papel")" && [[ -n "$h_origem" ]] || erro "verificador SCRAM de $papel ausente no $ORIG: nada pausado"
  sql_em "$ORIG" -At -v "papel=$papel" -f - <<'SQL' | sql_em "$NOVO" -f - || erro "verificador de $papel não copiado para o $NOVO: nada pausado"
SELECT format('ALTER ROLE %I PASSWORD %L', rolname, rolpassword) FROM pg_authid WHERE rolname = :'papel' AND rolpassword LIKE 'SCRAM-SHA-256$%';
SQL
  h_novo="$(hash_verificador "$NOVO" "$papel")" || erro "não consegui ler o verificador de $papel no $NOVO: nada pausado"
  [[ "$h_novo" == "$h_origem" ]] || erro "verificador de $papel no $NOVO difere da origem: nada pausado"
}

trocar() {
  # Só o `trocar` usa o profile: o `banco_novo` fica fora dos outros subcomandos.
  export COMPOSE_PROFILES=troca-banco
  passo=precondicoes
  local margem="${PHATI_MARGEM_SEQ:-1000}" ativo atual wal lista n lsn pausa_ms r papel_app
  [[ "$margem" =~ ^[0-9]{1,15}$ ]] || { echo "ERRO: PHATI_MARGEM_SEQ inválida: use inteiro maior ou igual a 0" >&2; exit 1; }
  ativo="$(cat "$dir/banco-ativo" 2>/dev/null || true)"
  if [[ "$ativo" == "$NOVO" ]]; then
    registrar "OK ja_trocado=1"
    echo "trocar_ok ja_trocado=1"
    return 0
  fi
  checar_vm
  # Único papel que o pgb_auth grava no userlist.txt: o do app (compose: PHATI_BANCO_APP_USUARIO). Nome validado antes de qualquer SQL.
  papel_app="${PHATI_BANCO_APP_USUARIO:-}"
  [[ -n "$papel_app" ]] || papel_app="$(grep -m1 '^PHATI_BANCO_APP_USUARIO=' "$dir/.env" | cut -d= -f2- || true)"
  [[ "$papel_app" =~ ^[a-z_][a-z0-9_]*$ ]] || erro "PHATI_BANCO_APP_USUARIO ausente ou inválido: nada foi feito"
  atual="$(grep -m1 '^PHATI_BANCO_DESTINO=' "$dir/.env" | cut -d= -f2- || true)"
  [[ -z "$atual" || "$atual" == "$ORIG" ]] || erro "PHATI_BANCO_DESTINO é '$atual', esperado $ORIG: nada foi feito"
  wal="$(consultar_wal)" || erro "não consegui ler wal_level do banco"
  [[ "$wal" == logical ]] || erro "wal_level não é logical: rode preparar antes (valor: $wal)"

  passo=banco-novo
  compor up -d --no-deps "$NOVO" >/dev/null || erro "não consegui subir o $NOVO"
  esperar_saude "$NOVO" || erro "$NOVO não voltou saudável (estado: ${estado:-desconhecido}): nada foi alterado"

  passo=backup
  backup_verificado

  passo=esquema
  n="$(sql_em "$NOVO" -At -c "SELECT count(*) $FROM_TABELAS")" || erro "não consegui contar tabelas do $NOVO"
  if [[ "$n" == 0 ]]; then
    compor exec -T "$ORIG" sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h 127.0.0.1 -U postgres --schema-only -d phati' \
      | sql_em "$NOVO" -f - || erro "esquema não aplicado no $NOVO"
  else
    echo "AVISO: $NOVO já tem tabelas de usuário em public: esquema não aplicado" >&2
  fi

  passo=publicacao
  lista="$(sql_em "$ORIG" -At -c "SELECT coalesce(string_agg(format('%I.%I', n.nspname, c.relname), ', '), '') $FROM_TABELAS")" || erro "não consegui listar as tabelas da origem"
  [[ -n "$lista" ]] || erro "lista de tabelas vazia: nada a publicar"
  publicacao=1  # antes do CREATE: se ele falhar no meio, o DROP IF EXISTS do aborto limpa
  sql_em "$ORIG" -f - <<SQL || erro "publicação não criada na origem"
SELECT format('CREATE PUBLICATION %I FOR TABLE %s', '$PUB', string_agg(format('%I.%I', n.nspname, c.relname), ', ')) $FROM_TABELAS \gexec
SQL

  passo=assinatura
  # A senha vai ao psql por `\getenv` (sem valor na linha de comando); a saída é suprimida: a instrução pode ecoar a senha.
  compor exec -T -e PHATI_BANCO_REPLICADOR_SENHA "$NOVO" sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -U postgres -d phati -f -' >/dev/null 2>&1 <<SQL || erro "assinatura não criada no $NOVO (saída suprimida: contém a senha)"
\getenv senha PHATI_BANCO_REPLICADOR_SENHA
SELECT format('CREATE SUBSCRIPTION %I CONNECTION %L PUBLICATION %I', '$SUB', 'host=$ORIG port=5432 dbname=phati user=replicador password=' || :'senha', '$PUB') \gexec
SQL
  assinatura=1

  passo=sincronia
  esperar_sincronia || erro "sincronização não chegou a 'r' em todas as tabelas: nada foi pausado"

  passo=verificador
  copiar_verificador "$papel_app"

  passo=pausa
  pausar_pgb
  passo=lag
  lsn="$(sql_em "$ORIG" -At -c 'SELECT pg_current_wal_lsn()')" || erro "não consegui ler o LSN da origem"
  [[ "$lsn" =~ ^[0-9A-Fa-f]+/[0-9A-Fa-f]+$ ]] || erro "LSN da origem em formato inesperado: nada trocado"
  esperar_lag "$lsn" || erro "destino não alcançou o LSN da origem com PAUSE ativo: nada trocado"

  passo=desabilita
  sql_em "$NOVO" -f - <<SQL || erro "não consegui desabilitar a assinatura"
ALTER SUBSCRIPTION $SUB DISABLE;
SQL

  passo=sequencias
  # Sequências não replicam: cada uma vai para last_value + margem (margem + 1 se nunca foi usada). Falha aborta antes do host.
  sql_em "$ORIG" -At -v "margem=$margem" -f - <<'SQL' | sql_em "$NOVO" -f - || erro "sequências não ajustadas no $NOVO: nada trocado"
SELECT format('SELECT setval(%L, %s, true);', schemaname || '.' || sequencename, CASE WHEN last_value IS NULL THEN :'margem'::bigint + 1 ELSE last_value + :'margem'::bigint END) FROM pg_sequences WHERE schemaname = 'public';
SQL

  passo=host
  host_trocado=1
  for r in pgb1 pgb2; do pgb_sed "$r" "s/host=$ORIG /host=$NOVO /" || erro "não consegui trocar o host em $r"; done
  passo=reload
  for r in pgb1 pgb2; do pgb_console "$r" RELOAD || erro "RELOAD falhou em $r"; done

  passo=resume
  comitado=1
  resumir_pgb
  [[ "$pausado" == 0 ]] || erro "RESUME falhou depois da troca de host: sem rollback automático (ver AVISO)"
  pausa_ms=$(( $(date +%s%3N) - pausa_t0 ))

  passo=limpeza
  if sql_em "$NOVO" -f - >/dev/null <<SQL
DROP SUBSCRIPTION $SUB;
SQL
  then
    assinatura=0
  else
    echo "AVISO: DROP SUBSCRIPTION falhou no $NOVO: rode DROP SUBSCRIPTION $SUB; (o slot fica na origem até lá)" >&2
  fi
  limpar_publicacao

  passo=persistir
  gravar_env_destino
  gravar_banco_ativo
  registrar "OK pausa_ms=$pausa_ms destino=$NOVO"
  echo "trocar_ok pausa_ms=$pausa_ms"
}

# Subcomando é a única entrada externa: validado antes de qualquer ação e antes da trava.
case "$sub" in
  preparar|trocar) ;;
  *) echo "ERRO: subcomando inválido: use preparar ou trocar" >&2; exit 1 ;;
esac
[[ $# -eq 1 ]] || { echo "ERRO: opção desconhecida: $sub não aceita argumentos" >&2; exit 1; }
projeto="${PHATI_PROJETO:-phati}"
[[ "$projeto" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || { echo "ERRO: PHATI_PROJETO inválido" >&2; exit 1; }
export COMPOSE_PROJECT_NAME="$projeto"
travar "$@"

trap 'erro "falhou no passo: $passo"' ERR
trap 'resumir_pgb' EXIT
case "$sub" in
  preparar) preparar ;;
  trocar) trocar ;;
esac
