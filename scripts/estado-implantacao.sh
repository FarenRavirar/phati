#!/usr/bin/env bash
# Estado da implantação azul/verde (spec 009, R16): lê o que o implantar.sh grava e imprime uma informação por linha.
# Só leitura: não escreve, não fala com o Docker e não lê `.env`. Tudo que vem do disco é validado antes de sair na tela.
# Uso: PHATI_DIR=/opt/phati estado-implantacao.sh   (PHATI_ALVO_DIR padrão: $PHATI_DIR/alvo)
# Saída: 0 quando leu; 2 só se PHATI_DIR não existe.
set -Eeuo pipefail
export LC_ALL=C

dir="${PHATI_DIR:-/opt/phati}"
alvo_conf="${PHATI_ALVO_DIR:-$dir/alvo}/alvo.conf"
[[ -d "$dir" ]] || { echo "ERRO: PHATI_DIR inexistente: $dir" >&2; exit 2; }

# Ativa: só azul ou verde; ausente é nenhuma (primeira implantação); qualquer outro valor vira invalida, sem ser ecoado.
ativa=nenhuma
if [[ -e "$dir/ativa" ]]; then
  bruta="$(head -c 64 "$dir/ativa" 2>/dev/null || true)"
  case "$bruta" in
    azul | verde) ativa="$bruta" ;;
    *) ativa=invalida ;;
  esac
fi
case "$ativa" in
  azul) candidata=verde ;;
  verde | nenhuma) candidata=azul ;;
  *) candidata=invalida ;;
esac

# SHA que a pilha serve: 40 hexadecimais viram 12 caracteres; qualquer outra coisa é nenhum.
sha_de() {
  local s
  s="$(head -n 1 "$dir/pilha-$1.sha" 2>/dev/null || true)"
  if [[ "$s" =~ ^[0-9a-f]{40}$ ]]; then echo "${s:0:12}"; else echo nenhum; fi
}
sha_azul="$(sha_de azul)"
sha_verde="$(sha_de verde)"

# Último registro: uma linha, sem controle e limitada a 300 bytes (LC_ALL=C); vazio ou ausente é nenhum.
ultimo=nenhum
if [[ -e "$dir/implantacoes.log" ]]; then
  linha="$(tail -n 1 "$dir/implantacoes.log" 2>/dev/null | head -c 300 | tr -d '[:cntrl:]' || true)"
  [[ -z "$linha" ]] || ultimo="$linha"
fi

# Destino do nginx: só `set $alvo app_azul;` ou `app_verde;`; outro conteúdo ou arquivo ausente é nenhum.
destino=nenhum
if [[ -e "$alvo_conf" ]]; then
  conteudo="$(head -c 4096 "$alvo_conf" 2>/dev/null || true)"
  re='set \$alvo (app_[a-z]+);'
  if [[ "$conteudo" =~ $re ]]; then
    case "${BASH_REMATCH[1]}" in
      app_azul | app_verde) destino="${BASH_REMATCH[1]}" ;;
    esac
  fi
fi

echo "ativa=$ativa"
echo "candidata=$candidata"
echo "sha-azul=$sha_azul"
echo "sha-verde=$sha_verde"
echo "ultimo=$ultimo"
echo "destino-nginx=$destino"

# Ativa e destino do nginx batem? Se não, avisa: o tráfego não segue o estado registrado.
if [[ "$ativa" == azul || "$ativa" == verde ]] && [[ "$destino" == app_azul || "$destino" == app_verde ]]; then
  if [[ "app_$ativa" != "$destino" ]]; then
    echo "AVISO: ativa=$ativa mas o nginx aponta ${destino#app_}"
  fi
fi
