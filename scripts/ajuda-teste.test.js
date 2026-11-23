'use strict';
// Testes das ajudas compartilhadas (scripts/ajuda-teste.js). Roda com: node --test scripts/ajuda-teste.test.js
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { unix, lerLinhas, escreverFlock } = require('./ajuda-teste');

// Pasta temporária própria de cada teste; some ao fim dele.
function pasta(t) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'ajuda-teste-'));
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
  return dir;
}

// Roda o `flock` de mentira com a linha de comando do script real (`flock -w T -E N arquivo comando...`).
function flock(dir, args, env = {}) {
  return spawnSync('bash', [unix(path.join(dir, 'flock')), ...args], {
    encoding: 'utf8',
    env: { ...process.env, ...env },
  });
}

test('unix: troca barra invertida por barra e deixa caminho POSIX igual', () => {
  assert.equal(unix('C:\\trabalho\\vm'), 'C:/trabalho/vm');
  assert.equal(unix('/tmp/vm'), '/tmp/vm');
});

test('unix: texto vazio continua vazio (entrada de borda)', () => {
  assert.equal(unix(''), '');
});

test('lerLinhas: arquivo com linhas devolve as não vazias, na ordem', (t) => {
  const arquivo = path.join(pasta(t), 'registro.log');
  fs.writeFileSync(arquivo, 'um\n\ndois\n');
  assert.deepEqual(lerLinhas(arquivo), ['um', 'dois']);
});

test('lerLinhas: arquivo ausente ou vazio devolve lista vazia, sem lançar erro', (t) => {
  const dir = pasta(t);
  assert.deepEqual(lerLinhas(path.join(dir, 'nao-existe.log')), []);
  fs.writeFileSync(path.join(dir, 'vazio.log'), '');
  assert.deepEqual(lerLinhas(path.join(dir, 'vazio.log')), []);
});

test('escreverFlock: cria o arquivo executável e sem registro não menciona FLOCK_CHAMADAS', (t) => {
  const destino = path.join(pasta(t), 'flock');
  escreverFlock(destino);
  assert.notEqual(fs.statSync(destino).mode & 0o111, 0, 'arquivo sem bit de execução');
  assert.ok(!fs.readFileSync(destino, 'utf8').includes('FLOCK_CHAMADAS'));
});

test('escreverFlock com registro: anota os argumentos em FLOCK_CHAMADAS antes de decidir', (t) => {
  const dir = pasta(t);
  escreverFlock(path.join(dir, 'flock'), { registro: true });
  const registro = path.join(dir, 'chamadas.log');
  const r = flock(dir, ['-w', '0', 'trava', 'echo', 'oi'], { FLOCK_CHAMADAS: registro });
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(lerLinhas(registro), ['-w 0 trava echo oi']);
});

test('flock de mentira: sem `.ocupado` roda o comando e devolve a saída', (t) => {
  const dir = pasta(t);
  escreverFlock(path.join(dir, 'flock'));
  const r = flock(dir, ['-w', '0', '-E', '75', path.join(dir, 'trava'), 'echo', 'oi']);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stdout, 'oi\n');
});

test('flock de mentira: trava `.ocupado` sai com o código do `-E` (75) e não roda o comando', (t) => {
  const dir = pasta(t);
  escreverFlock(path.join(dir, 'flock'));
  const trava = path.join(dir, 'trava');
  fs.writeFileSync(`${trava}.ocupado`, '');
  const r = flock(dir, ['-w', '0', '-E', '75', trava, 'touch', path.join(dir, 'rodou')]);
  assert.equal(r.status, 75);
  assert.ok(!fs.existsSync(path.join(dir, 'rodou')), 'o comando rodou com a trava ocupada');
});

test('flock de mentira: sem `-E` a trava ocupada sai com 1 (padrão)', (t) => {
  const dir = pasta(t);
  escreverFlock(path.join(dir, 'flock'));
  const trava = path.join(dir, 'trava');
  fs.writeFileSync(`${trava}.ocupado`, '');
  const r = flock(dir, ['-w', '0', trava, 'echo', 'oi']);
  assert.equal(r.status, 1);
});

test('flock de mentira: o código de saída do comando atravessa o dublê', (t) => {
  const dir = pasta(t);
  escreverFlock(path.join(dir, 'flock'));
  const r = flock(dir, ['-w', '0', path.join(dir, 'trava'), 'sh', '-c', 'exit 3']);
  assert.equal(r.status, 3);
});

test('flock de mentira: comando inexistente falha com 127 (entrada inválida)', (t) => {
  const dir = pasta(t);
  escreverFlock(path.join(dir, 'flock'));
  const r = flock(dir, ['-w', '0', path.join(dir, 'trava'), 'comando-que-nao-existe-9f3a']);
  assert.equal(r.status, 127);
});
