#!/usr/bin/env bash
# Troca de banco (spec 009 R15, R17, R18, R8). Roda na VM, como o implantar.sh: `trocar-banco.sh <preparar|trocar>`.
# `preparar`: precondições, backup verificado (R8), papel `replicador`, PAUSE nos dois PgBouncer, banco recriado com
# `wal_level=logical` (decisões 2 e 12 do plan.md §Registro R15), RESUME. Sempre lógico: soma `compose.troca-logica.yaml`.
# `trocar --modo fisica|logica` (padrão fisica, spec 009 R15, S2b). Dois modos:
#   fisica: standby físico por pg_basebackup do banco ativo, sem `preparar` e sem reiniciar a origem. Não soma o override.
#     Pré-requisitos: volume dados_banco_novo vazio e mesmo major da origem. Promove o standby (pg_promote) e troca o host.
#   logica: o fluxo abaixo (publicação e assinatura lógica). Soma `compose.troca-logica.yaml` (o `banco` é recriado com
#     `wal_level=logical`) e exige `preparar` antes.
# `trocar` (modo lógico): sobe o `banco_novo`, backup verificado, esquema (recusa se o destino já tem tabelas de usuário), publicação com
# lista explícita (sem tabelas de extensão do PostGIS), assinatura lógica, espera sincronia, verificador SCRAM do papel do app
# copiado da origem (o PgBouncer autentica pelo `userlist.txt` gerado com o verificador da origem; salt diferente no destino),
# PAUSE, lag zero, origem somente leitura, DISABLE, sequências com margem, host novo nos dois PgBouncer, RESUME, DROP SUBSCRIPTION, DROP PUBLICATION
# na origem e gravação do destino.
# O RESUME roda sempre que o script pausou (trap ERR e EXIT): a app não pode ficar presa em PAUSE.
# Sem rollback automático depois do RESUME da troca: o host novo já atende a app; falha depois disso vira AVISO com o
# comando de recuperação. Antes desse RESUME, qualquer falha restaura o `host=` anterior, remove a assinatura e a
# publicação e sai rc 1.
# Destino para o PgBouncer: grava o NOVO (`banco_novo` na ida, `banco` na volta) em `/cfg/banco-destino` (volume pgb_cfg, por one-off do pgb_auth). O entrypoint
# lê esse arquivo ao subir e ele vence PHATI_BANCO_DESTINO, porque o ambiente do contêiner não muda com `docker restart`.
# Modo lógico: depois do RELOAD e antes do RESUME. Janela residual: entre o RELOAD e a gravação, um reinício do PgBouncer
# volta ao `banco` pela variável; com a origem somente leitura (item 2, lote 3) isso vira erro de escrita, não divergência
# silenciosa (a origem fica RO depois do lag zero). Modo físico: logo antes do pg_promote,
# com o banco_novo ainda standby (uma instância reiniciada nesta janela só erra escrita, não diverge). Falha da gravação
# aborta antes do RESUME. No aborto, o arquivo sai se a gravação foi tentada (`destino_pgb_gravado`); se a remoção falhar
# três vezes, o marcador da troca fica (`destino_pendente`).
# Sinais TERM, HUP e INT viram erro: passam pelo mesmo rollback antes do ponto sem volta (depois dele só retomam).
# `banco-logico` é gravado junto de `banco-ativo`, só no sucesso do modo lógico: os scripts de implantação somam o override
# `compose.troca-logica.yaml` quando ele existe (o `banco` recriado pelo deploy continua com wal_level=logical).
# Variáveis: PHATI_DIR (padrão /opt/phati, com `.env`, `repo/` e `backups/`), DOCKER (para teste), PHATI_PROJETO, PHATI_BANCO_NOME
# (ambiente, depois `.env`, padrão phati; usado em todas as conexões), PHATI_FLOCK,
# PHATI_TRAVA_LIMITE (padrão 3600), PHATI_ESPERA e PHATI_TENTATIVAS (esperas), PHATI_MARGEM_SEQ (padrão 1000),
# PHATI_TROCA_MODO (padrão fisica; `--modo` na linha de comando tem prioridade). Argumentos: `trocar --modo <valor>` e
# `limpar-destino <banco|banco_novo>` (remove o banco inativo, contêiner e volume; único subcomando que apaga volume). A direção é
# dinâmica (volta): ORIG é o banco ativo gravado em banco-ativo e NOVO o outro (`resolver_direcao`).
# Segredo: a senha do `replicador` vai só ao ambiente do `exec` (`-e NOME`, sem valor na linha de comando) e ao `\getenv`
# do psql; nunca à saída nem ao registro. O stderr do psql é descartado porque ele pode ecoar a instrução com a senha.
# -E: o trap ERR vale dentro de funções; sem ele, falha do Docker sairia calada.
set -Eeuo pipefail

sub="${1:-}"
dir="${PHATI_DIR:-/opt/phati}"
docker="${DOCKER:-docker}"
registro="$dir/implantacoes.log"
# Par de bancos (spec 009 R15, volta): ORIG é o banco ativo e NOVO o outro. Vêm de `resolver_direcao` (depois da trava): com
# marcador de troca em curso, o marcador grava origem e destino; sem ele, ORIG é o `banco-ativo` (padrão banco). Nada de literal fixo.
ORIG=""
NOVO=""
PUB=phati_troca_pub
SUB=phati_troca_sub
# Passfile do libpq no banco_novo: a conninfo da assinatura aponta para ele, sem senha no SQL. Sai só depois do DROP SUBSCRIPTION.
PGPASS=/tmp/phati-replicador.pgpass
# Tabelas de public que são do usuário: exclui as de extensão (PostGIS, spatial_ref_sys) pelo pg_depend (deptype 'e').
FROM_TABELAS="FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND c.relkind IN ('r','p') AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')"
# Estado do passo atual (usado na mensagem do trap ERR) e do PAUSE (RESUME garantido por `resumir_pgb`).
passo=inicio
pausado=0
pausa_t0=0
estado=""
backup_arquivo=""
ja_logical=0
# Modo da troca: fisica (padrão) ou logica. Só `logica` soma o override de wal_level; `preparar` é sempre lógico.
modo="${PHATI_TROCA_MODO:-fisica}"
# Estado da troca física: slot do standby na origem, banco_novo (ou volume parcial) criado por nós, banco_novo promovido.
SLOT=phati_troca_slot
fisico_slot=0
novo_criado=0
promovido=0
# Estado da troca: host reescrito nos PgBouncer, assinatura criada no destino, publicação criada na origem, ponto sem volta
# (RESUME da troca).
host_trocado=0
# Tentativa da gravação do destino no volume pgb_cfg: posta ANTES do one-off, para o aborto remover mesmo com falha parcial.
destino_pgb_gravado=0
assinatura=0
# Origem somente leitura desde antes do DISABLE (modo lógico, item 2): o aborto devolve a escrita; o sucesso a deixa.
origem_ro=0
pgpass_criado=0
publicacao=0
comitado=0
# Host confirmado de volta por instância (1 = sem host pendente). Quem não confirma fica em PAUSE (ver resumir_pgb).
host_ok_pgb1=1
host_ok_pgb2=1
# RESUME já feito por instância: o EXIT roda de novo e não repete o que deu certo (ver resumir_pgb).
resumido_pgb1=0
resumido_pgb2=0
# Standby físico iniciado (antes do `up`): o aborto o para antes de largar o slot. Destino que não pôde ser removido: o marcador fica.
standby_iniciado=0
destino_pendente=0
# Temporários da gravação atômica (.env e banco-ativo): o EXIT remove o que sobrar.
tmp_env=""
tmp_banco=""
# Marcador da troca em curso: gravado antes do PAUSE, removido no sucesso e no aborto completo.
marcador="$dir/troca-banco-em-curso"

