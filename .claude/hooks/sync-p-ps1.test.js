#!/usr/bin/env node
// Suíte do sync-p.ps1 (espelhamento atômico). Roda com: node --test .claude/hooks/sync-p-ps1.test.js
//
// Roda o script de verdade (PowerShell + robocopy) contra pastas temporárias, com -Destino apontando para o temporário.
// P:\phati não é tocado. Só roda no Windows, que é onde o hook de sincronização roda (sync-p.js, plataforma win32).

const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const SCRIPT_ORIGEM = path.join(__dirname, '..', 'sync-p.ps1');

// Cada teste monta um local (origem) e um destino próprios num temporário.
function montar() {
  const raiz = fs.mkdtempSync(path.join(os.tmpdir(), 'sync-p-ps1-'));
  const origem = path.join(raiz, 'projeto');
  const destino = path.join(raiz, 'P-phati');
  fs.mkdirSync(path.join(origem, '.claude'), { recursive: true });
  fs.copyFileSync(SCRIPT_ORIGEM, path.join(origem, '.claude', 'sync-p.ps1'));
  fs.mkdirSync(path.join(origem, 'specs'));
  fs.writeFileSync(path.join(origem, 'specs', 'novo.md'), 'novo');
  fs.writeFileSync(path.join(origem, 'DEFINICAO.md'), 'novo');
  fs.mkdirSync(path.join(destino, 'specs'), { recursive: true });
  fs.writeFileSync(path.join(destino, 'specs', 'novo.md'), 'antigo');
  fs.writeFileSync(path.join(destino, 'specs', 'so-no-destino.md'), 'antigo');
  fs.writeFileSync(path.join(destino, 'DEFINICAO.md'), 'antigo');
  return { raiz, origem, destino, script: path.join(origem, '.claude', 'sync-p.ps1') };
}

function rodar(script, destino, extra = []) {
  return spawnSync(
    'powershell.exe',
    ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script, '-Destino', destino, ...extra],
    { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true },
  );
}

const sobrasTemporarias = (raiz) => fs.readdirSync(raiz).filter((nome) => nome.includes('.tmp-'));

test('caminho feliz: espelha o local no destino e não deixa temporária', () => {
  const m = montar();
  try {
    const r = rodar(m.script, m.destino);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(fs.readFileSync(path.join(m.destino, 'specs', 'novo.md'), 'utf8'), 'novo');
    assert.equal(fs.readFileSync(path.join(m.destino, 'DEFINICAO.md'), 'utf8'), 'novo');
    assert.equal(fs.existsSync(path.join(m.destino, 'specs', 'so-no-destino.md')), false, 'espelho remove o que não existe no local');
    assert.deepEqual(sobrasTemporarias(m.raiz), []);
  } finally {
    fs.rmSync(m.raiz, { recursive: true, force: true });
  }
});

test('falha na cópia: destino fica como estava, temporária é apagada, código de saída reflete a falha', () => {
  const m = montar();
  try {
    // `docs` como arquivo, não pasta: robocopy não consegue copiar a origem e a fase 1 falha.
    fs.writeFileSync(path.join(m.origem, 'docs'), 'não é pasta');
    const r = rodar(m.script, m.destino);
    assert.notEqual(r.status, 0);
    assert.equal(fs.readFileSync(path.join(m.destino, 'specs', 'novo.md'), 'utf8'), 'antigo');
    assert.equal(fs.existsSync(path.join(m.destino, 'specs', 'so-no-destino.md')), true);
    assert.equal(fs.readFileSync(path.join(m.destino, 'DEFINICAO.md'), 'utf8'), 'antigo');
    assert.deepEqual(sobrasTemporarias(m.raiz), []);
  } finally {
    fs.rmSync(m.raiz, { recursive: true, force: true });
  }
});

test('destino ausente falha fechado com código 1 e não cria nada', () => {
  const m = montar();
  try {
    const inexistente = path.join(m.raiz, 'nao-existe');
    const r = rodar(m.script, inexistente);
    assert.equal(r.status, 1);
    assert.equal(fs.existsSync(inexistente), false);
  } finally {
    fs.rmSync(m.raiz, { recursive: true, force: true });
  }
});

test('-Simular só lista: não altera o destino nem cria temporária', () => {
  const m = montar();
  try {
    const r = rodar(m.script, m.destino, ['-Simular']);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(fs.readFileSync(path.join(m.destino, 'specs', 'novo.md'), 'utf8'), 'antigo');
    assert.equal(fs.existsSync(path.join(m.destino, 'specs', 'so-no-destino.md')), true);
    assert.deepEqual(sobrasTemporarias(m.raiz), []);
  } finally {
    fs.rmSync(m.raiz, { recursive: true, force: true });
  }
});
