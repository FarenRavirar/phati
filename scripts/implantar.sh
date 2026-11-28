#!/usr/bin/env bash
# Implantação na VM (spec 006 R5, R7, R8; spec 009 Blue-Green). Roda na VM, chamada pela chave SSH de deploy (comando forçado em
# `authorized_keys`): o pedido do cliente chega em SSH_ORIGINAL_COMMAND e é só "<sha>" ou "<sha> --sem-migracao".
# Uso direto: implantar.sh <sha> [--sem-migracao]
# Variáveis: PHATI_DIR (padrão /opt/phati, com `.env` e `repo/`), PHATI_REF (padrão origin/main), DOCKER (para teste),
# PHATI_ALVO_DIR (padrão $PHATI_DIR/alvo, com o `alvo.conf` que o nginx lê), PHATI_TENTATIVAS e PHATI_ESPERA (espera de saúde).
# Estado fora do repositório, escrito só sob a trava: `ativa` (azul ou verde), `pilha-<cor>.sha` (SHA que cada pilha serve).
# Duas pilhas (azul e verde) ficam de pé. A implantação sobe só a inativa (candidata), troca o destino do nginx depois de
# conferi-la e deixa a anterior de pé: o rollback é trocar o destino de volta. Se o `<sha>` pedido é o da pilha inativa e ela
# está saudável, não há build: só troca o destino.
# Troca de banco interrompida (marcador `troca-banco-em-curso`) recusa antes do Docker; destino do compose e `banco-ativo` (e o
# `.env`) têm de apontar o mesmo banco: com banco_novo o destino vai ao ambiente do compose; divergência recusa (spec 009 R15).
# O valor de `PHATI_BANCO_DESTINO` lido do `.env` passa por `valor_env` (aspas e ` #comentário` saem como no Compose) antes da comparação.
# -E: o trap ERR vale dentro de funções; sem ele, falha do Docker sairia calada, sem mensagem nem registro.
set -Eeuo pipefail

