// Suíte do delegar-executor-gate. Rodar: `node --test .claude/hooks/delegar-executor-gate.test.js`.
//
// Um gate sem teste ou nega demais (e é desligado na primeira vez que atrapalha) ou
// não nega nada. Por isso a suíte cobre os dois lados, a entrada malformada e o
// caminho ponta a ponta pelo stdin, que é o que o Claude Code de fato executa.

'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { decidir } = require('./delegar-executor-gate.js');

const HOOK = path.join(__dirname, 'delegar-executor-gate.js');
// Raiz sintética do projeto: a regra é relativa a ela, não ao disco real.
const RAIZ = path.resolve('/projeto');
const sessaoPrincipal = (tool_name, file_path) => ({ tool_name, tool_input: { file_path }, cwd: RAIZ });
const dentroDeSubagente = (tool_name, file_path) => ({ ...sessaoPrincipal(tool_name, file_path), agent_id: 'agent-abc123' });
const arq = (...partes) => path.join(RAIZ, ...partes);

test('sessão principal + código em servidor/ é negada e manda ao executor', () => {
  const motivo = decidir(sessaoPrincipal('Edit', arq('servidor', 'comum', 'x.py')), RAIZ);
  assert.ok(motivo, 'deveria negar');
  assert.match(motivo, /executor/);
  assert.match(motivo, /subagent_type=executor/);
});

test('sessão principal + Write em navegador/ e scripts/ é negada', () => {
  assert.ok(decidir(sessaoPrincipal('Write', arq('navegador', 'app.ts')), RAIZ));
  assert.ok(decidir(sessaoPrincipal('Edit', arq('scripts', 'build.sh')), RAIZ));
});

test('sessão principal + arquivo de teste fora de servidor/ é negada', () => {
  assert.ok(decidir(sessaoPrincipal('Edit', arq('testes', 'test_x.py')), RAIZ));
});

test('subagente (agent_id presente) + .py passa', () => {
  assert.equal(decidir(dentroDeSubagente('Edit', arq('servidor', 'comum', 'x.py')), RAIZ), null);
});

test('documento .md passa mesmo em pasta de código', () => {
  assert.equal(decidir(sessaoPrincipal('Edit', arq('servidor', 'README.md')), RAIZ), null);
});

test('pastas de texto e config passam (specs, .specify, sessoes, docs, .claude)', () => {
  assert.equal(decidir(sessaoPrincipal('Write', arq('specs', '005', 'tasks.md')), RAIZ), null);
  assert.equal(decidir(sessaoPrincipal('Edit', arq('.specify', 'memory', 'x.md')), RAIZ), null);
  assert.equal(decidir(sessaoPrincipal('Edit', arq('sessoes', 'a.json')), RAIZ), null);
  assert.equal(decidir(sessaoPrincipal('Edit', arq('docs', 'a.yaml')), RAIZ), null);
  assert.equal(decidir(sessaoPrincipal('Edit', arq('.claude', 'hooks', 'x.js')), RAIZ), null);
});

test('caminho fora do projeto passa (ex.: ~/.claude)', () => {
  const fora = path.resolve('/outra', 'pasta', 'x.js');
  assert.equal(decidir({ tool_name: 'Edit', tool_input: { file_path: fora }, cwd: RAIZ }, RAIZ), null);
});

test('extensão fora da lista de código passa (ex.: .txt em servidor/)', () => {
  assert.equal(decidir(sessaoPrincipal('Edit', arq('servidor', 'notas.txt')), RAIZ), null);
});

test('ferramenta fora de Edit/Write/NotebookEdit passa', () => {
  assert.equal(decidir({ tool_name: 'Read', tool_input: { file_path: arq('servidor', 'x.py') }, cwd: RAIZ }, RAIZ), null);
});

test('entrada malformada não derruba: sem tool_input, sem caminho, nula, texto', () => {
  assert.equal(decidir(null, RAIZ), null);
  assert.equal(decidir('texto', RAIZ), null);
  assert.equal(decidir({ tool_name: 'Edit' }, RAIZ), null);
  assert.equal(decidir({ tool_name: 'Edit', tool_input: 'x' }, RAIZ), null);
  assert.equal(decidir({ tool_name: 'Edit', tool_input: { file_path: 42 } }, RAIZ), null);
  assert.equal(decidir({ tool_name: 'Edit', tool_input: { file_path: '' } }, RAIZ), null);
});

test('NotebookEdit usa notebook_path; .ipynb não é código da lista e passa', () => {
  const entrada = { tool_name: 'NotebookEdit', tool_input: { notebook_path: arq('servidor', 'a.ipynb') }, cwd: RAIZ };
  assert.equal(decidir(entrada, RAIZ), null);
});

// Ponta a ponta: stdin real, env real. Cobre o que o Claude Code de fato executa.
const rodar = (stdin) => spawnSync(process.execPath, [HOOK], {
  input: stdin,
  env: { ...process.env, CLAUDE_PROJECT_DIR: RAIZ },
  encoding: 'utf8',
  timeout: 5000,
});

test('ponta a ponta: sessão principal + .py emite deny em JSON e sai 0', () => {
  const r = rodar(JSON.stringify(sessaoPrincipal('Edit', arq('servidor', 'x.py'))));
  assert.equal(r.status, 0);
  const saida = JSON.parse(r.stdout);
  assert.equal(saida.hookSpecificOutput.permissionDecision, 'deny');
  assert.match(saida.hookSpecificOutput.permissionDecisionReason, /executor/);
});

test('ponta a ponta: subagente + .py não emite nada e sai 0', () => {
  const r = rodar(JSON.stringify(dentroDeSubagente('Write', arq('servidor', 'x.py'))));
  assert.equal(r.status, 0);
  assert.equal(r.stdout, '');
});

test('ponta a ponta: JSON inválido sai 0 sem saída', () => {
  const r = rodar('{não é json');
  assert.equal(r.status, 0);
  assert.equal(r.stdout, '');
});

test('ponta a ponta: stdin vazio sai 0 sem saída', () => {
  const r = rodar('');
  assert.equal(r.status, 0);
  assert.equal(r.stdout, '');
});
