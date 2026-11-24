#!/usr/bin/env node
// Suite do implantacao-gate.
//
// Metade negativa é a maior: um gate que bloqueia leitura, lint ou `gh workflow run` é desligado na
// primeira vez que atrapalha. Os casos liberados existem para isso. Os casos de desembrulho (rtk, sudo,
// bash -c, ssh) existem porque são a forma real de escapar de uma regra que só olha o texto do comando.

'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const path = require('node:path');

const HOOK = path.join(__dirname, 'implantacao-gate.js');

// Roda o hook como o Claude Code faz: payload JSON no stdin.
// Devolve { decisao, regra, motivo } ou null (passou). Falha se o hook sair com código diferente de 0.
function rodar(comando, raw) {
  const entrada = raw ?? JSON.stringify({
    hook_event_name: 'PreToolUse',
    tool_name: 'Bash',
    cwd: __dirname,
    tool_input: { command: comando },
  });
  const r = spawnSync('node', [HOOK], { input: entrada, encoding: 'utf8' });
  assert.equal(r.status, 0, `hook saiu com ${r.status}: ${r.stderr}`);
  if (!r.stdout.trim()) return null;
  const saida = JSON.parse(r.stdout).hookSpecificOutput;
  return {
    decisao: saida.permissionDecision,
    regra: saida.permissionDecisionReason.match(/\[implantacao-gate\/([^\]]+)\]/)?.[1] ?? null,
    motivo: saida.permissionDecisionReason,
  };
}

function assertNegado(resultado, comando) {
  assert.ok(resultado, `esperava deny para: ${comando}, hook passou`);
  assert.equal(resultado.decisao, 'deny', comando);
  assert.equal(resultado.regra, 'implantar-direto', comando);
  assert.match(resultado.motivo, /gh workflow run implantar -f sha=<SHA>/, comando);
}

function assertPergunta(resultado, comando) {
  assert.ok(resultado, `esperava ask para: ${comando}, hook passou`);
  assert.equal(resultado.decisao, 'ask', comando);
  assert.equal(resultado.regra, 'trocar-banco', comando);
}

// --- NEGA: execução direta de implantar.sh, restaurar.sh e backup.sh ---

const NEGADOS = [
  'sudo -n /opt/phati/bin/implantar.sh sha',
  'bash scripts/implantar.sh x',
  'rtk bash -lc "sudo scripts/restaurar.sh"',
  'scripts/implantar.sh abc',
  './scripts/implantar.sh abc',
  '/opt/phati/bin/implantar.sh reverter',
  'rtk sudo /opt/phati/bin/backup.sh cron',
  'sh -c "scripts/implantar.sh x"',
  'sudo -u root /opt/phati/bin/implantar.sh sha',
  'cd /x && sudo -n scripts/implantar.sh sha',
  'echo ok; ./scripts/implantar.sh x',
  'echo "$(bash scripts/backup.sh)"',
  'bash -lc "cd /x && bash scripts/implantar.sh sha"',
  'ssh maruko "sudo /opt/phati/bin/restaurar.sh arq RESTAURAR"',
  'rtk bypass bash scripts/implantar.sh sha',
  'bash scripts/trocar-banco.sh x && bash scripts/implantar.sh y',
];

for (const comando of NEGADOS) {
  test(`nega execução direta: ${comando}`, () => {
    assertNegado(rodar(comando), comando);
  });
}

// --- PERGUNTA: trocar-banco.sh não tem workflow ---

const PERGUNTAS = [
  'sudo -n /opt/phati/bin/trocar-banco.sh trocar',
  'bash scripts/trocar-banco.sh x',
  'ssh maruko "sudo /opt/phati/bin/trocar-banco.sh trocar"',
];

for (const comando of PERGUNTAS) {
  test(`pergunta antes do trocar-banco: ${comando}`, () => {
    assertPergunta(rodar(comando), comando);
  });
}

// --- LIBERA: leitura, sintaxe, lint, teste e o próprio workflow ---

const LIBERADOS = [
  'rtk rg implantar.sh scripts',
  'bash -n scripts/implantar.sh',
  'bash -n /opt/phati/bin/implantar.sh',
  'gh workflow run implantar -f sha=abc',
  'node --test scripts/implantar.test.js',
  'cat scripts/implantar.sh',
  'shellcheck scripts/implantar.sh',
  'rtk head -20 scripts/restaurar.sh',
  'rtk grep -n "reverter" scripts/implantar.sh',
  'rtk rg "sudo scripts/implantar.sh" scripts',
  'echo "bash scripts/implantar.sh"',
  'ssh maruko cat /opt/phati/bin/implantar.sh',
  'ssh maruko docker ps',
  'rtk git status',
];

for (const comando of LIBERADOS) {
  test(`libera sem execução: ${comando}`, () => {
    assert.equal(rodar(comando), null, comando);
  });
}

// --- CAMINHO INFELIZ: payload ruim não bloqueia trabalho ---

test('payload que não é JSON passa sem saída', () => {
  assert.equal(rodar(null, 'não é json'), null);
});

test('comando vazio passa sem saída', () => {
  assert.equal(rodar(''), null);
});

test('payload sem tool_input passa sem saída', () => {
  assert.equal(rodar(null, JSON.stringify({ tool_name: 'Bash' })), null);
});

test('comando que não é texto passa sem saída', () => {
  assert.equal(rodar(null, JSON.stringify({ tool_input: { command: 5 } })), null);
});
