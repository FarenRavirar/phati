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
# O tamanho é medido em bytes antes da substituição de comando, que tira as quebras finais (65 bytes já é inválido).
ativa=nenhuma
if [[ -e "$dir/ativa" ]]; then
  tamanho="$( (head -c 65 "$dir/ativa" 2>/dev/null || true) | wc -c | tr -d ' ')"
  bruta="$(head -c 64 "$dir/ativa" 2>/dev/null || true)"
  case "$bruta" in
    azul | verde) ativa="$bruta" ;;
    *) ativa=invalida ;;
  esac
  [[ "$tamanho" -le 64 ]] || ativa=invalida
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

# Destino lido do alvo.conf: só `set $alvo app_azul;` ou `app_verde;` em linha não comentada; outro conteúdo ou arquivo ausente é nenhum.
# Medido no nginx 1.30: com `set $alvo` repetido no mesmo bloco, o último vence; por isso fica a última diretiva efetiva.
destino=nenhum
if [[ -e "$alvo_conf" ]]; then
  conteudo="$(head -c 4096 "$alvo_conf" 2>/dev/null || true)"
  re='^[[:space:]]*set \$alvo (app_[a-z]+);'
  while IFS= read -r linha; do
    if [[ "$linha" =~ $re ]]; then
      case "${BASH_REMATCH[1]}" in
        app_azul | app_verde) destino="${BASH_REMATCH[1]}" ;;
        *) destino=nenhum ;;  # app_* fora da lista: nenhum, como diz o cabeçalho
      esac
    fi
  done <<< "$conteudo"
fi

echo "ativa=$ativa"
echo "candidata=$candidata"
echo "sha-azul=$sha_azul"
echo "sha-verde=$sha_verde"
echo "ultimo=$ultimo"
echo "destino-nginx=$destino"

# Ativa e o destino lido do alvo.conf batem? Se não, avisa. `destino-nginx` é a configuração do arquivo, não o roteamento
# efetivo do nginx (que só se sabe com o reload feito e `/saude` respondendo).
if [[ "$ativa" == azul || "$ativa" == verde ]] && [[ "$destino" == app_azul || "$destino" == app_verde ]] && [[ "app_$ativa" != "$destino" ]]; then
  echo "AVISO: ativa=$ativa mas o alvo.conf configura ${destino#app_} (configuração lida do arquivo, não o roteamento efetivo do nginx)"
fi
