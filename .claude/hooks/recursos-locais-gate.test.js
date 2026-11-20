const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const path = require('node:path');
const test = require('node:test');

const { medir, mensagem } = require('./recursos-locais-gate.js');

const falso = (docker, tasklist) => (comando) => {
  const saida = comando === 'docker' ? docker : tasklist;
  if (saida instanceof Error) throw saida;
  return saida;
};

test('contêiner rodando é apontado pelo nome', () => {
  assert.deepEqual(medir(falso('phati-pg18-local\n', 'INFO: sem processos'), 'win32'), ['contêineres: phati-pg18-local']);
});

test('contêiner de outra tarefa não é sobra do agente', () => {
  assert.deepEqual(medir(falso('banco-de-outro-projeto\nphatiteste-app-1\n', 'INFO: sem processos'), 'win32'), ['contêineres: phatiteste-app-1']);
  assert.deepEqual(medir(falso('banco-de-outro-projeto\n', 'INFO: sem processos'), 'win32'), []);
});

test('vmmemWSL rodando é apontado', () => {
  assert.deepEqual(medir(falso('', '"vmmemWSL.exe","1234","Services","0","3.000.000 K"'), 'win32'), ['processo vmmemWSL']);
});

test('nada rodando devolve lista vazia', () => {
  assert.deepEqual(medir(falso('', 'INFO: Nenhuma tarefa em execução'), 'win32'), []);
});

test('docker ausente ou fora do ar não é erro nem sobra', () => {
  assert.deepEqual(medir(falso(new Error('docker: not found'), new Error('sem tasklist')), 'win32'), []);
});

test('linux sem PHATI_GATE_DOCKER não consulta Docker nem tasklist', () => {
  const chamadas = [];
  const executar = (comando) => {
    chamadas.push(comando);
    return comando === 'docker' ? 'phati-app-1\n' : 'vmmemWSL.exe';
  };

  assert.deepEqual(medir(executar, 'linux', {}), []);
  assert.deepEqual(medir(executar, 'linux', { PHATI_GATE_DOCKER: '0' }), []);
  assert.deepEqual(chamadas, []);
});

test('linux com PHATI_GATE_DOCKER=1 consulta só docker ps e aponta contêiner phati', () => {
  const chamadas = [];
  const executar = (comando, args) => {
    chamadas.push([comando, ...args]);
    return comando === 'docker' ? 'banco-de-outro-projeto\nphati-app-1\n' : 'vmmemWSL.exe';
  };

  assert.deepEqual(medir(executar, 'linux', { PHATI_GATE_DOCKER: '1' }), ['contêineres: phati-app-1']);
  assert.deepEqual(chamadas, [['docker', 'ps', '--format', '{{.Names}}']]);
});

test('linux com PHATI_GATE_DOCKER=1 e docker fora do ar não é erro', () => {
  assert.deepEqual(
    medir(falso(new Error('docker: not found'), ''), 'linux', { PHATI_GATE_DOCKER: '1' }),
    [],
  );
});

test('a mensagem manda fechar o contêiner e o wsl', () => {
  const texto = mensagem(['processo vmmemWSL']);
  assert.match(texto, /docker stop/);
  assert.match(texto, /wsl --shutdown/);
});

test('segunda parada no mesmo turno passa (trava de laço)', () => {
  const r = execFileSync('node', [path.join(__dirname, 'recursos-locais-gate.js')], {
    input: JSON.stringify({ stop_hook_active: true }),
    stdio: ['pipe', 'pipe', 'pipe'],
  });
  assert.equal(r.toString(), '');
});
