#!/usr/bin/env node
'use strict';
// Barreira de pré-commit do par arquivo–teste (AGENTS.md §Testes).
//
// Arquivo de código em stage precisa de teste irmão, já existente ou no mesmo commit:
// - Python em `servidor/`: `servidor/<app>/<modulo>.py` ↔ `servidor/<app>/testes/test_<modulo>.py`
//   (módulo aninhado usa o nome do arquivo: o par fica em `servidor/<app>/testes/`);
// - JS/TS: `<nome>.test.<ext>` ao lado.
// Isentos: só a lista fixa do AGENTS.md (`__init__.py`, `migrations/`, `manage.py`, `apps.py`,
// `wsgi.py`, `asgi.py`) e os próprios testes. `conftest.py` exige par (achado do Codex no PR #1).
// Arquivo na raiz de `servidor/` tem o par em `servidor/projeto/testes/`.
// O inverso também vale: apagar ou renomear um teste que ainda é o par de um módulo rastreado bloqueia
// (achado do Codex no PR #1: a exclusão isolada passava).
// O par existir não prova o teste: cobertura e mutação manual continuam valendo.
// Falha ao ler o git bloqueia o commit (falha fechada).

const { execFileSync } = require('node:child_process');

const ISENTOS_PY = new Set(['__init__.py', 'manage.py', 'apps.py', 'wsgi.py', 'asgi.py']);
const EXTENSOES_JS = /\.(js|jsx|ts|tsx|mjs|cjs)$/;

// Devolve o caminho do par esperado, ou null quando o arquivo não exige par.
function parEsperado(caminho) {
  const c = caminho.replace(/\\/g, '/');
  const partes = c.split('/');
  const nome = partes[partes.length - 1];
  if (/^servidor\/[^/]+\/.+\.py$/.test(c)) {
    if (ISENTOS_PY.has(nome) || partes.includes('migrations') || partes.includes('testes')) return null;
    return `servidor/${partes[1]}/testes/test_${nome}`;
  }
  // Arquivo na raiz de `servidor/` (ex.: conftest.py) não tem app: o par fica no pacote do projeto.
  if (/^servidor\/[^/]+\.py$/.test(c)) {
    return ISENTOS_PY.has(nome) ? null : `servidor/projeto/testes/test_${nome}`;
  }
  if (EXTENSOES_JS.test(nome) && !/\.test\.[^.]+$/.test(nome) && !nome.endsWith('.d.ts')) {
    return c.replace(EXTENSOES_JS, (ext) => `.test${ext}`);
  }
  return null;
}

// Núcleo puro. `rastreados` é o índice do git depois do commit (nunca o disco: arquivo untracked e
// fora do stage não vai para o commit); `caminhos` são os adicionados/alterados e `removidos` os apagados
// (renomeação conta o nome antigo como removido).
function verificar({ caminhos, removidos = [], rastreados }) {
  const indice = new Set(rastreados.map((c) => c.replace(/\\/g, '/')));
  const achados = [];
  for (const caminho of caminhos) {
    const par = parEsperado(caminho);
    if (par && !indice.has(par)) achados.push({ arquivo: caminho, par });
  }
  const apagados = new Set(removidos.map((c) => c.replace(/\\/g, '/')));
  for (const modulo of indice) {
    const par = parEsperado(modulo);
    if (par && apagados.has(par) && !indice.has(par)) achados.push({ arquivo: modulo, par });
  }
  return achados;
}

function git(args, opcoes = {}) {
  return execFileSync('git', args, { maxBuffer: 256 * 1024 * 1024, ...opcoes });
}

function listar(raiz, args) {
  return git(args, { cwd: raiz, encoding: 'utf8' }).split('\0').filter(Boolean);
}

function principal() {
  const raiz = git(['rev-parse', '--show-toplevel'], { encoding: 'utf8' }).trim();
  const caminhos = listar(raiz, ['diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z']);
  const removidos = listar(raiz, ['diff', '--cached', '--name-only', '--diff-filter=D', '--no-renames', '-z']);
  const rastreados = listar(raiz, ['ls-files', '-z']);
  const achados = verificar({ caminhos, removidos, rastreados });
  if (achados.length === 0) return 0;
  process.stderr.write('COMMIT BLOQUEADO: arquivo de código sem teste irmão (AGENTS.md §Testes).\n');
  for (const a of achados) process.stderr.write(`  ${a.arquivo} — falta ${a.par}\n`);
  return 1;
}

if (require.main === module) {
  try {
    process.exit(principal());
  } catch (erro) {
    process.stderr.write(`COMMIT BLOQUEADO: a verificação falhou (${erro.message}).\n`);
    process.exit(1);
  }
}

module.exports = { verificar, parEsperado };