if [[ $# -gt 0 ]]; then
  sha="${1:-}"
  opcao="${2:-}"
else
  # Quebra de linha ou CR no pedido recusa o pedido inteiro: `read -r` pararia na primeira linha e o resto seria descartado calado.
  if [[ "${SSH_ORIGINAL_COMMAND:-}" == *$'\n'* || "${SSH_ORIGINAL_COMMAND:-}" == *$'\r'* ]]; then
    echo "ERRO: pedido com quebra de linha ou CR recusado: nada foi executado" >&2
    exit 1
  fi
  read -r sha opcao <<<"${SSH_ORIGINAL_COMMAND:-}" || true
  sha="${sha:-}"
  opcao="${opcao:-}"
fi

dir="${PHATI_DIR:-/opt/phati}"
ref="${PHATI_REF:-origin/main}"
docker="${DOCKER:-docker}"
registro="$dir/implantacoes.log"
# Ordem: ambiente, `.env` da VM, padrão $dir/alvo. O compose exige a variável (`${PHATI_ALVO_DIR:?}`), e o ambiente vence o `.env`.
alvo_dir="${PHATI_ALVO_DIR:-}"
[[ -n "$alvo_dir" ]] || alvo_dir="$(grep -m1 '^PHATI_ALVO_DIR=' "$dir/.env" 2>/dev/null | cut -d= -f2- || true)"
alvo_dir="${alvo_dir:-$dir/alvo}"
alvo_conf="$alvo_dir/alvo.conf"
# Estado da troca no registro: origem e destino entram no fim da linha; `antes_da_troca` diz se a ativa ainda não foi tocada.
origem=""
destino=""
antes_da_troca=1
# Valor do alvo.conf anterior à troca (`trocar` preenche), para reverter quando a gravação de `ativa` falha.
alvo_tinha=0
alvo_antigo=""
ativa=""
host=""
estado=""
# Migração (R4, R5): `migracao` entra no fim do registro; `ativa_parada` vale só entre a parada da ativa e a troca bem-sucedida.
migracao=""
ativa_parada=0
# `esquema_migrado` vale desde antes da migração fora do fluxo: falha depois dela não sabe se o banco já mudou (conta como mudou).
esquema_migrado=0
# App legado da 006 (sem `ativa`): `legado_ids` são os contêineres `app` do projeto, que servem a versão anterior.
legado=0
legado_ids=""
backup_arquivo=""
# X3c: `anterior` é o SHA que estava no clone; `repo_mudou` vale depois do checkout do SHA novo (erro() devolve o clone).
anterior=""
repo_mudou=0
# `clone_fica`: a candidata segue no alvo.conf sem pilha anterior para voltar; erro() deixa o clone no SHA dela.
clone_fica=0

registrar() {
  local extra=""
  [[ -z "$origem" ]] || extra+=" origem=$origem"
  [[ -z "$destino" ]] || extra+=" destino=$destino"
  [[ -z "$migracao" ]] || extra+=" migracao=$migracao"
  printf '%s %s %s%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${sha:-sem-sha}" "$*" "$extra" >> "$registro" 2>/dev/null || true
}
# Comando compose para o operador colar: caminhos e nome do projeto saem com `printf %q` (espaço ou caractere de shell não
# divide o comando). Texto igual ao antigo para valor simples; o `$1` é texto fixo do script.
comando_compose() {
  printf 'PHATI_ALVO_DIR=%q COMPOSE_PROJECT_NAME=%q docker compose --env-file %q -f %q -f %q %s\n' "$alvo_dir" "$COMPOSE_PROJECT_NAME" "$dir/.env" "$dir/repo/servidor/compose.yaml" "$dir/repo/servidor/compose.implantacao.yaml" "$1"
}
# Comando exato para subir a ativa de volta (usado quando ela foi parada e a implantação falhou depois).
comando_subir_ativa() {
  if [[ -z "$ativa" ]]; then echo "$docker start ${legado_ids//$'\n'/ }"; return; fi
  comando_compose "up -d --no-deps app_$ativa"
}
# Primeiro arquivo de infraestrutura que falta em $1 (commit); vazio = completa. Só arquivo regular (100644/100755) serve à
# montagem: link simbólico (120000) ou diretório (040000) com o mesmo nome não serve (medido com git ls-tree).
infra_faltando() {
  local rev="$1" arq modo
  for arq in servidor/compose.implantacao.yaml servidor/nginx/default.conf; do
    modo="$(git ls-tree "$rev" -- "$arq" | cut -d' ' -f1)"
    [[ "$modo" == 100644 || "$modo" == 100755 ]] || { echo "$arq"; return 0; }
  done
}
# A candidata segue no alvo.conf sem pilha anterior para voltar: o clone fica no SHA dela (erro() só devolve o clone quando a anterior volta a servir).
erro_candidata_no_ar() {
  clone_fica=1
  erro "$@"
}
erro() {
  echo "ERRO: $*" >&2
  # Dois casos. Falha depois da migração fora do fluxo: o banco já mudou, então nada de subir a versão anterior às cegas.
  # Falha antes disso: a pilha que servia (ou o app legado) segue, e o aviso diz como subi-la se foi parada.
  if [[ "$esquema_migrado" == 1 ]]; then
    echo "AVISO: o esquema JÁ foi migrado pela migração fora do fluxo; a pilha da versão anterior (${ativa:-app legado}) pode não ser compatível com ele. Não há restauração automática: recupere à mão um par compatível (código e esquema) a partir do backup verificado ($backup_arquivo)." >&2
  elif [[ "$ativa_parada" == 1 ]]; then
    echo "AVISO: a pilha ativa (${ativa:-app legado}) foi parada para a migração fora do fluxo e NÃO serve. Suba com: $(comando_subir_ativa)" >&2
  elif [[ "$antes_da_troca" == 1 && -n "$ativa" ]]; then
    echo "AVISO: a pilha ativa ($ativa) segue servindo." >&2
  elif [[ "$antes_da_troca" == 1 && "$legado" == 1 ]]; then
    echo "AVISO: o app legado da 006 segue servindo." >&2
  fi
  # X3c: o clone não pode ficar no SHA que falhou (uma reinicialização da VM leria o default.conf dele). Só volta ao SHA que
  # estava no ar; falha do checkout é avisada e não troca a mensagem do erro original.
  if [[ "$repo_mudou" == 1 && "$anterior" != "$sha" ]] && git cat-file -e "$anterior^{commit}" 2>/dev/null; then
    if [[ -n "$(infra_faltando "$anterior")" ]]; then
      # Voltar a um SHA sem a infraestrutura põe o servidor/nginx de volta no bug da VM: o clone fica no SHA que passou na pré-checagem.
      registrar "repo-mantido=${sha:0:12}: anterior sem infraestrutura blue-green"
    elif [[ "$clone_fica" == 1 ]]; then
      registrar "repo-mantido=${sha:0:12}: a candidata segue no alvo.conf"
    elif git -C "$dir/repo" checkout -q --detach "$anterior" 2>/dev/null; then
      registrar "repo-restaurado=${anterior:0:12}"
    else
      echo "AVISO: não consegui devolver o repositório a ${anterior:0:12}; corrija antes de reiniciar a VM" >&2
    fi
  fi
  registrar "FALHOU: $*"
  exit 1
}

# Nome do projeto Compose: `phati` na VM; `PHATI_PROJETO` só troca no ensaio local (spec 009, X4a). Valor inválido para antes de qualquer ação.
projeto="${PHATI_PROJETO:-phati}"
[[ "$projeto" =~ ^[a-z0-9][a-z0-9_-]*$ ]] || erro "PHATI_PROJETO inválido: use minúsculas, números, _ e -, começando por letra ou número"
export COMPOSE_PROJECT_NAME="$projeto"
# Banco ativo (spec 009 R15, T5.4c): `banco` até a troca, `banco_novo` depois (o trocar-banco.sh grava `banco-ativo`). Valor
# fora da lista vira nome de serviço do compose: recusa antes de qualquer chamada ao Docker.
banco_srv=banco
if [[ -f "$dir/banco-ativo" ]]; then banco_srv="$(cat "$dir/banco-ativo")"; fi
[[ "$banco_srv" == banco || "$banco_srv" == banco_novo ]] || erro "$dir/banco-ativo tem valor inválido"
# O serviço `banco_novo` só existe com o profile da troca: sem ele o compose não o enxerga.
if [[ "$banco_srv" == banco_novo ]]; then export COMPOSE_PROFILES=troca-banco; fi
volume_banco="dados_$banco_srv"
# Troca de banco interrompida (spec 009 R15): o marcador do trocar-banco.sh recusa antes de qualquer chamada ao Docker.
[[ ! -e "$dir/troca-banco-em-curso" ]] || erro "troca de banco interrompida (marcador $dir/troca-banco-em-curso): reconcilie antes de implantar"
# O destino do compose (`PHATI_BANCO_DESTINO`) tem de dizer o mesmo banco que `banco-ativo`, nas duas direções (volta): vazio conta
# como banco, o padrão do compose. Com banco_novo, o ambiente vence o `.env` (`--env-file`): exporta. Com banco, o destino tem de ser
# banco ou vazio; banco_novo é divergência (a checagem de banco_novo recusa o que não for banco_novo). Só essa chave é lida.
# Valor do `.env` como o Compose o lê: aspas que cercam o valor saem e ` #comentário` depois dele é cortado (sem isso, `"banco_novo"`
# passaria pela comparação e o compose receberia banco_novo mesmo com banco-ativo=banco).
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
# Falha cedo e com instrução, antes de qualquer passo: o implantar.sh instalado sem o backup.sh ao lado pararia no backup.
[[ -f "$(dirname "$0")/backup.sh" ]] || erro "backup.sh ausente ao lado de $0; instale-o junto, como administrador"
travar "$@"

# Host público para o `Host:` da verificação pelo nginx: o primeiro de PHATI_HOSTS_PERMITIDOS (lido, nunca impresso).
host_publico() {
  host="$(grep -m1 '^PHATI_HOSTS_PERMITIDOS=' "$dir/.env" || true)"
  host="${host#PHATI_HOSTS_PERMITIDOS=}"
  host="${host%%,*}"
  [[ -n "$host" ]] || host=localhost
  [[ "$host" =~ ^[A-Za-z0-9.-]+$ ]] || erro "primeiro host de PHATI_HOSTS_PERMITIDOS inválido"
}
host_publico

cd "$dir/repo"
git fetch -q origin
git cat-file -e "$sha^{commit}" 2>/dev/null || erro "o SHA $sha não existe no repositório"
git merge-base --is-ancestor "$sha" "$ref" || erro "o SHA $sha não é ancestral de $ref: só entra o que foi promovido"
# Antes do checkout: sem a infraestrutura, o checkout apaga o `servidor/nginx` que o nginx monta (bug da VM, spec 009 T3.4).
faltando="$(infra_faltando "$sha")"
[[ -z "$faltando" ]] || erro "o SHA não traz a infraestrutura de implantação blue-green: $faltando"
# O banco ativo tem de existir no compose do SHA: sem o serviço, o compose quebra depois do checkout. `banco` é sempre declarado.
if [[ "$banco_srv" != banco ]]; then
  compose_sha="$(git show "$sha:servidor/compose.implantacao.yaml" 2>/dev/null || true)"
  grep -qE "^  $banco_srv:" <<<"$compose_sha" || erro "o SHA não declara o serviço $banco_srv no compose de implantação"
fi
anterior="$(git rev-parse HEAD 2>/dev/null || echo nenhum)"
git checkout -q --detach "$sha"
repo_mudou=1
# O script em execução é a cópia instalada fora do clone; avisa se a do repositório mudou e precisa ser reinstalada.
if [[ -f scripts/implantar.sh && -f "$0" ]] && ! cmp -s scripts/implantar.sh "$0"; then
  echo "AVISO: o implantar.sh instalado difere do repositório; reinstale como administrador" >&2
fi

# O compose monta este diretório em /etc/nginx/alvo; o mesmo caminho é o que o script escreve (variável obrigatória lá).
export PHATI_ALVO_DIR="$alvo_dir"
# Modo lógico concluído (banco-logico, spec 009 E5): sem o override, o `up` do banco recriaria o banco_novo sem wal_level=logical.
extra_logica=()
if [[ -f "$dir/banco-logico" ]]; then
  # Depois do checkout: `erro` devolve o clone ao SHA anterior (X3c); `exit 1` deixaria o clone no SHA recusado.
  [[ -f "$dir/repo/servidor/compose.troca-logica.yaml" ]] || erro "banco-logico existe, mas $dir/repo/servidor/compose.troca-logica.yaml não está no clone"
  extra_logica=(-f "$dir/repo/servidor/compose.troca-logica.yaml")
fi
compor() { "$docker" compose --env-file "$dir/.env" -f "$dir/repo/servidor/compose.yaml" -f "$dir/repo/servidor/compose.implantacao.yaml" ${extra_logica[@]+"${extra_logica[@]}"} "$@"; }
mkdir -p "$alvo_dir"

passo=inicio
trap 'erro "falhou no passo: $passo"' ERR
registrar "inicio anterior=${anterior:0:12}"

# Estado: sem `ativa` é a primeira implantação, e a candidata é azul. Com `ativa`, a candidata é a outra pilha.
if [[ -f "$dir/ativa" ]]; then
  ativa="$(cat "$dir/ativa")"
  [[ "$ativa" == azul || "$ativa" == verde ]] || erro "$dir/ativa tem valor inválido"
fi
# Divergência ativa x alvo.conf (falha da reversão pós-troca grava `ativa` antiga com o destino novo no nginx): recusa antes de
# calcular a candidata e antes de qualquer chamada ao Docker, senão a próxima implantação sobrescreveria a pilha que serve.
if [[ -n "$ativa" && -e "$alvo_conf" ]]; then
  servida="$(grep -E '^set \$pilha (azul|verde);$' "$alvo_conf" 2>/dev/null | grep -oE 'azul|verde' || true)"
  if [[ "$servida" != "$ativa" ]]; then
    antes_da_troca=0
    erro "ativa=$ativa mas alvo.conf serve ${servida:-outra coisa}: reconcilie à mão antes de implantar"
  fi
fi
outra() { local atual="$1"; if [[ "$atual" == azul ]]; then echo verde; else echo azul; fi; }
if [[ -n "$ativa" ]]; then cand="$(outra "$ativa")"; else cand=azul; fi
primeira=0
[[ -n "$ativa" ]] || primeira=1
# X1: sem `ativa`, um contêiner `app` do projeto é o legado da 006, que serve a versão anterior (vale como base da verificação).
if [[ -z "$ativa" ]]; then
  legado_ids="$("$docker" ps -aq --filter label=com.docker.compose.project=$COMPOSE_PROJECT_NAME --filter label=com.docker.compose.service=app)"
  [[ -z "$legado_ids" ]] || legado=1
fi

# Grava $2 em $1 de forma atômica: temporário no mesmo diretório e `mv`, para ninguém ler a escrita pela metade.
gravar_atomico() {
  local tmp destino="$1" conteudo="$2"
  tmp="$(mktemp "$(dirname "$destino")/.tmp.XXXXXX")"
  # Falha em qualquer passo apaga o temporário (senão sobra `.tmp.*` no diretório que o nginx monta).
  printf '%s\n' "$conteudo" > "$tmp" && chmod 644 "$tmp" && mv -f "$tmp" "$destino" || { rm -f "$tmp"; return 1; }
}
# Mesmo contrato de `servidor/nginx/alvo/alvo.conf`: `$alvo` é o app e `$pilha` o volume de estáticos.
conteudo_alvo() { local cor="$1"; printf 'set $alvo app_%s;\nset $pilha %s;' "$cor" "$cor"; }

# nginx -t e reload. Sem `ativa` não há nginx com o `alvo.conf` novo (o da 006 não monta o diretório): sobe o contêiner, que
# lê o alvo.conf ao iniciar. Com `ativa`, valida e recarrega o que já está de pé.
nginx_recarrega() {
  if [[ -z "$ativa" ]]; then
    compor run --rm --no-deps nginx nginx -t >/dev/null || return 1
    compor up -d --no-deps nginx >/dev/null || return 1
    return 0
  fi
  compor exec -T nginx nginx -t >/dev/null || return 1
  compor exec -T nginx nginx -s reload >/dev/null || return 1
}
# Autocura do nginx, antes de qualquer build ou troca. Se o clone foi recriado sob um nginx existente, o bind de
# `servidor/nginx` aponta para diretório vazio: o contêiner é recriado (lê o alvo.conf atual ao subir). Sem contêiner nginx
# (primeira implantação de verdade), não faz nada. A marca sim/nao vem do próprio contêiner: falha do exec é erro, não
# "arquivo ausente". Com a recriação antes da troca, o alvo.conf ainda é o anterior: a reversão de `trocar` não precisa recarregar.
# Legado da 006 sem `ativa` e sem alvo.conf: nada a curar; `trocar` grava o alvo.conf e sobe o nginx. Falha do inspect ou
# saída fora de true/false não é "parado": para antes de validar ou recriar.
nginx_autocura() {
  local id marca estado motivo=parado
  id="$("$docker" ps -aq --filter label=com.docker.compose.project=$COMPOSE_PROJECT_NAME --filter label=com.docker.compose.service=nginx)"
  [[ -n "$id" ]] || return 0
  [[ -n "$ativa" || -f "$alvo_conf" ]] || return 0
  if ! estado="$("$docker" inspect -f '{{.State.Running}}' "$id" 2>/dev/null)" || [[ "$estado" != true && "$estado" != false ]]; then
    registrar "nginx-estado-falhou"
    echo "ERRO: não consegui verificar o estado do nginx (inspect falhou ou saída inesperada)" >&2
    return 1
  fi
  if [[ "$estado" == true ]]; then
    motivo=bind-obsoleto
    marca="$(compor exec -T nginx sh -c 'if [ -f /etc/nginx/conf.d/default.conf ]; then echo sim; else echo nao; fi')" || marca=""
    if [[ "$marca" != sim && "$marca" != nao ]]; then
      registrar "nginx-verificacao-falhou"
      echo "ERRO: não consegui verificar /etc/nginx/conf.d/default.conf no nginx (exec falhou ou saída inesperada)" >&2
      return 1
    fi
    [[ "$marca" == nao ]] || return 0
  fi
  # Valida a config do clone num contêiner novo antes de recriar o nginx existente: reprovada, ele segue como está.
  compor run --rm --no-deps nginx nginx -t >/dev/null || return 1
  compor up -d --no-deps --force-recreate nginx >/dev/null || return 1
  registrar "nginx-recriado=$motivo"
  compor exec -T nginx nginx -t >/dev/null || return 1
}
# Confere pelo próprio nginx (a rota que o usuário recebe). A recarga é assíncrona: tenta de novo algumas vezes.
verificar_nginx() {
  local _
  for _ in $(seq "${PHATI_TENTATIVAS:-60}"); do
    compor exec -T nginx wget -q -O /dev/null --header "Host: $host" http://127.0.0.1:8080/saude >/dev/null 2>&1 && return 0
    sleep "${PHATI_ESPERA:-2}"
  done
  return 1
}
# Espera a saúde por laço de `docker inspect`. Não usa `up --wait`: ele espera o projeto inteiro, não o serviço.
esperar_saude() {
  local _ id svc="$1"
  estado=""
  for _ in $(seq "${PHATI_TENTATIVAS:-60}"); do
    id="$(compor ps -q "$svc" 2>/dev/null || true)"
    [[ -z "$id" ]] || estado="$("$docker" inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || true)"
    [[ "$estado" == healthy ]] && return 0
    sleep "${PHATI_ESPERA:-2}"
  done
  return 1
}
saudavel_agora() {
  local id svc="$1"
  id="$(compor ps -q "$svc" 2>/dev/null || true)"
  [[ -n "$id" && "$("$docker" inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || true)" == healthy ]]
}
# Comando completo de recuperação (usado quando a reversão também falha). Vazio = nenhuma pilha servia antes.
comando_recuperacao() {
  local ativa_antes="$1" grava
  # Sem pilha anterior o alvo.conf nunca é removido (o nginx monta o diretório, e sem o arquivo ele não sobe): o comando sobe o nginx, que lê o arquivo atual.
  if [[ -z "$ativa_antes" ]]; then echo "$(comando_compose "up -d --no-deps nginx")"; return; fi
  # A ativa volta antes do alvo.conf: se só o alvo.conf voltasse, a ativa ficaria na candidata e a próxima implantação recusaria a divergência.
  local ativa_grava="printf '%s\\n' $ativa_antes > $(printf '%q' "$dir/ativa")"
  grava="printf 'set \$alvo app_$ativa_antes;\\nset \$pilha $ativa_antes;\\n' > $(printf '%q' "$alvo_conf")"
  echo "$ativa_grava && $grava && $(comando_compose "exec -T nginx nginx -s reload")"
}
# Comando para subir só o túnel à mão, quando o cloudflared falhou depois da troca.
comando_tunel() {
  comando_compose "up -d --no-deps cloudflared"
}

# Devolve o alvo.conf anterior ($2, se $1 = 1) e recarrega se o nginx já tinha recarregado o destino novo ($3 = 1). Sai com erro.
reverter() {
  local tinha="$1" antigo="$2" recarregou="$3" motivo="$4" recuperar
  recuperar="$(comando_recuperacao "$ativa")"
  if [[ "$tinha" == 1 ]]; then
    gravar_atomico "$alvo_conf" "$antigo" || erro "$motivo; falha ao gravar o alvo.conf anterior; recupere com: $recuperar"
  elif [[ -n "$ativa" ]]; then
    # Sem alvo.conf antes (ativa sem o arquivo): grava o destino da ativa. Remover o arquivo deixaria o nginx sem config.
    gravar_atomico "$alvo_conf" "$(conteudo_alvo "$ativa")" || erro "$motivo; falha ao gravar o alvo.conf de app_$ativa; recupere com: $recuperar"
  fi
  # Sem alvo.conf antes e sem ativa (primeira implantação): o arquivo fica com a candidata, que é o que o nginx serve.
  if [[ "$recarregou" == 1 ]] && ! nginx_recarrega; then
    # Sem pilha anterior nada foi revertido: o arquivo segue com a candidata, e o comando de recuperação só sobe o nginx.
    if [[ "$tinha" != 1 && -z "$ativa" ]]; then
      erro_candidata_no_ar "$motivo; sem pilha anterior: alvo.conf segue apontando app_$cand, mas o nginx não recarregou; recupere com: $recuperar"
    fi
    erro "$motivo; alvo.conf revertido, mas o nginx não recarregou; recupere com: $recuperar"
  fi
  if [[ -n "$ativa" ]]; then
    if [[ "$esquema_migrado" == 1 ]]; then
      erro "$motivo; alvo.conf revertido para app_$ativa, mas o esquema já foi migrado: não subo a versão anterior às cegas (ver AVISO)"
    fi
    if [[ "$ativa_parada" == 1 ]]; then
      erro "$motivo; alvo.conf revertido para app_$ativa, mas ela foi parada: suba com $(comando_subir_ativa)"
    fi
    erro "$motivo; alvo.conf revertido para app_$ativa, que segue servindo"
  fi
  [[ "$tinha" != 1 ]] || erro "$motivo; alvo.conf anterior restaurado (nenhuma pilha servia antes)"
  erro_candidata_no_ar "$motivo; sem pilha anterior: alvo.conf segue apontando app_$cand"
}

# Troca o destino do nginx para a cor $1: grava o alvo.conf, confere `nginx -t`, recarrega e verifica /saude pelo nginx.
# O alvo.conf anterior fica em `alvo_tinha`/`alvo_antigo` para `ativa`, gravada logo depois, reverter junto se falhar.
trocar() {
  local novo="$1"
  alvo_tinha=0
  alvo_antigo=""
  if [[ -f "$alvo_conf" ]]; then alvo_tinha=1; alvo_antigo="$(cat "$alvo_conf")"; fi
  # Falha ao gravar o alvo.conf deixa a ativa servindo (antes_da_troca segue 1: o aviso diz isso).
  gravar_atomico "$alvo_conf" "$(conteudo_alvo "$novo")"
  antes_da_troca=0
  if ! nginx_recarrega; then
    reverter "$alvo_tinha" "$alvo_antigo" 0 "nginx -t ou reload falhou"
  fi
  if ! verificar_nginx; then
    reverter "$alvo_tinha" "$alvo_antigo" 1 "/saude pelo nginx falhou depois do reload"
  fi
}

# Autocura antes de qualquer build ou troca (o rollback também usa o nginx): sem ela, o bind obsoleto segue até uma reinicialização.
passo=autocura-nginx
nginx_autocura || erro "nginx de pé não pôde ser recriado com a config do clone"

# Rollback: o SHA é o da pilha inativa e ela está saudável. Não há build nem migração; só o destino muda.
passo=rollback-rapido
if [[ -n "$ativa" && "$(cat "$dir/pilha-$cand.sha" 2>/dev/null || true)" == "$sha" ]] && saudavel_agora "app_$cand"; then
  origem="$ativa"
  destino="$cand"
  trocar "$cand"
  # Se gravar `ativa` falha, o alvo.conf já aponta a candidata: reverte o alvo.conf e avisa (senão os dois estados divergem).
  gravar_atomico "$dir/ativa" "$cand" || reverter "$alvo_tinha" "$alvo_antigo" 1 "falha ao gravar ativa=$cand"
  migracao=pulada
  trap - ERR
  registrar "OK"
  echo "implantado=${sha:0:12} ativa=$cand anterior=$ativa"
  exit 0
fi

# Implantação normal: a candidata sobe ao lado da ativa, e o destino só muda depois de ela estar saudável.
passo=backup
tem_dados=0
if [[ -n "$(compor ps -q "$banco_srv" 2>/dev/null)" ]] || "$docker" volume inspect "${COMPOSE_PROJECT_NAME}_$volume_banco" >/dev/null 2>&1; then
  tem_dados=1
fi
if [[ "$tem_dados" == 1 && "$opcao" != "--sem-migracao" ]]; then
  # Banco parado com volume é instalação existente: sobe o banco e tira o backup antes de migrar.
  compor up -d --wait "$banco_srv"
  # backup.sh fica ao lado deste script (na VM, em /opt/phati/bin, de dono root, como ele).
  backup_arquivo="$(PHATI_DIR="$dir" DOCKER="$docker" bash "$(dirname "$0")/backup.sh" "${anterior:0:12}")"
elif [[ "$tem_dados" == 0 ]]; then
  echo "sem banco nem volume: primeira implantação, sem backup"
fi

passo=build
# Só a candidata e os one-shots: a ativa segue de pé com a imagem que já tem.
compor build app_"$cand" migracao estaticos_"$cand" pacotes_dono camadas_dono banco_extensoes pgb_auth

passo=banco
compor up -d --wait "$banco_srv"
# PostGIS em volume que já existia (o init só roda em volume vazio). Commit antigo sem o serviço: pula e segue.
# `servicos=$(...)` fora do `if` faz falha do Compose cair no ERR, não virar "pulado" (falha fechada).
passo=extensoes
servicos="$(compor config --services)"
if grep -qx banco_extensoes <<<"$servicos"; then
  compor run --rm banco_extensoes
else
  echo "pulado: compose sem banco_extensoes"
  registrar "pulado: compose sem banco_extensoes"
fi

# PgBouncer permanente na frente do banco (R18): auth gerado, depois os dois processos, que a app já usa.
# shortcut: o PgBouncer não é recriado por este fluxo se já está de pé (recriar pgb_ns derruba o banco da ativa). Mudança de
# configuração do PgBouncer é procedimento manual, um processo por vez, com `docker kill -s TERM` (nunca `SHUTDOWN` por console);
# upgrade: quando houver rotina de reconfiguração no script (X3b).
pgb_no_ar=0
if saudavel_agora pgb1 && saudavel_agora pgb2 && [[ -n "$(compor ps -q pgb_ns 2>/dev/null || true)" ]]; then
  pgb_no_ar=1
fi
passo=pgb
if [[ "$pgb_no_ar" == 0 ]]; then
  passo=pgb-auth
  compor run --rm --no-deps pgb_auth
  compor up -d --no-deps pgb_ns pgb1 pgb2
  for svc in pgb1 pgb2; do
    esperar_saude "$svc" || erro "$svc não ficou saudável (estado: ${estado:-desconhecido})"
  done
fi

passo=migracao
migracao=pulada
if [[ "$opcao" != "--sem-migracao" ]]; then
  migracao=nenhuma
  # R17: nenhuma migração entre o início da replicação lógica e a troca (DDL não é replicado). A publicação criada pelo
  # trocar-banco.sh existe na origem desde antes do marcador da troca; qualquer publicação na origem recusa a migração.
  # Consulta que falha recusa também (fecha falhado).
  publicacoes="$(compor exec -T "$banco_srv" sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -X -At -v ON_ERROR_STOP=1 -h 127.0.0.1 -U postgres -d "${PHATI_BANCO_NOME:-phati}" -c "SELECT count(*) FROM pg_publication"')" \
    || erro "não consegui conferir a replicação lógica em $banco_srv (R17): migração não roda"
  [[ "$publicacoes" =~ ^[0-9]+$ ]] || erro "saída inesperada ao conferir a replicação lógica (R17): migração não roda"
  [[ "$publicacoes" == 0 ]] || erro "replicação lógica em curso (publicação na origem): migração não roda (R17); termine ou reverta a troca de banco antes"
  # Backup verificado antes de qualquer migração com arquivo a verificar (R8): o caminho vem do backup.sh.
  exigir_backup() {
    [[ -n "$backup_arquivo" && -s "$backup_arquivo" ]] || erro "backup verificado ausente ou vazio: a migração não roda"
  }
  # R4 e R5: com `ativa`, a versão anterior segue de pé e a migração tem de ser compatível com ela. Sem `ativa` (primeira
  # implantação) ninguém serve a anterior: nada a verificar.
  if [[ -n "$ativa" || "$legado" == 1 ]]; then
    # Base: a pilha ativa; sem ela, o legado da 006 serve o SHA que estava no clone antes deste checkout (`anterior`).
    if [[ -n "$ativa" ]]; then base="$(cat "$dir/pilha-$ativa.sha" 2>/dev/null || true)"; else base="$anterior"; fi
    git cat-file -e "$base^{commit}" 2>/dev/null || erro "base da verificação de migração ($base) não existe no repositório: não aprovo calado"
    # -z e array NUL: nome de arquivo hostil (espaço, `;`, `$(...)`, quebra de linha) não vira shell nem quebra a lista.
    lista="$(mktemp)"
    git diff --name-only -z --diff-filter=AM "$base" "$sha" -- 'servidor/*/migrations/[0-9]*.py' > "$lista"
    novos=()
    mapfile -d '' -t novos < "$lista"
    rm -f "$lista"
    arquivos=()
    for f in "${novos[@]}"; do arquivos+=("${f#servidor/}"); done
    if [[ "${#arquivos[@]}" -gt 0 ]]; then
      rc=0
      saida="$(compor run --rm --no-deps migracao python -m comum.compat_migracao "${arquivos[@]}" 2>&1)" || rc=$?
      linhas="$(grep '^REPROVADA' <<<"$saida" || true)"
      case "$rc" in
        0) migracao=compativel ;;
        1|2) erro "migração reprovada pelo verificador (rc $rc); nada foi migrado; a pilha ativa segue servindo. ${linhas:-$saida} Torne a migração aditiva (expand-only) ou, se for incompatível por design, marque '# bluegreen: incompativel-por-design' e use o procedimento manual." ;;
        3) migracao=fora-do-fluxo
           if [[ "${PHATI_ACEITO_PARADA:-}" != 1 ]]; then
             erro "migração incompatível por design: exige parada do site, janela e aprovação do mantenedor; nada foi parado. $saida"
           fi ;;
        *) erro "saída inesperada do verificador de migração (rc $rc): fecha falhado" ;;
      esac
      if [[ "$migracao" == compativel || "$migracao" == fora-do-fluxo ]]; then exigir_backup; fi
      if [[ "$migracao" == fora-do-fluxo ]]; then
        echo "AVISO: migração incompatível por design (PHATI_ACEITO_PARADA=1): o site FICA FORA DO AR até a candidata subir." >&2
        if [[ -n "$ativa" ]]; then compor stop app_"$ativa"; else "$docker" stop $legado_ids >/dev/null; fi
        ativa_parada=1
      fi
    fi
  fi
  # Migração fora do fluxo: a partir daqui o banco pode ter mudado; `erro()` então não manda subir a versão anterior.
  if [[ "$migracao" == fora-do-fluxo ]]; then esquema_migrado=1; fi
  compor run --rm migracao
