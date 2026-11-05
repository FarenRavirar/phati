#!/usr/bin/env bash
# Prova do `flock` de verdade com a linha de comando de implantar.sh e restaurar.sh (spec 006): `flock -w T -E 75 arquivo
# comando`. Os testes de Node usam um dublê do flock e provam o que o script faz com ele; este prova o que o flock faz.
# Precisa de Linux com util-linux (o job `testes` do CI); o Git Bash do Windows não tem `flock`.
set -euo pipefail

command -v flock >/dev/null 2>&1 || { echo "ERRO: flock ausente; rode em Linux com util-linux" >&2; exit 1; }
d="$(mktemp -d)"
dono=""
trap '[[ -z "$dono" ]] || kill -9 "$dono" 2>/dev/null || true; rm -rf "$d"' EXIT
falha() { echo "FALHA: $*" >&2; exit 1; }

# 1) Com outro processo segurando a trava, o flock desiste com 75 e o comando não roda.
( exec 9>"$d/.trava"; flock -x 9; exec sleep 30 ) &
dono=$!
sleep 1
rc=0
flock -w 1 -E 75 "$d/.trava" touch "$d/rodou" || rc=$?
[[ "$rc" == 75 ]] || falha "com o dono vivo o código devia ser 75, foi $rc"
[[ ! -e "$d/rodou" ]] || falha "o comando rodou sem a trava"

# 2) O dono morre sem limpar nada: o sistema solta a trava, não sobra arquivo de PID para ficar velho.
kill -9 "$dono"
wait "$dono" 2>/dev/null || true
dono=""
sleep 0.5
flock -w 5 -E 75 "$d/.trava" touch "$d/rodou" || falha "depois de o dono morrer a trava devia estar livre"
[[ -e "$d/rodou" ]] || falha "o comando não rodou com a trava livre"

# 3) O código de saída do comando atravessa o flock (a falha da implantação chega ao workflow).
rc=0
flock -w 5 -E 75 "$d/.trava" bash -c 'exit 3' || rc=$?
[[ "$rc" == 3 ]] || falha "o código de saída do comando devia atravessar o flock (3), foi $rc"

# 4) Cinco disputando: um de cada vez dentro da seção crítica.
: > "$d/dentro"
: > "$d/violacoes"
for _ in 1 2 3 4 5; do
  flock -w 30 -E 75 "$d/.trava" bash -c '
    [[ -s "$1/dentro" ]] && echo v >> "$1/violacoes"
    echo x >> "$1/dentro"; sleep 0.3; : > "$1/dentro"' _ "$d" &
done
wait
[[ ! -s "$d/violacoes" ]] || falha "dois processos entraram juntos na seção crítica"

echo "trava_flock_ok"
