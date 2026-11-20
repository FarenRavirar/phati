const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');

const { sincronizar } = require('./sync-p.js');

// Trava em diretório temporário próprio: nunca toca a trava real do sistema.
const travaTemp = () => path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'sync-p-')), 'trava.lock');

test('Linux encerra com sucesso sem chamar PowerShell', () => {
  const executar = () => {
    throw new Error('PowerShell não deveria ser chamado');
  };
  assert.equal(sincronizar({ plataforma: 'linux', executar, trava: travaTemp() }), 0);
});

test('Windows preserva o comando de backup e devolve sucesso', () => {
  let chamada;
  const executar = (comando, argumentos, opcoes) => {
    chamada = { comando, argumentos, opcoes };
    return { status: 0 };
  };
  const script = 'C:\\projeto\\.claude\\sync-p.ps1';

  assert.equal(sincronizar({ plataforma: 'win32', executar, script, trava: travaTemp() }), 0);
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
    trava: travaTemp(),
  }), 8);
});

test('Windows falha fechado quando PowerShell não inicia', () => {
  assert.equal(sincronizar({
    plataforma: 'win32',
    executar: () => ({ error: new Error('indisponível'), status: null }),
    trava: travaTemp(),
  }), 1);
});

test('execução concorrente sai 0 sem rodar o script (trava exclusiva)', () => {
  const trava = travaTemp();
  const chamadas = [];
  let segunda;
  const executar = () => {
    chamadas.push('primeira');
    // Outra sessão para no meio desta execução e tenta de novo.
    segunda = sincronizar({ plataforma: 'win32', executar: () => { chamadas.push('segunda'); return { status: 0 }; }, trava });
    return { status: 0 };
  };

  assert.equal(sincronizar({ plataforma: 'win32', executar, trava }), 0);
  assert.equal(segunda, 0);
  assert.deepEqual(chamadas, ['primeira']);
});

test('trava é liberada depois da execução, inclusive quando o script falha', () => {
  const trava = travaTemp();
  assert.equal(sincronizar({ plataforma: 'win32', executar: () => ({ status: 8 }), trava }), 8);
  assert.equal(fs.existsSync(trava), false);

  let rodou = false;
  assert.equal(sincronizar({ plataforma: 'win32', executar: () => { rodou = true; return { status: 0 }; }, trava }), 0);
  assert.equal(rodou, true, 'depois de liberar, nova execução pode rodar');
});

test('trava de execução morta (mais velha que o limite) é tomada', () => {
  const trava = travaTemp();
  fs.writeFileSync(trava, '99999');
  const antiga = new Date(Date.now() - 60 * 60 * 1000);
  fs.utimesSync(trava, antiga, antiga);

  let rodou = false;
  assert.equal(sincronizar({ plataforma: 'win32', executar: () => { rodou = true; return { status: 0 }; }, trava }), 0);
  assert.equal(rodou, true);
  assert.equal(fs.existsSync(trava), false);
});

test('trava recente de outra execução impede e não é apagada', () => {
  const trava = travaTemp();
  fs.writeFileSync(trava, '99999');

  let rodou = false;
  assert.equal(sincronizar({ plataforma: 'win32', executar: () => { rodou = true; return { status: 0 }; }, trava }), 0);
  assert.equal(rodou, false);
  assert.equal(fs.existsSync(trava), true, 'trava de outra execução continua no lugar');
});

test('falha ao criar a trava sai 1 sem rodar o script', () => {
  const trava = path.join(os.tmpdir(), 'pasta-que-nao-existe-sync-p', 'trava.lock');
  let rodou = false;
  assert.equal(sincronizar({ plataforma: 'win32', executar: () => { rodou = true; return { status: 0 }; }, trava }), 1);
  assert.equal(rodou, false);
});

test('hook Stop usa o wrapper multiplataforma', () => {
  const settings = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'settings.json'), 'utf8'));
  const comandos = settings.hooks.Stop.flatMap((grupo) => grupo.hooks.map((hook) => hook.command));
  assert.ok(comandos.some((comando) => comando.includes('/.claude/hooks/sync-p.js')));
  assert.ok(comandos.every((comando) => !comando.includes('sync-p.ps1')));
});