registrar() {
  printf '%s troca-banco %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$sub" "$*" >> "$registro" 2>/dev/null || true
}
# Valor de `NOME` no `.env` (primeira linha `NOME=`), sem as aspas que cercam o valor inteiro; espaços internos ficam. Devolve só
# pela captura (`$(ler_env NOME)`): nunca imprime, para o segredo não sair em log.
ler_env() {
  local valor
  valor="$(grep -m1 "^$1=" "$dir/.env" 2>/dev/null | cut -d= -f2- || true)"
  # Como o Compose lê (igual ao valor_env do implantar.sh): espaços iniciais saem; aspas que cercam o valor saem e ` #comentário`
  # depois dele é cortado; sem aspas, espaços finais saem também.
  valor="${valor#"${valor%%[![:space:]]*}"}"
  if [[ "$valor" =~ ^\"([^\"]*)\" || "$valor" =~ ^\'([^\']*)\' ]]; then valor="${BASH_REMATCH[1]}"; else valor="${valor%%[[:space:]]#*}"; valor="${valor%"${valor##*[![:space:]]}"}"; fi
  printf '%s' "$valor"
}
erro() {
  echo "ERRO: $*" >&2
  restaurar_host
  restaurar_origem
  restaurar_destino
  resumir_pgb
  limpar_assinatura
  remover_pgpass
  limpar_publicacao
  limpar_fisico
  limpar_marcador
  registrar "FALHOU: $*"
  exit 1
}
# Banco ativo gravado em banco-ativo (padrão banco). Só leitura; quem usa valida o valor.
ativo_gravado() {
  local v=banco
  if [[ -f "$dir/banco-ativo" ]]; then v="$(cat "$dir/banco-ativo")"; fi
  printf '%s' "$v"
}
# Recusa antes de qualquer ação. Não usa `erro`: o `erro` apaga o marcador da troca, e aqui o marcador pode ser o que se recusa.
recusar() {
  echo "ERRO: $*" >&2
  exit 1
}
# Direção da troca (desenho da volta): ORIG = banco ativo, NOVO = o outro do par. Com marcador, o marcador manda (grava origem e
# destino); marcador sem os dois (formato anterior) recusa e não é apagado. Sem marcador, ORIG vem de banco-ativo e o destino do
# `.env` (vazio conta como banco, o padrão do compose) tem de ser ORIG: divergência recusa. Nunca recalcula a direção de um
# banco-ativo já gravado pela metade.
resolver_direcao() {
  local linha ativo env_dest efetivo re='^origem=(banco|banco_novo) destino=(banco|banco_novo) modo='
  if [[ -e "$marcador" ]]; then
    linha="$(head -n 1 "$marcador" 2>/dev/null || true)"
    if [[ "$linha" =~ $re && "${BASH_REMATCH[1]}" != "${BASH_REMATCH[2]}" ]]; then
      ORIG="${BASH_REMATCH[1]}"
      NOVO="${BASH_REMATCH[2]}"
      return 0
    fi
    # Marcador de versão anterior (`modo=... passo=...`, sem origem e destino): a versão que o gravou só fazia banco -> banco_novo
    # (ORIG e NOVO eram literais), então a direção é essa. O marcador novo sempre grava origem e destino (`marcar_troca`).
    if [[ "$linha" =~ ^modo=(fisica|logica)\ passo= ]]; then
      ORIG=banco
      NOVO=banco_novo
      return 0
    fi
    recusar "marcador $marcador inválido (sem origem, destino e modo): reconcilie à mão, grave origem e destino ou remova o marcador; nada foi feito"
  fi
  ativo="$(ativo_gravado)"
  [[ "$ativo" == banco || "$ativo" == banco_novo ]] || recusar "$dir/banco-ativo tem valor inválido: nada foi feito"
  env_dest="$(ler_env PHATI_BANCO_DESTINO)"
  efetivo="${env_dest:-banco}"
  [[ "$efetivo" == "$ativo" ]] || recusar "PHATI_BANCO_DESTINO é '$efetivo', esperado $ativo: nada foi feito (persistência parcial da troca: banco-ativo e .env divergem sem o marcador $marcador; reconcilie à mão antes de repetir)"
  ORIG="$ativo"
  if [[ "$ativo" == banco ]]; then NOVO=banco_novo; else NOVO=banco; fi
}
# Guarda explícita do stop/rm (desenho item 5): o serviço nunca é o banco ativo gravado nem o ORIG desta execução. Falso = não atinge.
# Não chama `erro` (o erro chama as limpezas, que chamariam esta guarda de novo).
guarda_inativo() {
  local svc="$1"
  [[ "$svc" != "$(ativo_gravado)" && "$svc" != "$ORIG" ]]
}

# Compose com os mesmos arquivos do implantar.sh. O `PHATI_ALVO_DIR` é exigido pelo compose (monta o nginx), então é exportado.
# O override de wal_level entra só no modo lógico ou no `preparar` (sempre lógico): ele recria o `banco` no `up`.
# $1 = segundos de limite ("" = sem limite): `timeout N` na frente do `docker` (PHATI_TIMEOUT). Sem o comando, AVISO e segue sem limite.
compor_limite() {
  local limite="$1" t="${PHATI_TIMEOUT:-timeout}" pre=() extra=()
  shift
  if [[ -n "$limite" ]]; then
    if command -v "$t" >/dev/null 2>&1; then pre=("$t" "$limite"); else echo "AVISO: '$t' ausente: sem limite de tempo no console do PgBouncer" >&2; fi
  fi
  if [[ "$sub" == preparar || "$modo" == logica ]]; then extra=(-f "$dir/repo/servidor/compose.troca-logica.yaml"); fi
  ${pre[@]+"${pre[@]}"} "$docker" compose --env-file "$dir/.env" -f "$dir/repo/servidor/compose.yaml" -f "$dir/repo/servidor/compose.implantacao.yaml" ${extra[@]+"${extra[@]}"} "$@"
}
compor() { compor_limite "" "$@"; }
# Ordem: ambiente, `.env` da VM, padrão $dir/alvo (igual ao implantar.sh e ao backup.sh).
alvo_dir="${PHATI_ALVO_DIR:-}"
[[ -n "$alvo_dir" ]] || alvo_dir="$(grep -m1 '^PHATI_ALVO_DIR=' "$dir/.env" 2>/dev/null | cut -d= -f2- || true)"
export PHATI_ALVO_DIR="${alvo_dir:-$dir/alvo}"

saudavel_agora() {
  local svc="$1" id
  id="$(compor ps -q "$svc" 2>/dev/null || true)"
  [[ -n "$id" && "$("$docker" inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || true)" == healthy ]]
}
# Espera a saúde por laço de `docker inspect`, como o implantar.sh (não usa `up --wait`: espera o projeto inteiro).
esperar_saude() {
  local svc="$1" _ id
  estado=""
  for _ in $(seq "${PHATI_TENTATIVAS:-60}"); do
    id="$(compor ps -q "$svc" 2>/dev/null || true)"
    [[ -z "$id" ]] || estado="$("$docker" inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || true)"
    [[ "$estado" == healthy ]] && return 0
    sleep "${PHATI_ESPERA:-2}"
  done
  return 1
}
# Valor de `wal_level` do banco (só leitura). Falha do exec sai com rc diferente de 0.
consultar_wal() {
  compor exec -T "$ORIG" sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -At -h 127.0.0.1 -U postgres -d postgres -c "SHOW wal_level"'
}
# psql no banco do serviço $1 com as opções seguintes. SQL vai por `-c` (leitura) ou por stdin (`-f -`). Stderr descartado:
# o psql pode ecoar a instrução com erro.
sql_em() {
  local svc="$1"
  shift
  compor exec -T "$svc" sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -U postgres -d '"$bdnome"' "$@"' sh "$@" 2>/dev/null
}
# Console admin do PgBouncer de uma instância ($1), por `psql` no próprio contêiner. O socket é `/tmp/pgb/<instância>`, o padrão
# do entrypoint.sh (PGB_RAIZ não vem no compose). `-U pgbouncer` é obrigatório: sem ele o psql falha (medido no ensaio).
pgb_console() {
  local limite=20 svc="$1" cmd="$2"
  if [[ "$cmd" == PAUSE ]]; then limite="${PHATI_PAUSA_LIMITE:-30}"; fi
  compor_limite "$limite" exec -T "$svc" psql -X -q -h "/tmp/pgb/$svc" -p 6432 -U pgbouncer pgbouncer -c "$cmd" >/dev/null
}
# Consulta de leitura no console do PgBouncer da instância $1 (SQL $2): saída crua no stdout e o rc do docker/psql. Sem pipe, para o rc
# não se perder; quem chama captura a saída e testa o rc separado.
pgb_consulta() {
  local svc="$1" sql="$2"
  compor_limite 20 exec -T "$svc" psql -X -A -h "/tmp/pgb/$svc" -p 6432 -U pgbouncer pgbouncer -c "$sql"
}
# Estado de pausa da instância $1 (linha `paused|<valor>` do SHOW STATE, formato real do psql -A): imprime 0 (`no`) ou 1 (`yes`).
# Qualquer outro valor, linha ausente ou consulta com erro saem com rc 1 e sem saída: desconhecido é falha.
pgb_pausado() {
  local svc="$1" saida valor
  saida="$(pgb_consulta "$svc" 'SHOW STATE')" || return 1
  valor="$(awk -F'|' '$1=="paused"{n++; v=$2} END{if(n==1) print v}' <<<"$saida")"
  case "$valor" in
    no) echo 0 ;;
    yes) echo 1 ;;
    *) return 1 ;;
  esac
}
# Host em execução da linha do banco da app ($bdnome) no SHOW DATABASES da instância $1. Imprime o host; vazio se a consulta falhar
# ou a linha não existir (sem confirmação, quem chama trata como host diferente).
pgb_host_app() {
  local svc="$1" saida
  saida="$(pgb_consulta "$svc" 'SHOW DATABASES')" || return 1
  awk -F'|' -v db="$bdnome" '$1==db{n++; h=$2} END{if(n==1) print h}' <<<"$saida"
}
# Reescreve a linha `host=` do pgbouncer.ini da instância $1 (gerado pelo entrypoint.sh em /tmp/pgb/<instância>).
pgb_sed() {
  local svc="$1" expr="$2"
  compor exec -T "$svc" sed -i "$expr" "/tmp/pgb/$svc/pgbouncer.ini"
}
# Só leitura: 0 se a linha `host=$ORIG ` (com espaço depois do nome, como o sed) está no pgbouncer.ini da instância $1.
ini_no_host_origem() {
  local svc="$1"
  compor exec -T "$svc" grep -q "host=$ORIG " "/tmp/pgb/$svc/pgbouncer.ini" >/dev/null 2>&1
}
# Destino para o entrypoint do PgBouncer: `/cfg/banco-destino` no volume pgb_cfg. Por one-off do pgb_auth, o único serviço com
# o volume em escrita (pgb1 e pgb2 montam em leitura). `--no-deps` evita subir o banco. O conteúdo é o `$NOVO` constante.
gravar_destino_pgb() {
  compor run --rm --no-deps -T --entrypoint sh pgb_auth -c "printf '%s\n' $NOVO > /cfg/banco-destino"
}
remover_destino_pgb() {
  compor run --rm --no-deps -T --entrypoint sh pgb_auth -c 'rm -f /cfg/banco-destino'
}
# Sem o arquivo, um reinício do PgBouncer volta à variável (origem). Só se a gravação foi tentada (sem tentativa não há arquivo, e o
# one-off de remoção seria uma chamada Docker à toa) e só antes do ponto sem volta. Três tentativas; se continuar falhando,
# `destino_pendente` mantém o marcador da troca (o aviso manda apagar o arquivo à mão).
restaurar_destino() {
  [[ "$destino_pgb_gravado" == 1 && "$comitado" == 0 ]] || return 0
  local _
  for _ in 1 2 3; do
    if remover_destino_pgb; then destino_pgb_gravado=0; return 0; fi
  done
  destino_pendente=1
  echo "AVISO: não consegui remover /cfg/banco-destino: apague o arquivo no volume pgb_cfg antes de reiniciar o PgBouncer (marcador da troca mantido)" >&2
}
# RESUME nos dois processos sempre que o script pausou. Não chama `erro` (evita laço): quem chama decide. Falha aparece em AVISO.
# Instância com host trocado e não confirmado de volta fica em PAUSE: retomar a levaria ao destino errado. Recuperação à mão no
# AVISO. `pausado=2` marca essa pendência: o EXIT não tenta RESUME de novo e o marcador da troca fica.
resumir_pgb() {
  [[ "$pausado" == 1 ]] || return 0
  local svc rn falhou="" presa=""
  for svc in pgb1 pgb2; do
    rn="resumido_$svc"
    # Já retomada em chamada anterior (o EXIT roda de novo): não repete o RESUME.
    [[ "${!rn}" == 1 ]] && continue
    if [[ "$host_trocado" == 1 && "$comitado" == 0 ]] && ! host_confirmado "$svc"; then
      presa+=" $svc"
      echo "AVISO: $svc segue em PAUSE com host=$NOVO (volta ao host=$ORIG não confirmada). Recuperação à mão: no contêiner $svc, sed -i 's/host=$NOVO /host=$ORIG /' /tmp/pgb/$svc/pgbouncer.ini; depois psql -h /tmp/pgb/$svc -p 6432 -U pgbouncer pgbouncer -c RELOAD e -c RESUME" >&2
      continue
    fi
    # Falha do RESUME com o pooler já não pausado: medido no ensaio Docker (modo físico), um PgBouncer reiniciado na janela
    # promote→RESUME volta sem PAUSE (lê /cfg/banco-destino) e já serve o destino; é o estado desejado. Depois do RESUME da troca
    # (comitado) o host em execução da app tem de ser o destino gravado ($NOVO): host antigo é falha, com a recuperação no AVISO.
    # Pausado ou consulta falhando segue falha. As consultas só rodam no ramo de falha.
    if pgb_console "$svc" RESUME; then
      printf -v "$rn" '%s' 1
    elif [[ "$(pgb_pausado "$svc")" != 0 ]]; then
      falhou+=" $svc"
    elif [[ "$comitado" == 1 && "$(pgb_host_app "$svc")" != "$NOVO" ]]; then
      echo "AVISO: RESUME de $svc falhou, o pooler não está pausado e não confirmei a linha de $bdnome em $NOVO (SHOW DATABASES): pode ter reiniciado com o host antigo. Recuperação à mão: no contêiner $svc, sed -i 's/host=$ORIG /host=$NOVO /' /tmp/pgb/$svc/pgbouncer.ini; depois psql -h /tmp/pgb/$svc -p 6432 -U pgbouncer pgbouncer -c RELOAD e -c RESUME" >&2
      falhou+=" $svc"
    elif [[ "$comitado" == 0 && "$(pgb_host_app "$svc")" != "$ORIG" ]]; then
      # Aborto: o PgBouncer reiniciado na janela gravação→promote leu o destino. Sem o host original confirmado, não retoma.
      echo "AVISO: RESUME de $svc falhou, o pooler não está pausado e não confirmei a linha de $bdnome em $ORIG (SHOW DATABASES): pode ter reiniciado com o host de destino. Recuperação à mão: no contêiner $svc, sed -i 's/host=$NOVO /host=$ORIG /' /tmp/pgb/$svc/pgbouncer.ini; depois psql -h /tmp/pgb/$svc -p 6432 -U pgbouncer pgbouncer -c RELOAD e -c RESUME" >&2
      falhou+=" $svc"
    else
      local onde="host original"
      [[ "$comitado" == 1 ]] && onde=destino
      echo "AVISO: RESUME de $svc falhou, mas o pooler não está pausado (reiniciado na troca): segue no $onde" >&2
      printf -v "$rn" '%s' 1
    fi
  done
  if [[ -n "$falhou" ]]; then
    echo "AVISO: RESUME falhou em:$falhou; o PgBouncer pode seguir em PAUSE: rode RESUME nos dois processos à mão" >&2
  elif [[ -n "$presa" ]]; then
    pausado=2
  else
    pausado=0
  fi
}
# Registro por instância: 1 = host de volta ao original e confirmado (RESTAURA e RELOAD), 0 = não confirmado.
definir_host_ok() { local svc="$1" valor="$2"; printf -v "host_ok_$svc" '%s' "$valor"; }
host_confirmado() { local svc="$1"; local nome="host_ok_$svc"; [[ "${!nome}" == 1 ]]; }
pausar_pgb() {
  pausado=1
  pgb_console pgb1 PAUSE || erro "não consegui pausar pgb1 pelo console"
  pgb_console pgb2 PAUSE || erro "não consegui pausar pgb2 pelo console"
  pausa_t0="$(date +%s%3N)"
}
# Antes do RESUME da troca: devolve o `host=` anterior nos dois PgBouncer e recarrega. Depois do RESUME não há rollback.
restaurar_host() {
  [[ "$host_trocado" == 1 && "$comitado" == 0 ]] || return 0
  local svc
  for svc in pgb1 pgb2; do
    definir_host_ok "$svc" 1
    # sed falhou: o ini pode já estar no host original (medido no ensaio: o sed falhou nos dois sentidos e o ini não mudou).
    # Confere a linha real; só sem ela no host original a instância fica sem confirmação.
    if ! pgb_sed "$svc" "s/host=$NOVO /host=$ORIG /"; then
      ini_no_host_origem "$svc" || definir_host_ok "$svc" 0
    fi
  done
  for svc in pgb1 pgb2; do pgb_console "$svc" RELOAD || definir_host_ok "$svc" 0; done
  if host_confirmado pgb1 && host_confirmado pgb2; then
    host_trocado=0
  else
    echo "AVISO: não consegui restaurar host=$ORIG nos PgBouncer: confira pgbouncer.ini e rode RELOAD" >&2
  fi
}
# Origem somente leitura (item 2, achado CodeRabbit, modo lógico): depois do lag zero e antes do DISABLE, a origem para de receber
# escrita, para que nenhuma escrita fique de fora da última LSN lida. `ALTER DATABASE` vale só para sessões novas; o
# pg_terminate_backend derruba as sessões de cliente abertas (o walsender do replicador tem backend_type diferente e fica).
# A flag vai antes do ALTER: se ele falhar no meio, o aborto tenta o RESET. No sucesso a origem antiga fica somente leitura de
# propósito: um reinício do PgBouncer que volte a ela recebe erro de escrita, não diverge em silêncio.
origem_somente_leitura() {
  origem_ro=1
  sql_em "$ORIG" -f - >/dev/null <<SQL
ALTER DATABASE "$bdnome" SET default_transaction_read_only = on;
SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$bdnome' AND pid <> pg_backend_pid() AND backend_type = 'client backend';
SQL
}
# Aborto antes do ponto sem volta (erro(), depois do restaurar_host e antes do resumir_pgb): 3 tentativas do RESET. Sem êxito, AVISO
# com o comando. Depois do ponto sem volta (`comitado`) não mexe: a origem fica somente leitura de propósito.
# O SET vai na mesma sessão (mesmo stdin): sem ele, o ALTER DATABASE falha na sessão que já é somente leitura (medido no PostgreSQL).
restaurar_origem() {
  local t manual
  [[ "$origem_ro" == 1 && "$comitado" == 0 ]] || return 0
  for t in 1 2 3; do
    if sql_em "$ORIG" -f - >/dev/null <<SQL
SET default_transaction_read_only = off;
ALTER DATABASE "$bdnome" RESET default_transaction_read_only;
SQL
    then
      origem_ro=0
      return 0
    fi
  done
  # Duas opções `-c` no mesmo psql: mesma sessão, cada uma em autocommit. Um `-c` só com as duas falha (transação única).
  manual="PGPASSWORD=\"\$POSTGRES_PASSWORD\" psql -X -h 127.0.0.1 -U postgres -d $bdnome -c 'SET default_transaction_read_only = off;' -c 'ALTER DATABASE \"$bdnome\" RESET default_transaction_read_only;'"
  echo "AVISO: não consegui devolver a escrita à origem ($ORIG). Rode no contêiner dela: $manual" >&2
}
# Remove a assinatura do destino (e o slot na origem) quando a troca não chegou ao RESUME.
limpar_assinatura() {
  [[ "$assinatura" == 1 && "$comitado" == 0 ]] || return 0
  # Guardado por pg_subscription (lote 2, R3): sem assinatura (falha antes do CREATE) não há erro nem AVISO falso; com a resposta
  # do CREATE perdida, a assinatura existe e sai aqui. `\gexec` roda cada comando montado; DROP só depois do DISABLE.
  if sql_em "$NOVO" -f - >/dev/null 2>&1 <<SQL
SELECT format('ALTER SUBSCRIPTION %I DISABLE', subname) FROM pg_subscription WHERE subname = '$SUB' \gexec
SELECT format('DROP SUBSCRIPTION %I', subname) FROM pg_subscription WHERE subname = '$SUB' \gexec
SQL
  then
    assinatura=0
  else
    # O DROP pode falhar com a origem fora do ar (ele também remove o slot remoto): o slot, se ficou, sai na origem.
    echo "AVISO: não consegui remover a assinatura $SUB no $NOVO. Rode no $NOVO: ALTER SUBSCRIPTION $SUB DISABLE; DROP SUBSCRIPTION $SUB; e, se o slot ficou, na origem ($ORIG): SELECT pg_drop_replication_slot('$SUB');" >&2
  fi
}
# Remove a publicação da origem (aborto e fim com sucesso). Idempotente (IF EXISTS). Falha vira AVISO: não derruba a troca.
limpar_publicacao() {
  [[ "$publicacao" == 1 ]] || return 0
  if sql_em "$ORIG" -f - >/dev/null 2>&1 <<SQL
SET default_transaction_read_only = off;
DROP PUBLICATION IF EXISTS $PUB;
SQL
  then
    publicacao=0
  else
    echo "AVISO: não consegui remover a publicação $PUB no $ORIG: rode DROP PUBLICATION IF EXISTS $PUB; no $ORIG" >&2
  fi
}

