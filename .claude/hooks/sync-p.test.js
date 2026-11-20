const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const { sincronizar } = require('./sync-p.js');

test('Linux encerra com sucesso sem chamar PowerShell', () => {
  const executar = () => {
    throw new Error('PowerShell não deveria ser chamado');
  };
  assert.equal(sincronizar({ plataforma: 'linux', executar }), 0);
});

test('Windows preserva o comando de backup e devolve sucesso', () => {
  let chamada;
  const executar = (comando, argumentos, opcoes) => {
    chamada = { comando, argumentos, opcoes };
    return { status: 0 };
  };
  const script = 'C:\\projeto\\.claude\\sync-p.ps1';

  assert.equal(sincronizar({ plataforma: 'win32', executar, script }), 0);
  assert.deepEqual(chamada, {
    comando: 'powershell',
    argumentos: ['-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', script],
    opcoes: { stdio: 'inherit' },
  });
});

test('Windows propaga falha do script de backup', () => {
  assert.equal(sincronizar({
    plataforma: 'win32',
    executar: () => ({ status: 8 }),
  }), 8);
});

test('Windows falha fechado quando PowerShell não inicia', () => {
  assert.equal(sincronizar({
    plataforma: 'win32',
    executar: () => ({ error: new Error('indisponível'), status: null }),
  }), 1);
});

test('hook Stop usa o wrapper multiplataforma', () => {
  const settings = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'settings.json'), 'utf8'));
  const comandos = settings.hooks.Stop.flatMap((grupo) => grupo.hooks.map((hook) => hook.command));
  assert.ok(comandos.some((comando) => comando.includes('/.claude/hooks/sync-p.js')));
  assert.ok(comandos.every((comando) => !comando.includes('sync-p.ps1')));
});
