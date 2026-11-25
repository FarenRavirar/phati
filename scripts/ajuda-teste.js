'use strict';
// Ajudas compartilhadas pelos testes de `scripts/` (trocar-banco.test.js e implantacao.test.js).
// Não é suíte: o nome não casa com `*.test.js`, então o `node --test scripts/*.test.js` do CI não o coleta.
// Par: scripts/ajuda-teste.test.js.
const fs = require('node:fs');

// Caminho no formato que o Bash da VM de teste aceita (barra invertida do Windows vira barra).
const unix = (caminho) => caminho.replace(/\\/g, '/');

// Linhas não vazias de um registro; arquivo ausente = lista vazia (nada foi anotado ainda).
const lerLinhas = (arquivo) => (fs.existsSync(arquivo) ? fs.readFileSync(arquivo, 'utf8').split('\n').filter(Boolean) : []);

// `flock` de mentira com a mesma linha de comando do de verdade (`-w T -E N arquivo comando...`).
// "Ocupado" é o arquivo `<trava>.ocupado`: espera `T` segundos e sai com `N` (padrão 1). Sem ocupado, roda o comando.
// `registro: true` anota cada chamada em `$FLOCK_CHAMADAS` (só o implantacao.test.js lê esse registro).
function escreverFlock(destino, { registro = false } = {}) {
  const linhas = ['#!/usr/bin/env bash'];
  if (registro) linhas.push('echo "$*" >> "$FLOCK_CHAMADAS"');
  linhas.push(
    't=0; e=1',
    'while [[ "${1:-}" == -* ]]; do case "$1" in -w) t="$2"; shift 2 ;; -E) e="$2"; shift 2 ;; *) shift ;; esac; done',
    'arquivo="$1"; shift',
    'if [[ -e "$arquivo.ocupado" ]]; then sleep "$t"; exit "$e"; fi',
    'exec "$@"',
    '',
  );
  fs.writeFileSync(destino, linhas.join('\n'), { mode: 0o755 });
  return destino;
}

module.exports = { unix, lerLinhas, escreverFlock };