# Passfile da assinatura, escrito dentro do banco_novo (dono postgres, modo 0600). Formato .pgpass: `\` e `:` levam `\`. A senha
# entra só pelo ambiente do exec (-e sem valor) e nunca como argumento; origem e banco vêm como parâmetros do sh (validados antes).
gravar_pgpass() {
  pgpass_criado=1
  compor exec -T -u postgres -e PHATI_BANCO_REPLICADOR_SENHA "$NOVO" sh -c \
    'rm -f "$0" && umask 077 && esc="$(printf "%s" "$PHATI_BANCO_REPLICADOR_SENHA" | sed "s/[\\:]/\\\\&/g")" && printf "%s\n" "$1:5432:$2:replicador:$esc" > "$0"' \
    "$PGPASS" "$ORIG" "$bdnome" >/dev/null 2>&1 || erro "não consegui gravar o arquivo de senha no $NOVO: nada trocado"
}
# Remove o passfile do banco_novo. Chamada depois do DROP SUBSCRIPTION (sucesso ou aborto): antes disso o apply worker ainda reconecta.
remover_pgpass() {
  [[ "$pgpass_criado" == 1 ]] || return 0
  if compor exec -T -u postgres "$NOVO" rm -f "$PGPASS" >/dev/null 2>&1; then
    pgpass_criado=0
  else
    echo "AVISO: não consegui remover $PGPASS no $NOVO: rode rm -f $PGPASS no $NOVO" >&2
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
  # O valor vai ao `exec` pela variável exportada (ler_env tira as aspas e não imprime). Vazio é o mesmo que ausente.
  PHATI_BANCO_REPLICADOR_SENHA="$(ler_env PHATI_BANCO_REPLICADOR_SENHA)"
  [[ -n "$PHATI_BANCO_REPLICADOR_SENHA" ]] || erro "PHATI_BANCO_REPLICADOR_SENHA ausente ou vazia no .env"
  export PHATI_BANCO_REPLICADOR_SENHA
  [[ -d "$dir/repo/.git" ]] || erro "$dir/repo não é um clone do repositório"
  [[ -f "$dir/repo/servidor/compose.implantacao.yaml" ]] || erro "compose de implantação ausente no clone"
  [[ -f "$dir/repo/servidor/banco/papeis.sql" ]] || erro "papeis.sql ausente no clone"
  saudavel_agora pgb1 && saudavel_agora pgb2 || erro "PgBouncer indisponível: pgb1 e pgb2 precisam estar saudáveis antes da troca"
  saudavel_agora "$ORIG" || erro "banco não está saudável: nada foi feito"
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
  compor exec -T -e PHATI_BANCO_REPLICADOR_SENHA "$ORIG" sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -U postgres -d postgres -f -' < "$dir/repo/servidor/banco/papeis.sql" >/dev/null 2>&1 \
    || erro "SQL do papel replicador falhou (saída suprimida: contém a senha)"

  if [[ "$ja_logical" == 1 ]]; then
    registrar "OK ja_logical=1"
    echo "preparar_ok ja_logical=1"
    return 0
  fi

  passo=pausa
  pausar_pgb
  passo=banco-reinicio
  compor up -d --no-deps "$ORIG" >/dev/null || erro "não consegui recriar o banco com wal_level=logical"
  esperar_saude "$ORIG" || erro "banco não voltou saudável depois do reinício (estado: ${estado:-desconhecido})"
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
# Espera a origem ter o LSN $1 confirmado pelo assinante (com PAUSE ativo, sem escrita nova). A barreira é o slot da origem:
# received_lsn e latest_end_lsn do destino só provam recebimento, não aplicação. Pré-condição no destino: o received já chegou.
# NÃO CONFIRMADO PELA DOC, a validar no ensaio real: que o slot (nome = $SUB, criado pelo CREATE SUBSCRIPTION) avance o
# confirmed_flush_lsn até o LSN de pg_current_wal_lsn() sem transação nova. Se não avançar, o laço estoura e aborta (falha segura).
esperar_lag() {
  local _ ok confirmado lsn="$1"
  for _ in $(seq "${PHATI_TENTATIVAS:-60}"); do
    ok="$(sql_em "$NOVO" -At -c "SELECT pg_wal_lsn_diff(received_lsn, '$lsn') >= 0 FROM pg_stat_subscription WHERE subname = '$SUB'" || true)"
    if [[ "$ok" == t ]]; then
      confirmado="$(sql_em "$ORIG" -At -c "SELECT pg_wal_lsn_diff('$lsn', confirmed_flush_lsn) <= 0 FROM pg_replication_slots WHERE slot_name = '$SUB'" || true)"
      [[ "$confirmado" == t ]] && return 0
    fi
    sleep "${PHATI_ESPERA:-2}"
  done
  return 1
}
# Grava o destino no `.env` de forma atômica: arquivo temporário no mesmo diretório, com o modo e o dono do `.env`.
# Temporário registrado em `tmp_env`/`tmp_banco`: o EXIT (limpar_temporarios) remove o que sobrar de uma falha do mv ou de uma saída.
gravar_env_destino() {
  tmp_env="$(mktemp "$dir/.env.XXXXXX")"
  # grep -v sai 1 quando não sobra linha (normal); rc acima de 1 é leitura que falhou: aborta sem publicar o temporário.
  # A leitura vem antes do chmod: com o modo do .env (ilegível) o temporário não aceitaria a gravação e o erro sairia mascarado.
  local rc=0
  grep -v '^PHATI_BANCO_DESTINO=' "$dir/.env" > "$tmp_env" || rc=$?
  (( rc <= 1 )) || erro "não consegui ler o .env: nada gravado"
  chmod --reference="$dir/.env" "$tmp_env"
  chown --reference="$dir/.env" "$tmp_env" 2>/dev/null || true
  printf 'PHATI_BANCO_DESTINO=%s\n' "$NOVO" >> "$tmp_env" || erro "não consegui gravar o .env"
  mv -f "$tmp_env" "$dir/.env" || erro "não consegui gravar o .env"
  tmp_env=""
}
gravar_banco_ativo() {
  tmp_banco="$(mktemp "$dir/.banco-ativo.XXXXXX")"
  # mktemp cria 600 e os scripts de implantação (outro usuário) leem este arquivo: sai 644 com o dono do diretório.
  # O resultado é checado: na recuperação (`completar_persistencia && return 0`) o set -e fica suspenso.
  chmod 644 "$tmp_banco" || erro "não consegui ajustar o modo de banco-ativo"
  chown --reference="$dir" "$tmp_banco" 2>/dev/null || true
  printf '%s\n' "$NOVO" > "$tmp_banco" && mv -f "$tmp_banco" "$dir/banco-ativo" || erro "não consegui gravar banco-ativo"
  tmp_banco=""
}
# Marcador do modo lógico para os scripts de implantação. Gravado antes do banco-ativo: uma queda entre as duas deixa o override
# no `banco` (estado do preparar), nunca a falta dele no banco_novo.
gravar_banco_logico() {
  tmp_banco="$(mktemp "$dir/.banco-logico.XXXXXX")"
  # Mesmo motivo de gravar_banco_ativo: o marcador é lido pelo usuário de implantação, e o resultado do chmod é checado.
  chmod 644 "$tmp_banco" || erro "não consegui ajustar o modo de banco-logico"
  chown --reference="$dir" "$tmp_banco" 2>/dev/null || true
  printf 'logica\n' > "$tmp_banco" && mv -f "$tmp_banco" "$dir/banco-logico" || erro "não consegui gravar banco-logico"
  tmp_banco=""
}
limpar_temporarios() {
  [[ -z "$tmp_env" ]] || rm -f "$tmp_env"
  [[ -z "$tmp_banco" ]] || rm -f "$tmp_banco"
  return 0
}
# Estado parcial da persistência: banco-ativo e .env são duas gravações. Se uma já diz banco_novo, a troca passou do ponto sem
# volta: completa a que falta (banco-ativo primeiro, é o que os scripts consultam) sem pausar nem tocar nos PgBouncer, e só com o
# marcador `troca-banco-em-curso` (parcial sem marcador recusa, lote 2 R4). Retorna 1 quando nenhuma das duas diz banco_novo (troca nova).
completar_persistencia() {
  local ativo_ok=0 env_ok=0 completou=""
  [[ "$(ativo_gravado)" == "$NOVO" ]] && ativo_ok=1
  [[ "$(ler_env PHATI_BANCO_DESTINO)" == "$NOVO" ]] && env_ok=1
  # Só há o que completar com o marcador da troca em curso (lote 2, R4; desenho da volta). Sem ele, estado completo é troca nova
  # (não rc 0 falso) e o parcial já foi recusado por `resolver_direcao`. Com marcador, a direção é a do marcador, não a do banco-ativo.
  [[ -e "$marcador" ]] || return 1
  (( ativo_ok == 1 || env_ok == 1 )) || return 1
  # Ponto sem volta já passou: um erro daqui não pode apagar o marcador (limpar_marcador só apaga com comitado=0).
  comitado=1
  if (( ativo_ok == 0 )); then gravar_banco_ativo; completou="banco-ativo"; fi
  if (( env_ok == 0 )); then gravar_env_destino; completou="${completou:+$completou,}env"; fi
  # Arquivos que não passam pelos gravar_*: banco-ativo que já dizia banco_novo (ativo_ok=1) e banco-logico, se existir, saem 644
  # com o dono do diretório, como os gravados. Antes do marcador: falha aborta com o marcador ainda presente.
  for f in "$dir/banco-ativo" "$dir/banco-logico"; do
    [[ -e "$f" ]] || continue
    chmod 644 "$f" || erro "não consegui ajustar o modo de $(basename "$f")"
    chown --reference="$dir" "$f" 2>/dev/null || true
  done
  # Falha ao remover o marcador aborta antes do trocar_ok (lote 2, R5): o marcador que sobra recusa a próxima execução.
  rm -f "$marcador" || erro "não consegui remover o marcador $marcador: troca não completada"
  if [[ -z "$completou" ]]; then
    registrar "OK ja_trocado=1"
    echo "trocar_ok ja_trocado=1"
  else
    registrar "OK ja_trocado=1 completou=$completou"
    echo "trocar_ok ja_trocado=1 completou=$completou"
  fi
  return 0
}
# Marcador gravado antes do PAUSE (conteúdo: origem, destino, modo e passo). Fica se a troca passou do RESUME e falhou depois: a
# próxima execução recusa até alguém reconciliar. A origem e o destino gravados são o que a recuperação usa para a direção (volta):
# marcador sem eles é de versão anterior e recusa (`resolver_direcao`).
marcar_troca() {
  printf 'origem=%s destino=%s modo=%s passo=%s\n' "$ORIG" "$NOVO" "$modo" "$passo" > "$marcador" || erro "não consegui gravar o marcador $marcador: nada pausado"
}
# Remove o marcador só no aborto completo de `trocar` (RESUME feito e sem o ponto sem volta).
limpar_marcador() {
  [[ "$sub" == trocar && "$comitado" == 0 && "$pausado" == 0 && "$destino_pendente" == 0 ]] && rm -f "$marcador"
  return 0
}

# Hash sha256 do verificador SCRAM do papel $2 no serviço $1 (só leitura: o valor não sai do banco). Vazio = sem senha.
hash_verificador() {
  local svc="$1" papel="$2"
  sql_em "$svc" -At -v "papel=$papel" -f - <<'SQL'
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

# ---- Modo físico (spec 009 R15, S2b): standby por pg_basebackup do banco ativo; sem `preparar`, sem reiniciar a origem ----
# Ordem: build do banco_novo, volume vazio, major igual, backup verificado (R8), regra de replicação no pg_hba (reload, sem
# reinício), pg_basebackup com slot, standby em streaming, PAUSE, atraso zero, pg_promote, RESET do primary_conninfo (senha
# do replicador fora do postgresql.auto.conf), host nos PgBouncer, RESUME, drop do slot, persistência.
# Antes do promote, o aborto remove slot e banco_novo. Depois do promote e sem commit, o host volta e o banco_novo promovido
# vira AVISO de descarte. A senha do replicador vai só ao ambiente do `run` (`-e PGPASSWORD`, sem valor na linha de comando).
# Espera a consulta $2 em $1 devolver exatamente $3 (laço com PHATI_TENTATIVAS e PHATI_ESPERA).
esperar_consulta() {
  local svc="$1" consulta="$2" esperado="$3" _ r
  for _ in $(seq "${PHATI_TENTATIVAS:-60}"); do
    r="$(sql_em "$svc" -At -c "$consulta" || true)"
    [[ "$r" == "$esperado" ]] && return 0
    sleep "${PHATI_ESPERA:-2}"
  done
  return 1
}
# Espera o destino chegar ao LSN atual da origem com PAUSE ativo (atraso zero). Polling com PHATI_ESPERA_MS (padrão 100 ms;
# 0 não dorme, como nos testes).
esperar_lag_zero() {
  local _ lsn diff ms="${PHATI_ESPERA_MS:-100}"
  for _ in $(seq "${PHATI_TENTATIVAS:-60}"); do
    lsn="$(sql_em "$ORIG" -At -c 'SELECT pg_current_wal_lsn()')" || return 1
    [[ "$lsn" =~ ^[0-9A-Fa-f]+/[0-9A-Fa-f]+$ ]] || return 1
    diff="$(sql_em "$NOVO" -At -c "SELECT pg_wal_lsn_diff('$lsn', pg_last_wal_replay_lsn())" || true)"
    # Replay no LSN da origem ou à frente dele (diff <= 0; pg_wal_lsn_diff devolve numeric). Vazio ou texto não passa.
    if [[ "$diff" =~ ^-?[0-9]+(\.[0-9]+)?$ ]] && { [[ "$diff" == -* ]] || [[ "$diff" =~ ^0+(\.0+)?$ ]]; }; then return 0; fi
    (( ms > 0 )) && sleep "$(printf '%d.%03d' $((ms / 1000)) $((ms % 1000)))"
  done
  return 1
}
# Saída útil de um `run` capturado: tira as linhas de progresso do BuildKit (`#1 ...`) que o compose põe no stdout. O código de
# saída é o do `compor` (pipefail): o grep só filtra.
saida_run() { grep -v '^#[0-9]' || true; }
# Volume do banco_novo tem de estar vazio: o pg_basebackup grava nele tudo, e um volume com dado não é cópia limpa.
checar_volume_vazio() {
  local conteudo
  conteudo="$(compor run --rm -T --no-deps --entrypoint sh "$NOVO" -c 'ls -A /var/lib/postgresql' | saida_run)" || erro "não consegui ler o volume do $NOVO"
  [[ -z "$conteudo" ]] || erro "dados_$NOVO não está vazio: use limpar-destino $NOVO antes de trocar (nada foi alterado)"
}
# Destino limpo antes de qualquer escrita, nos dois modos (desenho item 2): a segunda troca logo após um sucesso cai aqui, porque o
# banco da origem antiga ainda tem dado. Só o `limpar-destino` apaga volume. O build vem antes do `run` (saída do BuildKit).
checar_destino_limpo() {
  passo=build
  compor build "$NOVO" >/dev/null 2>&1 || erro "build do $NOVO falhou: nada foi alterado"
  passo=volume
  checar_volume_vazio
}
# Major da origem igual ao da imagem do banco_novo (o standby físico só acompanha a mesma versão maior).
checar_major() {
  local origem novo major_novo
  origem="$(sql_em "$ORIG" -At -c 'SHOW server_version_num')" && [[ "$origem" =~ ^[0-9]+$ ]] || erro "não consegui ler a versão da origem"
  novo="$(compor run --rm -T --no-deps --entrypoint sh "$NOVO" -c 'postgres --version' | saida_run)" || erro "não consegui ler a versão da imagem do $NOVO"
  major_novo="$(printf '%s\n' "$novo" | grep -oE '[0-9]+' | head -n 1 || true)"
  [[ "$major_novo" =~ ^[0-9]+$ ]] || erro "versão da imagem do $NOVO em formato inesperado"
  (( origem / 10000 == major_novo )) || erro "major diferente: use --modo logica (origem $(( origem / 10000 )), imagem $major_novo)"
}
# Regra de replicação do replicador pela sub-rede (samenet). Acrescenta só se falta; recarrega sem reiniciar a origem.
garantir_pg_hba() {
  local regra="host replication replicador samenet scram-sha-256" contagem
  if ! compor exec -T -u postgres "$ORIG" sh -c "grep -qxF '$regra' \"\$PGDATA/pg_hba.conf\"" >/dev/null 2>&1; then
    compor exec -T -u postgres "$ORIG" sh -c "printf '%s\n' '$regra' >> \"\$PGDATA/pg_hba.conf\"" \
      || erro "não consegui acrescentar a regra de replicação no pg_hba da origem"
  fi
  sql_em "$ORIG" -At -c 'SELECT pg_reload_conf()' >/dev/null || erro "pg_reload_conf falhou na origem"
  contagem="$(sql_em "$ORIG" -At -c "SELECT count(*) FROM pg_hba_file_rules WHERE 'replication' = ANY(database) AND 'replicador' = ANY(user_name) AND auth_method = 'scram-sha-256' AND error IS NULL" || true)"
  [[ "$contagem" =~ ^[1-9][0-9]*$ ]] || erro "regra de replicação do replicador não carregou no pg_hba da origem"
}
# O `pg_basebackup -R` gravou `primary_conninfo` (com a senha do replicador) no postgresql.auto.conf do banco_novo. Depois do promote
# o banco é primário e a linha não serve: o RESET a tira do arquivo. Falha vira AVISO (o banco novo já é primário; sem rollback).
limpar_conninfo_standby() {
  if ! sql_em "$NOVO" -f - >/dev/null <<'SQL'
ALTER SYSTEM RESET primary_conninfo;
ALTER SYSTEM RESET primary_slot_name;
SELECT pg_reload_conf();
SQL
  then
    echo "AVISO: não consegui limpar primary_conninfo no $NOVO: rode ALTER SYSTEM RESET primary_conninfo; ALTER SYSTEM RESET primary_slot_name; SELECT pg_reload_conf(); no $NOVO" >&2
  fi
}
# Aborto da troca física. Antes do promote: remove o slot da origem e o banco_novo (e avisa o volume). Depois do promote sem
# commit: o host já voltou, então o banco_novo promovido vira AVISO de descarte. Depois do commit: nada a fazer.
limpar_fisico() {
  [[ "$comitado" == 0 ]] || return 0
  if [[ "$fisico_slot" == 1 ]]; then
    local liberado=1
    # O PostgreSQL recusa drop de slot ativo: com o standby iniciado, para-o e espera o slot ficar inativo antes do drop.
    if [[ "$standby_iniciado" == 1 ]]; then
      guarda_inativo "$NOVO" && compor stop "$NOVO" >/dev/null 2>&1 || liberado=0
      standby_iniciado=0
      esperar_consulta "$ORIG" "SELECT active FROM pg_replication_slots WHERE slot_name = '$SLOT'" f || liberado=0
    fi
    # Slot que não saiu não é zerado: o aviso leva o comando de remoção à mão.
    if [[ "$liberado" == 1 ]] && sql_em "$ORIG" -At -c "SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots WHERE slot_name = '$SLOT'" >/dev/null 2>&1; then
      fisico_slot=0
    else
      echo "AVISO: não consegui remover o slot $SLOT na origem (standby parado e slot inativo antes do drop): rode SELECT pg_drop_replication_slot('$SLOT'); na origem" >&2
    fi
  fi
  if [[ "$promovido" == 1 ]]; then
    echo "AVISO: $NOVO foi promovido e o host voltou para $ORIG: descarte o $NOVO (compose rm -sfv $NOVO e remova o volume dados_$NOVO)" >&2
    return 0
  fi
  if [[ "$novo_criado" == 1 ]]; then
    guarda_inativo "$NOVO" && compor rm -sfv "$NOVO" >/dev/null 2>&1 || echo "AVISO: não consegui remover o $NOVO: rode compose rm -sfv $NOVO" >&2
    echo "AVISO: remova o volume dados_$NOVO antes de tentar de novo (o modo físico exige volume vazio)" >&2
  fi
}
# Build da imagem do banco_novo antes de qualquer `run` capturado: sem ela, o `run` do volume ou da versão constrói a imagem e o
# progresso do BuildKit cai no stdout capturado (medido no ensaio real: '#1' virou major). A saída do build vai ao /dev/null.
# Movido para `checar_destino_limpo` (antes dos dois modos, desenho da volta); aqui fica só o que o modo físico precisa depois dele.
trocar_fisica() {
  local rep r
  passo=major
  checar_major
  passo=backup
  backup_verificado
  passo=replicador
  # Papel replicador: o papeis.sql (idempotente) roda na origem, como no preparar. Sem reinício da origem; falha aborta antes do PAUSE.
  compor exec -T -e PHATI_BANCO_REPLICADOR_SENHA "$ORIG" sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -U postgres -d postgres -f -' < "$dir/repo/servidor/banco/papeis.sql" >/dev/null 2>&1 \
    || erro "SQL do papel replicador falhou (saída suprimida: contém a senha): nada pausado"
  rep="$(sql_em "$ORIG" -At -c "SELECT count(*) FROM pg_roles WHERE rolname = 'replicador' AND rolreplication" || true)"
  [[ "$rep" == 1 ]] || erro "papel replicador ausente ou sem REPLICATION na origem: nada foi alterado"
  passo=pg_hba
  garantir_pg_hba
  passo=basebackup
  fisico_slot=1
  novo_criado=1  # o basebackup pode deixar dado parcial no volume: o aborto avisa para remover
  (
    export PGPASSWORD="$PHATI_BANCO_REPLICADOR_SENHA"
    compor run --rm -T --no-deps --user postgres -e PGPASSWORD --entrypoint sh "$NOVO" \
      -c "pg_basebackup -h $ORIG -U replicador -D \"\$PGDATA\" -R -X stream -C -S $SLOT --checkpoint=fast && chmod 0700 \"\$PGDATA\"" >/dev/null 2>&1
  ) || erro "pg_basebackup falhou (saída suprimida: contém a senha): nada pausado"
  passo=standby
  standby_iniciado=1  # antes do up: o aborto para o standby antes de largar o slot
  compor up -d --no-deps "$NOVO" >/dev/null || erro "não consegui subir o $NOVO"
  esperar_saude "$NOVO" || erro "$NOVO não voltou saudável (estado: ${estado:-desconhecido})"
  esperar_consulta "$NOVO" 'SELECT pg_is_in_recovery()' t || erro "$NOVO não entrou em recovery: nada pausado"
  esperar_consulta "$NOVO" "SELECT count(*) FROM pg_stat_wal_receiver WHERE status = 'streaming'" 1 || erro "$NOVO sem streaming da origem: nada pausado"
  passo=pausa
  marcar_troca
  pausar_pgb
  passo=atraso
  esperar_lag_zero || erro "atraso do $NOVO não chegou a zero com PAUSE ativo: nada trocado"
  passo=promocao
  # Destino do PgBouncer logo antes do promote: uma instância reiniciada nesta janela lê o destino com o banco_novo ainda standby.
  destino_pgb_gravado=1
  gravar_destino_pgb || erro "não consegui gravar o destino no volume pgb_cfg: nada trocado"
  # Um PgBouncer reiniciado daqui até o RESUME lê o destino e sobe com banco_novo: o aborto devolve o host dele (restaurar_host),
  # não só apaga o destino (medido no dublê: test "pgb1 reinicia entre o destino gravado e o pg_promote").
  host_trocado=1
  promovido=1  # antes do promote: se ele falhar no meio, o aborto trata o banco_novo como promovido
  [[ "$(sql_em "$NOVO" -At -c 'SELECT pg_promote(true, 60)' || true)" == t ]] || erro "pg_promote falhou: nada trocado"
  esperar_consulta "$NOVO" 'SELECT pg_is_in_recovery()' f || erro "$NOVO não saiu de recovery depois do promote"
  passo=conninfo
  limpar_conninfo_standby
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
  sql_em "$ORIG" -At -c "SELECT pg_drop_replication_slot('$SLOT')" >/dev/null 2>&1 \
    || echo "AVISO: não consegui remover o slot $SLOT na origem: rode SELECT pg_drop_replication_slot('$SLOT'); na origem" >&2
  fisico_slot=0
  passo=persistir
  gravar_banco_ativo
  gravar_env_destino
  rm -f "$marcador" || erro "não consegui remover o marcador $marcador: troca não completada"
  registrar "OK modo=fisica pausa_ms=$pausa_ms destino=$NOVO"
  echo "trocar_ok pausa_ms=$pausa_ms"
}

trocar() {
  # Só o `trocar` usa o profile: o `banco_novo` fica fora dos outros subcomandos.
  export COMPOSE_PROFILES=troca-banco
  passo=precondicoes
  local margem="${PHATI_MARGEM_SEQ:-1000}" wal lista n lsn pausa_ms r papel_app
  [[ "$margem" =~ ^[0-9]{1,15}$ ]] || { echo "ERRO: PHATI_MARGEM_SEQ inválida: use inteiro maior ou igual a 0" >&2; exit 1; }
  # Antes do marcador: uma troca que já passou do ponto sem volta só completa a persistência (e o marcador sai com ela).
  completar_persistencia && return 0
  [[ ! -e "$marcador" ]] || { echo "ERRO: troca anterior interrompida (marcador $marcador): confira os PgBouncer (SHOW DATABASES, estado de pausa), a origem e o banco_novo, e remova o marcador depois de reconciliar" >&2; exit 1; }
  checar_vm
  # Único papel que o pgb_auth grava no userlist.txt: o do app (compose: PHATI_BANCO_APP_USUARIO). Nome validado antes de qualquer SQL.
  papel_app="${PHATI_BANCO_APP_USUARIO:-}"
  [[ -n "$papel_app" ]] || papel_app="$(ler_env PHATI_BANCO_APP_USUARIO)"
  [[ "$papel_app" =~ ^[a-z_][a-z0-9_]*$ ]] || erro "PHATI_BANCO_APP_USUARIO ausente ou inválido: nada foi feito"
  # O destino do `.env` já foi conferido com o banco ativo em `resolver_direcao`. Destino com dado (origem antiga) recusa aqui, antes de
  # qualquer escrita, nos dois modos.
  checar_destino_limpo
  if [[ "$modo" == fisica ]]; then
    trocar_fisica
    return 0
  fi
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
    compor exec -T "$ORIG" sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -h 127.0.0.1 -U postgres --schema-only -d '"$bdnome"'' \
      | sql_em "$NOVO" -f - || erro "esquema não aplicado no $NOVO"
  else
    # Recusa antes da publicação e do PAUSE: tabelas de uma tentativa abortada fariam a cópia do lógico colidir em chave duplicada.
    erro "$NOVO já tem tabelas de usuário em public: remova o volume dados_$NOVO antes de repetir o modo lógico (nada foi alterado)"
  fi

  passo=publicacao
  lista="$(sql_em "$ORIG" -At -c "SELECT coalesce(string_agg(format('%I.%I', n.nspname, c.relname), ', '), '') $FROM_TABELAS")" || erro "não consegui listar as tabelas da origem"
  [[ -n "$lista" ]] || erro "lista de tabelas vazia: nada a publicar"
  publicacao=1  # antes do CREATE: se ele falhar no meio, o DROP IF EXISTS do aborto limpa
  sql_em "$ORIG" -f - <<SQL || erro "publicação não criada na origem"
SELECT format('CREATE PUBLICATION %I FOR TABLE %s', '$PUB', string_agg(format('%I.%I', n.nspname, c.relname), ', ')) $FROM_TABELAS \gexec
SQL

  passo=assinatura
  # A conninfo aponta para o passfile: a instrução (que o servidor loga em erro) não leva senha. Stderr suprimido pelo sql_em.
  gravar_pgpass
  # Antes do CREATE (lote 2, R3): se a resposta se perder depois de o servidor criar a assinatura, o aborto tenta remover.
  assinatura=1
  sql_em "$NOVO" -f - >/dev/null <<SQL || erro "assinatura não criada no $NOVO: nada pausado"
CREATE SUBSCRIPTION $SUB CONNECTION 'host=$ORIG port=5432 dbname=$bdnome user=replicador passfile=$PGPASS' PUBLICATION $PUB;
SQL

  passo=sincronia
  esperar_sincronia || erro "sincronização não chegou a 'r' em todas as tabelas: nada foi pausado"

  passo=verificador
  copiar_verificador "$papel_app"

  passo=pausa
  marcar_troca
  pausar_pgb
  passo=lag
  lsn="$(sql_em "$ORIG" -At -c 'SELECT pg_current_wal_lsn()')" || erro "não consegui ler o LSN da origem"
  [[ "$lsn" =~ ^[0-9A-Fa-f]+/[0-9A-Fa-f]+$ ]] || erro "LSN da origem em formato inesperado: nada trocado"
  esperar_lag "$lsn" || erro "destino não alcançou o LSN da origem com PAUSE ativo: nada trocado"

  passo=origem-ro
  origem_somente_leitura || erro "origem não ficou somente leitura: nada trocado"

  passo=desabilita
  sql_em "$NOVO" -f - <<SQL || erro "não consegui desabilitar a assinatura"
ALTER SUBSCRIPTION $SUB DISABLE;
SQL

  passo=sequencias
  # Sequências não replicam. Valor = último (ou start_value - increment_by, se nunca usada) + margem no sentido do increment_by
  # (margem + 1 se nunca usada). Limitado por LEAST/GREATEST a [min_value, max_value]: se a margem não cabe, para no limite
  # (a sequência fica esgotada no destino, como na origem). Falha aborta antes do host.
  sql_em "$ORIG" -At -v "margem=$margem" -f - <<'SQL' | sql_em "$NOVO" -f - || erro "sequências não ajustadas no $NOVO: nada trocado"
SELECT format('SELECT setval(%L, %s, true);', schemaname || '.' || sequencename,
  GREATEST(LEAST(COALESCE(last_value::numeric, start_value::numeric - increment_by::numeric)
    + CASE WHEN increment_by < 0 THEN -1 ELSE 1 END * (:'margem'::numeric + CASE WHEN last_value IS NULL THEN 1 ELSE 0 END),
    max_value::numeric), min_value::numeric)::bigint)
FROM pg_sequences WHERE schemaname = 'public';
SQL

  passo=host
  host_trocado=1
  for r in pgb1 pgb2; do pgb_sed "$r" "s/host=$ORIG /host=$NOVO /" || erro "não consegui trocar o host em $r"; done
  passo=reload
  for r in pgb1 pgb2; do pgb_console "$r" RELOAD || erro "RELOAD falhou em $r"; done
  passo=destino-pgb
  destino_pgb_gravado=1
  gravar_destino_pgb || erro "não consegui gravar o destino no volume pgb_cfg: nada trocado"

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
    remover_pgpass
  else
    echo "AVISO: DROP SUBSCRIPTION falhou no $NOVO: rode DROP SUBSCRIPTION $SUB; (o slot fica na origem até lá)" >&2
  fi
  limpar_publicacao

  passo=persistir
  gravar_banco_logico
  gravar_banco_ativo
  gravar_env_destino
  rm -f "$marcador" || erro "não consegui remover o marcador $marcador: troca não completada"
  registrar "OK pausa_ms=$pausa_ms destino=$NOVO"
  echo "trocar_ok pausa_ms=$pausa_ms"
}

# Assinatura, publicação ou slot no banco $1: contagem exata 0. Sem resposta recusa (nada se presume).
pendencias_de() {
  local svc="$1" contagem
  contagem="$(sql_em "$svc" -At -c 'SELECT (SELECT count(*) FROM pg_subscription) + (SELECT count(*) FROM pg_publication) + (SELECT count(*) FROM pg_replication_slots)' || true)"
  [[ "$contagem" == 0 ]] || erro "assinatura, publicação ou slot pendente em $svc (contagem: ${contagem:-sem resposta}): nada foi removido"
}
# Serviço $1 em execução? Saída: 0 sim, 1 não (parado ou removido), 2 indeterminado (o Docker não respondeu). Doc do `ps --status`:
# https://docs.docker.com/reference/cli/docker/compose/ps/
alvo_em_execucao() {
  local svc="$1" saida
  saida="$(compor ps -q --status running "$svc")" || return 2
  [[ -n "$saida" ]]
}
# Volume nomeado $1 existe? Saída: 0 sim, 1 não, 2 indeterminado (o `volume ls` falhou). Nome exato, não substring do filtro.
volume_existe() {
  local nome="$1" saida
  saida="$("$docker" volume ls -q --filter "name=^${nome}\$")" || return 2
  grep -qxF -- "$nome" <<<"$saida"
}
# Remove o banco INATIVO (desenho da volta, item 4): contêiner e volume nomeado `${projeto}_dados_<serviço>`. É o único lugar que apaga
# volume; `trocar` nunca apaga. Falha fechada: qualquer dúvida sai antes da remoção. `docker compose rm -v` não serve para o volume
# nomeado: só remove o anônimo (doc oficial: https://docs.docker.com/reference/cli/docker/compose/rm/), por isso o `docker volume rm`.
limpar_destino() {
  local alvo="$1" pgb_dest contagem svc
  export COMPOSE_PROFILES=troca-banco
  passo=precondicoes
  [[ ! -e "$marcador" ]] || recusar "troca anterior interrompida (marcador $marcador): reconcilie antes de remover um banco; nada foi removido"
  [[ "$alvo" != "$ORIG" ]] || recusar "não remove o banco ativo ($ORIG): nada foi removido"
  checar_vm
  # Destino do PgBouncer: o arquivo `/cfg/banco-destino` (ausente = padrão banco, como o entrypoint) e o host em execução nos dois.
  passo=destino-pgb
  pgb_dest="$(compor run --rm --no-deps -T --entrypoint sh pgb_auth -c 'if [ -e /cfg/banco-destino ]; then cat /cfg/banco-destino; else echo __AUSENTE__; fi' | saida_run)" \
    || erro "não consegui ler o destino do PgBouncer: nada foi removido"
  if [[ "$pgb_dest" == __AUSENTE__ ]]; then pgb_dest=banco; fi
  [[ "$pgb_dest" == "$ORIG" ]] || erro "destino do PgBouncer não é o banco ativo ($ORIG): nada foi removido"
  for svc in pgb1 pgb2; do
    [[ "$(pgb_host_app "$svc")" == "$ORIG" ]] || erro "destino do PgBouncer não é o banco ativo ($ORIG): nada foi removido"
  done
  # Pendência (assinatura, publicação ou slot) no ativo: sempre consultado. No alvo: só se está em execução; parado ou removido não tem
  # conexão ativa a consultar (a consulta falharia, e um contêiner removido é o caso do aborto que manda limpar o volume). Estado
  # indeterminado (o Docker não responde) recusa antes de qualquer remoção.
  passo=pendencias
  pendencias_de "$ORIG"
  alvo_rc=0
  alvo_em_execucao "$alvo" || alvo_rc=$?
  case "$alvo_rc" in
    0) pendencias_de "$alvo" ;;
    1) ;;
    *) erro "não consegui saber se o alvo está em execução: nada foi removido" ;;
  esac
  # Volume: existe (será removido), não existe (repetição depois de falha no meio: nada a apagar) ou indeterminado (recusa agora).
  passo=volume-existe
  vol="${projeto}_dados_$alvo"
  vol_rc=0
  volume_existe "$vol" || vol_rc=$?
  case "$vol_rc" in
    0|1) ;;
    *) erro "não consegui saber se o volume $vol existe: nada de volume foi removido" ;;
  esac
  # Backup verificado do ativo antes de qualquer remoção (mesmo mecanismo da troca, R8).
  passo=backup
  backup_verificado
  passo=remover
  guarda_inativo "$alvo" || erro "guarda: $alvo é o banco ativo: nada foi removido"
  compor rm -sfv "$alvo" >/dev/null 2>&1 || erro "não consegui remover o contêiner $alvo: o volume ficou (rode compose rm -sfv $alvo)"
  passo=volume
  if [[ "$vol_rc" == 0 ]]; then
    "$docker" volume rm "$vol" >/dev/null 2>&1 || erro "não consegui remover o volume $vol: rode docker volume rm $vol"
  fi
  registrar "OK alvo=$alvo"
  echo "limpar_destino_ok alvo=$alvo"
}

