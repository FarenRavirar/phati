#!/usr/bin/env bash
# Smoke externo, sem credencial, depois da implantação (spec 006 R13).
# Uso: smoke-implantacao.sh <url-base>   (ex.: https://host)
# Confere: sonda de saúde, tela de entrada com CSP, painel e API sem sessão negando e, em https, o HSTS.
set -euo pipefail

base="${1:-}"
[[ "$base" =~ ^https?://[^/]+$ ]] || { echo "ERRO: informe a URL base sem caminho (http://… ou https://…)" >&2; exit 1; }

falhas=0
confere() { # descrição, código de saída da condição (0 = ok)
  if [[ "$2" == 0 ]]; then
    echo "ok    $1"
  else
    echo "FALHA $1" >&2
    falhas=$((falhas + 1))
  fi
}
status() { curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$@"; }
cabecalhos() { curl -s -D - -o /dev/null --max-time 10 "$@"; }

corpo="$(curl -s --max-time 10 "$base/saude" || true)"
[[ "$corpo" == *'"estado": "ok"'* ]] && ok=0 || ok=1
confere "/saude devolve estado ok" "$ok"
[[ "$(status "$base/entrar")" == 200 ]] && ok=0 || ok=1
confere "/entrar responde 200" "$ok"
cabecalhos "$base/entrar" | grep -qi '^content-security-policy:' && ok=0 || ok=1
confere "/entrar leva Content-Security-Policy" "$ok"
[[ "$(status "$base/painel/")" =~ ^(301|302|403)$ ]] && ok=0 || ok=1
confere "/painel/ sem sessão não abre" "$ok"
[[ "$(status "$base/api/v1/pessoas")" =~ ^(401|403|404)$ ]] && ok=0 || ok=1
confere "API sem sessão nega" "$ok"
if [[ "$base" == https://* ]]; then
  cabecalhos "$base/entrar" | grep -qi '^strict-transport-security:' && ok=0 || ok=1
  confere "HSTS presente" "$ok"
fi

[[ "$falhas" == 0 ]] || { echo "smoke falhou: $falhas verificação(ões)" >&2; exit 1; }
echo "smoke_ok"
