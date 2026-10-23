'use strict';
// Suíte do verificar-par-teste. Roda com: node --test .githooks/

const test = require('node:test');
const assert = require('node:assert/strict');
const { verificar, parEsperado } = require('./verificar-par-teste.js');

const nada = () => false;

test('Python de app exige o par em testes/', () => {
  assert.equal(parEsperado('servidor/permissao/pode.py'), 'servidor/permissao/testes/test_pode.py');
  assert.equal(
    parEsperado('servidor/identidade/management/commands/criar_administrador_plataforma.py'),
    'servidor/identidade/testes/test_criar_administrador_plataforma.py',
  );
});

test('isentos da lista fixa não exigem par', () => {
  for (const c of [
    'servidor/permissao/__init__.py',
    'servidor/permissao/apps.py',
    'servidor/permissao/migrations/0001_inicial.py',
    'servidor/manage.py',
    'servidor/projeto/wsgi.py',
    'servidor/projeto/asgi.py',
    'servidor/conftest.py',
    'servidor/permissao/testes/test_pode.py',
    'README.md',
  ]) {
    assert.equal(parEsperado(c), null, c);
  }
});

test('JS/TS exige o .test irmão; o próprio teste e .d.ts não', () => {
  assert.equal(parEsperado('.githooks/x.js'), '.githooks/x.test.js');
  assert.equal(parEsperado('app/y.ts'), 'app/y.test.ts');
  assert.equal(parEsperado('.githooks/x.test.js'), null);
  assert.equal(parEsperado('app/tipos.d.ts'), null);
});

test('sem par existente nem no commit, bloqueia', () => {
  const achados = verificar({ caminhos: ['servidor/permissao/pode.py'], existe: nada });
  assert.deepEqual(achados, [{ arquivo: 'servidor/permissao/pode.py', par: 'servidor/permissao/testes/test_pode.py' }]);
});

test('par no mesmo commit ou já no repositório passa', () => {
  const noCommit = verificar({
    caminhos: ['servidor/permissao/pode.py', 'servidor/permissao/testes/test_pode.py'],
    existe: nada,
  });
  assert.deepEqual(noCommit, []);
  const noRepo = verificar({ caminhos: ['servidor/permissao/pode.py'], existe: () => true });
  assert.deepEqual(noRepo, []);
});

test('de ponta a ponta: par só no disco (fora do stage) bloqueia; par no stage passa', () => {
  const { execFileSync } = require('node:child_process');
  const fs = require('node:fs');
  const os = require('node:os');
  const path = require('node:path');
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), 'par-teste-'));
  const git = (...args) => execFileSync('git', args, { cwd: repo, stdio: 'pipe' });
  const escrever = (caminho) => {
    fs.mkdirSync(path.dirname(path.join(repo, caminho)), { recursive: true });
    fs.writeFileSync(path.join(repo, caminho), '# x\n');
  };
  const hook = () => {
    try {
      execFileSync('node', [path.join(__dirname, 'verificar-par-teste.js')], { cwd: repo, stdio: 'pipe' });
      return 0;
    } catch (erro) {
      return erro.status;
    }
  };
  try {
    git('init', '-q');
    escrever('servidor/x/y.py');
    escrever('servidor/x/testes/test_y.py');
    git('add', 'servidor/x/y.py');
    assert.equal(hook(), 1, 'par untracked no disco não conta');
    git('add', 'servidor/x/testes/test_y.py');
    assert.equal(hook(), 0, 'par no stage conta');
  } finally {
    fs.rmSync(repo, { recursive: true, force: true });
  }
});