# Subcomando é a única entrada externa: validado antes de qualquer ação e antes da trava.
case "$sub" in
  preparar|trocar|limpar-destino) ;;
  *) echo "ERRO: subcomando inválido: use preparar, trocar ou limpar-destino" >&2; exit 1 ;;
esac
args=("${@:2}")
alvo_pedido=""
if [[ "$sub" == preparar ]]; then
  [[ ${#args[@]} -eq 0 ]] || { echo "ERRO: opção desconhecida: preparar não aceita argumentos" >&2; exit 1; }
elif [[ "$sub" == limpar-destino ]]; then
  # Serviço explícito e de uma lista fixa; a checagem contra o ativo é depois, com o estado lido.
  [[ ${#args[@]} -eq 1 && ( "${args[0]}" == banco || "${args[0]}" == banco_novo ) ]] || { echo "ERRO: limpar-destino exige um serviço: banco ou banco_novo" >&2; exit 1; }
  alvo_pedido="${args[0]}"
else
  while [[ ${#args[@]} -gt 0 ]]; do
    case "${args[0]}" in
      --modo)
        [[ ${#args[@]} -ge 2 ]] || { echo "ERRO: --modo exige valor: fisica ou logica" >&2; exit 1; }
        modo="${args[1]}"
        args=("${args[@]:2}")
        ;;
      --modo=*) modo="${args[0]#--modo=}"; args=("${args[@]:1}") ;;
      *) echo "ERRO: opção desconhecida: ${args[0]}" >&2; exit 1 ;;
    esac
  done
  # Recusa antes da trava e do Docker.
  case "$modo" in
    fisica|logica) ;;
    *) echo "ERRO: modo inválido: use fisica ou logica" >&2; exit 1 ;;
  esac
fi
[[ "${PHATI_PAUSA_LIMITE:-30}" =~ ^[1-9][0-9]{0,5}$ ]] || { echo "ERRO: PHATI_PAUSA_LIMITE inválida: use inteiro positivo (segundos)" >&2; exit 1; }
projeto="${PHATI_PROJETO:-phati}"
[[ "$projeto" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || { echo "ERRO: PHATI_PROJETO inválido" >&2; exit 1; }
# Nome do banco, como o compose (PHATI_BANCO_NOME): ambiente, depois `.env`, padrão phati. Resolvido uma vez, validado antes do
# Docker e usado em todas as conexões (psql, pg_dump e conninfo da assinatura).
bdnome="${PHATI_BANCO_NOME:-}"
[[ -n "$bdnome" ]] || bdnome="$(ler_env PHATI_BANCO_NOME)"
[[ -n "$bdnome" ]] || bdnome=phati
[[ "$bdnome" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "ERRO: PHATI_BANCO_NOME inválido: use minúsculas, dígitos e _ (começa por letra ou _)" >&2; exit 1; }
export COMPOSE_PROJECT_NAME="$projeto"
travar "$@"
# Direção da troca, depois da trava e antes de qualquer Docker de escrita (ver `resolver_direcao`).
resolver_direcao

trap 'erro "falhou no passo: $passo"' ERR
trap 'resumir_pgb; limpar_temporarios' EXIT
# Sinal vira erro (rollback antes do ponto sem volta; depois dele, só RESUME): sem isso, o EXIT retomaria as instâncias sem restaurar o host.
trap 'erro "interrompido por sinal"' TERM HUP INT
case "$sub" in
  preparar) preparar ;;
  trocar) trocar ;;
  limpar-destino) limpar_destino "$alvo_pedido" ;;
  *) erro "subcomando inválido: $sub" ;;
esac