fi
# `up --no-deps` não dispara o depends_on: os donos dos volumes de pacotes e camadas rodam aqui, antes da candidata.
passo=estaticos
compor run --rm --no-deps estaticos_"$cand"
passo=pacotes-dono
compor run --rm --no-deps pacotes_dono
passo=camadas-dono
compor run --rm --no-deps camadas_dono
passo=app-candidata
# X3c: o estado não pode mentir. Antes de (re)criar a candidata, tira o SHA antigo dela: a partir daqui o contêiner roda
# código novo. Só grava o SHA novo quando ela ficou saudável (a troca pode falhar depois: a pilha roda esse SHA mesmo assim).
rm -f "$dir/pilha-$cand.sha"
compor up -d --no-deps app_"$cand"
esperar_saude "app_$cand" || erro "a candidata app_$cand não ficou saudável (estado: ${estado:-desconhecido})"
gravar_atomico "$dir/pilha-$cand.sha" "$sha"

passo=troca
origem="${ativa:-nenhuma}"
destino="$cand"
trocar "$cand"
gravar_atomico "$dir/ativa" "$cand" || reverter "$alvo_tinha" "$alvo_antigo" 1 "falha ao gravar ativa=$cand"
ativa_parada=0
passo=nginx-e-tunel
# A pilha anterior fica de pé (rollback instantâneo). O nginx já recarregou; os dois `up` só garantem nginx e cloudflared.
# R9: falha aqui é depois da troca, então reverte a troca: `ativa` volta ao anterior antes, para o estado não divergir do alvo.
# Dois `up` (e não um) para a mensagem dizer qual falhou; sem o nginx, o cloudflared não é tentado.
falhou=""
compor up -d --no-deps nginx || falhou=nginx
if [[ -z "$falhou" ]]; then compor up -d --no-deps cloudflared || falhou=cloudflared; fi
if [[ -n "$falhou" ]]; then
  if [[ "$falhou" == nginx ]]; then
    motivo="nginx falhou depois da troca; cloudflared não foi tentado"
  else
    motivo="cloudflared falhou depois da troca; o túnel segue fora, suba à mão com: $(comando_tunel)"
  fi
  # Migração fora do fluxo (X2 + Codex P1): a ativa anterior foi parada e o esquema já mudou. Voltar a ela agora derruba a candidata.
  if [[ "$esquema_migrado" == 1 ]]; then
    erro_candidata_no_ar "$falhou falhou depois da troca; esquema já migrado: não volto à versão anterior (ver AVISO); a candidata app_$cand segue no alvo.conf. Suba $falhou à mão com: $(comando_compose "up -d --no-deps $falhou")"
  fi
  # Primeira implantação (sem ativa): a candidata já está em `ativa` e no alvo.conf, e não há pilha anterior para reverter.
  # Não remove nem reverte o alvo.conf (o nginx monta o diretório): diz o que subir à mão.
  if [[ -z "$ativa" ]]; then
    if [[ "$falhou" == nginx ]]; then
      motivo+="; suba o nginx à mão com: $(comando_compose "up -d --no-deps nginx")"
    fi
    erro_candidata_no_ar "$motivo; sem pilha anterior: a candidata app_$cand segue no alvo.conf e em ativa, nada revertido"
  fi
  gravar_atomico "$dir/ativa" "$ativa" || erro "$motivo; falha ao regravar ativa=$ativa; recupere com: $(comando_recuperacao "$ativa")"
  reverter "$alvo_tinha" "$alvo_antigo" 1 "$motivo"
fi
# Primeira implantação sobre o layout da 006 (contêiner `app` órfão): só sai depois da troca bem-sucedida. Volumes não são
# tocados; o `phati_estaticos` antigo fica como pendência manual. Antes da troca o site segue pelo nginx e pelo app antigos;
# a troca recria o nginx (blip de ~1 s, não medido).
passo=orfao
if [[ "$primeira" == 1 ]]; then
  for id in $("$docker" ps -aq --filter label=com.docker.compose.project=$COMPOSE_PROJECT_NAME --filter label=com.docker.compose.service=app); do
    # Depois da troca a pilha nova já serve: falha aqui não reverte nada, só diz o que sobrou para remover à mão.
    "$docker" rm -f "$id" >/dev/null || erro "a troca já foi feita (ativa=$cand), mas não consegui remover o app órfão $id: remova à mão com: $docker rm -f $id"
    registrar "removido-orfao=app"
  done
fi
trap - ERR
registrar "OK"
echo "implantado=${sha:0:12} ativa=$cand anterior=${ativa:-nenhuma}"
