#!/usr/bin/env bash
# Restaura um backup do banco na VM (spec 006 R8). Destrutivo: troca os dados atuais pelos do arquivo.
# Uso: restaurar.sh <arquivo.dump> RESTAURAR
# Para o app, valida o dump (gera o SQL antes de apagar qualquer coisa) e troca o schema `public` inteiro numa transação
# única: objetos criados depois do dump somem junto, e qualquer erro desfaz tudo e deixa o banco como estava. O app só
# sobe de novo se a restauração terminar; a saúde, quem chamou confere.
# Troca de banco interrompida (marcador `troca-banco-em-curso`) recusa antes do Docker; o destino do compose segue o
# `banco-ativo`, e divergência com o `.env` recusa (spec 009 R15). O valor lido do `.env` passa por `valor_env` (aspas e
# ` #comentário` saem como no Compose) antes da comparação com banco_novo.
set -Eeuo pipefail

arquivo="${1:-}"
confirmacao="${2:-}"
dir="${PHATI_DIR:-/opt/phati}"
docker="${DOCKER:-docker}"

[[ "$confirmacao" == "RESTAURAR" ]] || { echo "ERRO: a confirmação precisa ser RESTAURAR" >&2; exit 1; }
[[ -n "$arquivo" && -s "$arquivo" ]] || { echo "ERRO: informe um arquivo de backup existente e não vazio" >&2; exit 1; }
[[ "$arquivo" == "$dir"/backups/*.dump && "$arquivo" != *..* ]] || { echo "ERRO: só restaura arquivo de $dir/backups" >&2; exit 1; }
[[ -f "$dir/.env" ]] || { echo "ERRO: $dir/.env ausente" >&2; exit 1; }
# Nome do projeto Compose: `phati` na VM; `PHATI_PROJETO` só troca no ensaio local (spec 009, X4a).
projeto="${PHATI_PROJETO:-phati}"
[[ "$projeto" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || { echo "ERRO: PHATI_PROJETO inválido: use minúsculas, números, _ e -, começando por letra ou número" >&2; exit 1; }
export COMPOSE_PROJECT_NAME="$projeto"
# Banco ativo (spec 009 R15, T5.4c): `banco` até a troca, `banco_novo` depois. Valor fora da lista vira nome de serviço: recusa.
banco_srv=banco
if [[ -f "$dir/banco-ativo" ]]; then banco_srv="$(cat "$dir/banco-ativo")"; fi
[[ "$banco_srv" == banco || "$banco_srv" == banco_novo ]] || { echo "ERRO: $dir/banco-ativo tem valor inválido" >&2; exit 1; }
# O serviço `banco_novo` só existe com o profile da troca: sem ele o compose não o enxerga.
if [[ "$banco_srv" == banco_novo ]]; then export COMPOSE_PROFILES=troca-banco; fi
# Troca de banco interrompida: recusa antes do Docker (restaurar em cima de uma troca no meio é o pior caso).
[[ ! -e "$dir/troca-banco-em-curso" ]] || { echo "ERRO: troca de banco interrompida (marcador $dir/troca-banco-em-curso): reconcilie antes de implantar" >&2; exit 1; }
# Destino do compose igual ao `banco-ativo` (ver implantar.sh): banco_novo vai ao ambiente; divergência recusa. Só essa chave é lida.
# Valor do `.env` como o Compose o lê: aspas que cercam o valor saem e " #comentário" depois dele é cortado.
valor_env() {
  local v="$1"
  v="${v#"${v%%[![:space:]]*}"}"
  if [[ "$v" =~ ^\"([^\"]*)\" || "$v" =~ ^\'([^\']*)\' ]]; then v="${BASH_REMATCH[1]}"; else v="${v%%[[:space:]]#*}"; v="${v%"${v##*[![:space:]]}"}"; fi
  printf '%s' "$v"
}
if [[ "$banco_srv" == banco_novo ]]; then
  export PHATI_BANCO_DESTINO=banco_novo
else
  destino_env="${PHATI_BANCO_DESTINO:-}"
  [[ -n "$destino_env" ]] || destino_env="$(valor_env "$(grep -m1 '^PHATI_BANCO_DESTINO=' "$dir/.env" 2>/dev/null | cut -d= -f2- || true)")"
  [[ "$destino_env" != banco_novo ]] || { echo "ERRO: estado de banco divergente: .env aponta banco_novo, banco-ativo não" >&2; exit 1; }
fi
# X4: mesma ordem do backup.sh e do implantar.sh (ambiente, `.env`, padrão $dir/alvo); a instrução de recuperação a traz.
alvo_dir="${PHATI_ALVO_DIR:-}"
[[ -n "$alvo_dir" ]] || alvo_dir="$(grep -m1 '^PHATI_ALVO_DIR=' "$dir/.env" 2>/dev/null | cut -d= -f2- || true)"
export PHATI_ALVO_DIR="${alvo_dir:-$dir/alvo}"

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
travar "$@"

# Só a pilha ativa para e sobe de novo (`ativa`, azul por padrão antes da primeira troca da spec 009).
ativa=azul
if [[ -f "$dir/ativa" ]]; then ativa="$(cat "$dir/ativa")"; fi
[[ "$ativa" == azul || "$ativa" == verde ]] || { echo "ERRO: $dir/ativa tem valor inválido" >&2; exit 1; }

# Modo lógico concluído (banco-logico, spec 009 E5): o override wal_level entra em todo compose, como no implantar.sh.
extra_logica=()
if [[ -f "$dir/banco-logico" ]]; then
  [[ -f "$dir/repo/servidor/compose.troca-logica.yaml" ]] || { echo "ERRO: banco-logico existe, mas $dir/repo/servidor/compose.troca-logica.yaml não está no clone" >&2; exit 1; }
  extra_logica=(-f "$dir/repo/servidor/compose.troca-logica.yaml")
fi
compor() { "$docker" compose --env-file "$dir/.env" -f "$dir/repo/servidor/compose.yaml" -f "$dir/repo/servidor/compose.implantacao.yaml" ${extra_logica[@]+"${extra_logica[@]}"} "$@"; }

passo=inicio
# A transação única só protege até o `psql`: falha depois dele deixa o banco já restaurado e o app parado.
# O comando de recuperação é o mesmo que `compor` roda, com os caminhos resolvidos: sem o projeto, o `--env-file` e o segundo
# arquivo do compose, ele erraria a configuração ou subiria outro projeto (Greptile, PR #46).
recuperar="PHATI_ALVO_DIR=$PHATI_ALVO_DIR COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME docker compose --env-file $dir/.env -f $dir/repo/servidor/compose.yaml -f $dir/repo/servidor/compose.implantacao.yaml up -d --no-deps app_$ativa"
trap 'if [[ "$passo" == subir-app ]]; then echo "ERRO: o banco foi restaurado, mas o app não subiu; suba com: $recuperar" >&2; else echo "ERRO: a restauração falhou no passo $passo; o banco ficou como estava (transação única) e o app segue parado" >&2; fi' ERR

passo=parar-app
compor stop app_"$ativa"
passo=banco
compor up -d --wait "$banco_srv"
passo=restaurar-dump
# `pg_restore -f` falhando (dump inválido) para antes do `psql`, que só então apaga e recria o schema. O GRANT devolve o
# USAGE que o schema `public` novo não tem e o papel `app` precisa. O SQL temporário (com dado) é apagado ao sair.
compor exec -T "$banco_srv" sh -c 'set -e; trap "rm -f /tmp/restaurar-dump.sql /tmp/restaurar-total.sql" EXIT; export PGPASSWORD="$PHATI_BANCO_DONO_SENHA"; pg_restore --no-owner -f /tmp/restaurar-dump.sql; { echo "DROP SCHEMA public CASCADE;"; echo "CREATE SCHEMA public;"; echo "GRANT USAGE ON SCHEMA public TO PUBLIC;"; cat /tmp/restaurar-dump.sql; } > /tmp/restaurar-total.sql; psql -q -v ON_ERROR_STOP=1 --single-transaction -h 127.0.0.1 -U "$PHATI_BANCO_DONO_USUARIO" -d "$PHATI_BANCO_NOME" -f /tmp/restaurar-total.sql' < "$arquivo"
# Restauração confirmada: o banco mudou para o dump, então o SHA guardado da pilha inativa deixa de valer.
inativa=verde
if [[ "$ativa" == verde ]]; then inativa=azul; fi
rm -f -- "$dir/pilha-$inativa.sha"
passo=subir-app
compor up -d --no-deps app_"$ativa"
echo "restaurado=$(basename "$arquivo")"
