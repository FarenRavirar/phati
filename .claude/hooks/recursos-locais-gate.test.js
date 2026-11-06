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
  assert.deepEqual(medir(falso('phati-pg18-local\n', 'INFO: sem processos')), ['contêineres: phati-pg18-local']);
});

test('contêiner de outra tarefa não é sobra do agente', () => {
  assert.deepEqual(medir(falso('banco-de-outro-projeto\nphatiteste-app-1\n', 'INFO: sem processos')), ['contêineres: phatiteste-app-1']);
  assert.deepEqual(medir(falso('banco-de-outro-projeto\n', 'INFO: sem processos')), []);
});

test('vmmemWSL rodando é apontado', () => {
  assert.deepEqual(medir(falso('', '"vmmemWSL.exe","1234","Services","0","3.000.000 K"')), ['processo vmmemWSL']);
});

test('nada rodando devolve lista vazia', () => {
  assert.deepEqual(medir(falso('', 'INFO: Nenhuma tarefa em execução')), []);
});

test('docker ausente ou fora do ar não é erro nem sobra', () => {
  assert.deepEqual(medir(falso(new Error('docker: not found'), new Error('sem tasklist'))), []);
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
