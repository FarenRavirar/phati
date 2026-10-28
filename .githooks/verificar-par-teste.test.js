'use strict';
// Suíte do verificar-par-teste. Roda com: node --test .githooks/

const test = require('node:test');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { verificar, parEsperado } = require('./verificar-par-teste.js');

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
    'servidor/permissao/testes/test_pode.py',
    'README.md',
  ]) {
    assert.equal(parEsperado(c), null, c);
  }
});

test('conftest.py exige par, na raiz de servidor/ e dentro de app', () => {
  assert.equal(parEsperado('servidor/conftest.py'), 'servidor/projeto/testes/test_conftest.py');
  assert.equal(parEsperado('servidor/permissao/conftest.py'), 'servidor/permissao/testes/test_conftest.py');
});

test('JS/TS exige o .test irmão; o próprio teste e .d.ts não', () => {
  assert.equal(parEsperado('.githooks/x.js'), '.githooks/x.test.js');
  assert.equal(parEsperado('app/y.ts'), 'app/y.test.ts');
  assert.equal(parEsperado('.githooks/x.test.js'), null);
  assert.equal(parEsperado('app/tipos.d.ts'), null);
});

test('sem par existente nem no commit, bloqueia', () => {
  const achados = verificar({ caminhos: ['servidor/permissao/pode.py'], rastreados: ['servidor/permissao/pode.py'] });
  assert.deepEqual(achados, [{ arquivo: 'servidor/permissao/pode.py', par: 'servidor/permissao/testes/test_pode.py' }]);
});

test('par no índice (no mesmo commit ou já no repositório) passa', () => {
  const rastreados = ['servidor/permissao/pode.py', 'servidor/permissao/testes/test_pode.py'];
  assert.deepEqual(verificar({ caminhos: rastreados, rastreados }), []);
  assert.deepEqual(verificar({ caminhos: ['servidor/permissao/pode.py'], rastreados }), []);
});

test('apagar só o teste de um módulo rastreado bloqueia; apagar os dois passa', () => {
  const teste = 'servidor/permissao/testes/test_pode.py';
  const so = verificar({ caminhos: [], removidos: [teste], rastreados: ['servidor/permissao/pode.py'] });
  assert.deepEqual(so, [{ arquivo: 'servidor/permissao/pode.py', par: teste }]);
  assert.deepEqual(verificar({ caminhos: [], removidos: [teste, 'servidor/permissao/pode.py'], rastreados: [] }), []);
});

// Repositório temporário com os hooks copiados; devolve utilitários para os testes de ponta a ponta.
function criarRepositorio() {
  const repositorio = fs.mkdtempSync(path.join(os.tmpdir(), 'par-teste-'));
  const git = (...argumentos) => execFileSync('git', argumentos, { cwd: repositorio, stdio: 'pipe' });
  const escrever = (caminho, conteudo = '# x\n') => {
    fs.mkdirSync(path.dirname(path.join(repositorio, caminho)), { recursive: true });
    fs.writeFileSync(path.join(repositorio, caminho), conteudo);
  };
  const executar = (...comando) => {
    try {
      execFileSync(comando[0], comando.slice(1), { cwd: repositorio, stdio: 'pipe' });
      return 0;
    } catch (erro) {
      return erro.status;
    }
  };
  const executarHook = (...argumentos) => executar('node', path.join(__dirname, 'verificar-par-teste.js'), ...argumentos);
  const limpar = () => fs.rmSync(repositorio, { recursive: true, force: true });
  return { repositorio, git, escrever, executar, executarHook, limpar };
}

test('de ponta a ponta: par só no disco (fora do stage) bloqueia; par no stage passa', () => {
  const { git, escrever, executarHook, limpar } = criarRepositorio();
  try {
    git('init', '-q');
    escrever('servidor/x/y.py');
    escrever('servidor/x/testes/test_y.py');
    git('add', 'servidor/x/y.py');
    assert.equal(executarHook(), 1, 'par untracked no disco não conta');
    git('add', 'servidor/x/testes/test_y.py');
    assert.equal(executarHook(), 0, 'par no stage conta');
    git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'base', '--no-verify');
    git('rm', '-q', 'servidor/x/testes/test_y.py');
    assert.equal(executarHook(), 1, 'apagar só o teste bloqueia');
    git('rm', '-q', 'servidor/x/y.py');
    assert.equal(executarHook(), 0, 'apagar módulo e teste passa');
  } finally {
    limpar();
  }
});

test('de ponta a ponta: com <base> confere o intervalo commitado, sem olhar o stage (uso do CI)', () => {
  const { git, escrever, executarHook, limpar } = criarRepositorio();
  const commitar = (mensagem) =>
    git('-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', mensagem, '--no-verify');
  try {
    git('init', '-q', '-b', 'dev');
    escrever('LEIAME.md');
    git('add', '.');
    commitar('base');
    git('switch', '-q', '-c', 'feat/x');
    escrever('servidor/x/y.py');
    git('add', '.');
    commitar('sem par');
    assert.equal(executarHook('dev'), 1, 'módulo sem par no intervalo bloqueia, com o stage vazio');
    escrever('servidor/x/testes/test_y.py');
    git('add', '.');
    commitar('par');
    assert.equal(executarHook('dev'), 0, 'par no intervalo passa');
  } finally {
    limpar();
  }
});

test('de ponta a ponta: par adicionado só com git add -N não conta', () => {
  const { git, escrever, executarHook, limpar } = criarRepositorio();
  try {
    git('init', '-q');
    escrever('servidor/x/y.py');
    escrever('servidor/x/testes/test_y.py');
    git('add', 'servidor/x/y.py');
    git('add', '-N', 'servidor/x/testes/test_y.py');
    assert.equal(executarHook(), 1, 'intent-to-add não entra no commit');
  } finally {
    limpar();
  }
});

test('o pre-commit propaga a falha de cada verificador (vazamento e par)', () => {
  const { git, escrever, executar, limpar, repositorio } = criarRepositorio();
  try {
    git('init', '-q');
    for (const arquivo of ['pre-commit', 'verificar-vazamento.js', 'verificar-par-teste.js']) {
      fs.mkdirSync(path.join(repositorio, '.githooks'), { recursive: true });
      fs.copyFileSync(path.join(__dirname, arquivo), path.join(repositorio, '.githooks', arquivo));
    }
    const executarPreCommit = () => executar('sh', '.githooks/pre-commit');
    escrever('servidor/x/y.py');
    escrever('servidor/x/testes/test_y.py');
    git('add', 'servidor/x/y.py', 'servidor/x/testes/test_y.py');
    assert.equal(executarPreCommit(), 0, 'sem problema, passa');
    git('rm', '-q', '--cached', 'servidor/x/testes/test_y.py');
    assert.notEqual(executarPreCommit(), 0, 'o primeiro verificador passa e o segundo (par) falha');
    git('add', 'servidor/x/testes/test_y.py');
    escrever('.env', 'x=1\n');
    git('add', '-f', '.env');
    assert.notEqual(executarPreCommit(), 0, 'o primeiro verificador (vazamento) falha');
  } finally {
    limpar();
  }
});

test('pre-commit está versionado como executável (o git ignora hook sem o bit +x)', () => {
  const saida = execFileSync('git', ['ls-files', '-s', '.githooks/pre-commit'], { encoding: 'utf8' });
  assert.match(saida, /^100755 /);
});
