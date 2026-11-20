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
alvo_dir="${PHATI_ALVO_DIR:-$dir/alvo}"
alvo_conf="$alvo_dir/alvo.conf"
# Estado da troca no registro: origem e destino entram no fim da linha; `antes_da_troca` diz se a ativa ainda não foi tocada.
origem=""
destino=""
antes_da_troca=1
ativa=""
host=""
estado=""
# Migração (R4, R5): `migracao` entra no fim do registro; `ativa_parada` vale só entre a parada da ativa e a troca bem-sucedida.
migracao=""
ativa_parada=0
backup_arquivo=""
# X3c: `anterior` é o SHA que estava no clone; `repo_mudou` vale depois do checkout do SHA novo (erro() devolve o clone).
anterior=""
repo_mudou=0

registrar() {
  local extra=""
  [[ -z "$origem" ]] || extra+=" origem=$origem"
  [[ -z "$destino" ]] || extra+=" destino=$destino"
  [[ -z "$migracao" ]] || extra+=" migracao=$migracao"
  printf '%s %s %s%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${sha:-sem-sha}" "$*" "$extra" >> "$registro" 2>/dev/null || true
}
# Comando exato para subir a ativa de volta (usado quando ela foi parada e a implantação falhou depois).
comando_subir_ativa() {
  echo "COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME docker compose --env-file $dir/.env -f $dir/repo/servidor/compose.yaml -f $dir/repo/servidor/compose.implantacao.yaml up -d --no-deps app_$ativa"
}
erro() {
  echo "ERRO: $*" >&2
  if [[ -n "$ativa" && "$antes_da_troca" == 1 && "$ativa_parada" == 0 ]]; then
    echo "AVISO: a pilha ativa ($ativa) segue servindo." >&2
  fi
  if [[ "$ativa_parada" == 1 ]]; then
    echo "AVISO: a pilha ativa ($ativa) foi parada para a migração fora do fluxo e NÃO serve. Suba com: $(comando_subir_ativa)" >&2
  fi
  # X3c: o clone não pode ficar no SHA que falhou (uma reinicialização da VM leria o default.conf dele). Só volta ao SHA que
  # estava no ar; falha do checkout é avisada e não troca a mensagem do erro original.
  if [[ "$repo_mudou" == 1 && "$anterior" != "$sha" ]] && git cat-file -e "$anterior^{commit}" 2>/dev/null; then
    if git -C "$dir/repo" checkout -q --detach "$anterior" 2>/dev/null; then
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
anterior="$(git rev-parse HEAD 2>/dev/null || echo nenhum)"
git checkout -q --detach "$sha"
repo_mudou=1
# O script em execução é a cópia instalada fora do clone; avisa se a do repositório mudou e precisa ser reinstalada.
if [[ -f scripts/implantar.sh && -f "$0" ]] && ! cmp -s scripts/implantar.sh "$0"; then
  echo "AVISO: o implantar.sh instalado difere do repositório; reinstale como administrador" >&2
fi

# O compose monta este diretório em /etc/nginx/alvo; o mesmo caminho é o que o script escreve (variável obrigatória lá).
export PHATI_ALVO_DIR="$alvo_dir"
compor() { "$docker" compose --env-file "$dir/.env" -f "$dir/repo/servidor/compose.yaml" -f "$dir/repo/servidor/compose.implantacao.yaml" "$@"; }
mkdir -p "$alvo_dir"

passo=inicio
trap 'erro "falhou no passo: $passo"' ERR
registrar "inicio anterior=${anterior:0:12}"

# Estado: sem `ativa` é a primeira implantação, e a candidata é azul. Com `ativa`, a candidata é a outra pilha.
if [[ -f "$dir/ativa" ]]; then
  ativa="$(cat "$dir/ativa")"
  [[ "$ativa" == azul || "$ativa" == verde ]] || erro "$dir/ativa tem valor inválido"
fi
outra() { if [[ "$1" == azul ]]; then echo verde; else echo azul; fi; }
if [[ -n "$ativa" ]]; then cand="$(outra "$ativa")"; else cand=azul; fi
primeira=0
[[ -n "$ativa" ]] || primeira=1

# Grava $2 em $1 de forma atômica: temporário no mesmo diretório e `mv`, para ninguém ler a escrita pela metade.
gravar_atomico() {
  local tmp
  tmp="$(mktemp "$(dirname "$1")/.tmp.XXXXXX")"
  printf '%s\n' "$2" > "$tmp" || { rm -f "$tmp"; return 1; }
  chmod 644 "$tmp"
  mv -f "$tmp" "$1"
}
# Mesmo contrato de `servidor/nginx/alvo/alvo.conf`: `$alvo` é o app e `$pilha` o volume de estáticos.
conteudo_alvo() { printf 'set $alvo app_%s;\nset $pilha %s;' "$1" "$1"; }

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
saudavel_agora() {
  local id
  id="$(compor ps -q "$1" 2>/dev/null || true)"
  [[ -n "$id" && "$("$docker" inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || true)" == healthy ]]
}
# Comando completo de recuperação (usado quando a reversão também falha). Vazio = nenhuma pilha servia antes.
comando_recuperacao() {
  local grava="rm -f $alvo_conf"
  [[ -z "$1" ]] || grava="printf 'set \$alvo app_$1;\\nset \$pilha $1;\\n' > $alvo_conf"
  echo "$grava && COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME docker compose --env-file $dir/.env -f $dir/repo/servidor/compose.yaml -f $dir/repo/servidor/compose.implantacao.yaml exec -T nginx nginx -s reload"
}

# Devolve o alvo.conf anterior ($2, se $1 = 1) e recarrega se o nginx já tinha recarregado o destino novo ($3 = 1). Sai com erro.
reverter() {
  local tinha="$1" antigo="$2" recarregou="$3" motivo="$4" recuperar
  recuperar="$(comando_recuperacao "$ativa")"
  if [[ "$tinha" == 1 ]]; then
    gravar_atomico "$alvo_conf" "$antigo" || erro "$motivo; falha ao gravar o alvo.conf anterior; recupere com: $recuperar"
  else
    rm -f "$alvo_conf"
  fi
  if [[ "$recarregou" == 1 ]] && ! nginx_recarrega; then
    erro "$motivo; alvo.conf revertido, mas o nginx não recarregou; recupere com: $recuperar"
  fi
  if [[ -n "$ativa" ]]; then
    erro "$motivo; alvo.conf revertido para app_$ativa, que segue servindo"
  fi
  erro "$motivo; alvo.conf removido (nenhuma pilha servia antes)"
}

# Troca o destino do nginx para a cor $1: grava o alvo.conf, confere `nginx -t`, recarrega e verifica /saude pelo nginx.
trocar() {
  local novo="$1" tinha=0 antigo=""
  antes_da_troca=0
  if [[ -f "$alvo_conf" ]]; then tinha=1; antigo="$(cat "$alvo_conf")"; fi
  gravar_atomico "$alvo_conf" "$(conteudo_alvo "$novo")"
  if ! nginx_recarrega; then
    reverter "$tinha" "$antigo" 0 "nginx -t ou reload falhou"
  fi
  if ! verificar_nginx; then
    reverter "$tinha" "$antigo" 1 "/saude pelo nginx falhou depois do reload"
  fi
}

# Rollback: o SHA é o da pilha inativa e ela está saudável. Não há build nem migração; só o destino muda.
passo=rollback-rapido
if [[ -n "$ativa" && "$(cat "$dir/pilha-$cand.sha" 2>/dev/null || true)" == "$sha" ]] && saudavel_agora "app_$cand"; then
  origem="$ativa"
  destino="$cand"
  trocar "$cand"
  gravar_atomico "$dir/ativa" "$cand"
  migracao=pulada
  trap - ERR
  registrar "OK"
  echo "implantado=${sha:0:12} ativa=$cand anterior=$ativa"
  exit 0
fi

# Implantação normal: a candidata sobe ao lado da ativa, e o destino só muda depois de ela estar saudável.
passo=backup
tem_dados=0
if [[ -n "$(compor ps -q banco 2>/dev/null)" ]] || "$docker" volume inspect "${COMPOSE_PROJECT_NAME}_dados_banco" >/dev/null 2>&1; then
  tem_dados=1
fi
if [[ "$tem_dados" == 1 && "$opcao" != "--sem-migracao" ]]; then
  # Banco parado com volume é instalação existente: sobe o banco e tira o backup antes de migrar.
  compor up -d --wait banco
  # backup.sh fica ao lado deste script (na VM, em /opt/phati/bin, de dono root, como ele).
  backup_arquivo="$(PHATI_DIR="$dir" DOCKER="$docker" bash "$(dirname "$0")/backup.sh" "${anterior:0:12}")"
elif [[ "$tem_dados" == 0 ]]; then
  echo "sem banco nem volume: primeira implantação, sem backup"
fi

passo=build
# Só a candidata e os one-shots: a ativa segue de pé com a imagem que já tem.
compor build app_"$cand" migracao estaticos_"$cand" pacotes_dono camadas_dono banco_extensoes pgb_auth

passo=banco
compor up -d --wait banco
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
  # Backup verificado antes de qualquer migração com arquivo a verificar (R8): o caminho vem do backup.sh.
  exigir_backup() {
    [[ -n "$backup_arquivo" && -s "$backup_arquivo" ]] || erro "backup verificado ausente ou vazio: a migração não roda"
  }
  # R4 e R5: com `ativa`, a versão anterior segue de pé e a migração tem de ser compatível com ela. Sem `ativa` (primeira
  # implantação) ninguém serve a anterior: nada a verificar.
  if [[ -n "$ativa" ]]; then
    base="$(cat "$dir/pilha-$ativa.sha" 2>/dev/null || true)"
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
        compor stop app_"$ativa"
        ativa_parada=1
      fi
    fi
  fi
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
gravar_atomico "$dir/ativa" "$cand"
ativa_parada=0
passo=nginx-e-tunel
# A pilha anterior fica de pé (rollback instantâneo). O nginx já recarregou; o `up` só garante o cloudflared.
compor up -d --no-deps nginx cloudflared
# Primeira implantação sobre o layout da 006 (contêiner `app` órfão): só sai depois da troca bem-sucedida. Volumes não são
# tocados; o `phati_estaticos` antigo fica como pendência manual. Antes da troca o site segue pelo nginx e pelo app antigos;
# a troca recria o nginx (blip de ~1 s, não medido).
passo=orfao
if [[ "$primeira" == 1 ]]; then
  for id in $("$docker" ps -aq --filter label=com.docker.compose.project=$COMPOSE_PROJECT_NAME --filter label=com.docker.compose.service=app); do
    "$docker" rm -f "$id" >/dev/null
    registrar "removido-orfao=app"
  done
fi
trap - ERR
registrar "OK"
echo "implantado=${sha:0:12} ativa=$cand anterior=${ativa:-nenhuma}"
