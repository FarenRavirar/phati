#!/usr/bin/env bash
# Smoke externo, sem credencial, depois da implantação (spec 006 R13).
# Uso: smoke-implantacao.sh <url-base>   (ex.: https://host)
# Confere: sonda de saúde, tela de entrada com CSP, painel e API sem sessão negando e, em https, o HSTS.
set -euo pipefail

base="${1:-}"
# HTTP puro só para o próprio computador (o teste sobe um servidor local); a implantação real é sempre https.
[[ "$base" =~ ^(https://[^/]+|http://(127\.0\.0\.1|localhost)(:[0-9]+)?)$ ]] || { echo "ERRO: informe a URL base sem caminho: https://… (http:// só em 127.0.0.1 ou localhost)" >&2; exit 1; }

# Base local (http) numa implantação: o Host é o primeiro de PHATI_HOSTS_PERMITIDOS, o mesmo de implantar.sh e do healthcheck;
# sem ele, o Django recusa o Host do loopback com 400 (spec 011 R8). Nome fora de host é recusado antes de qualquer curl.
host_args=()
if [[ "$base" == http://* && -n "${PHATI_HOSTS_PERMITIDOS:-}" ]]; then
  host_permitido="${PHATI_HOSTS_PERMITIDOS%%,*}"
  [[ "$host_permitido" =~ ^[A-Za-z0-9.-]+$ ]] || { echo "ERRO: primeiro host de PHATI_HOSTS_PERMITIDOS inválido" >&2; exit 1; }
  host_args=(-H "Host: $host_permitido")
fi

falhas=0
confere() { # descrição, código de saída da condição (0 = ok)
  local descricao="$1" codigo="$2"
  if [[ "$codigo" == 0 ]]; then
    echo "ok    $descricao"
  else
    echo "FALHA $descricao" >&2
    falhas=$((falhas + 1))
  fi
}
status() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "${host_args[@]}" "$@"; }
cabecalhos() { curl -s -D - -o /dev/null --max-time 10 "${host_args[@]}" "$@"; }

corpo="$(curl -s --max-time 10 "${host_args[@]}" "$base/saude" || true)"
[[ "$corpo" == *'"estado": "ok"'* ]] && ok=0 || ok=1
confere "/saude devolve estado ok" "$ok"
[[ "$(status "$base/entrar")" == 200 ]] && ok=0 || ok=1
confere "/entrar responde 200" "$ok"
# Cabeçalhos capturados antes de procurar: `grep -q` num pipe fecharia o curl no meio e, com `pipefail`, reprovaria um
# smoke válido; e a falha do curl depois de emitir cabeçalhos não pode valer como "achei" (CodeRabbit, PR #46).
cab_ok=1
cab="$(cabecalhos "$base/entrar")" && cab_ok=0
[[ "$cab_ok" == 0 ]] && grep -qi '^content-security-policy:' <<<"$cab" && ok=0 || ok=1
confere "/entrar leva Content-Security-Policy" "$ok"
[[ "$(status "$base/painel/")" =~ ^(301|302|403)$ ]] && ok=0 || ok=1
confere "/painel/ sem sessão não abre" "$ok"
[[ "$(status "$base/api/v1/pessoas")" =~ ^(401|403)$ ]] && ok=0 || ok=1  # 404 seria rota ausente, não negação
confere "API sem sessão nega" "$ok"
if [[ "$base" == https://* ]]; then
  [[ "$cab_ok" == 0 ]] && grep -qi '^strict-transport-security:' <<<"$cab" && ok=0 || ok=1
  confere "HSTS presente" "$ok"
fi

[[ "$falhas" == 0 ]] || { echo "smoke falhou: $falhas verificação(ões)" >&2; exit 1; }
echo "smoke_ok"
