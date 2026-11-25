// Testes do escopo de CI (scripts/escopo-ci.js): decide quais jobs de PR rodam pelos arquivos alterados.
// Roda com: node --test scripts/escopo-ci.test.js
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const { decidir, decidirCodeql, listarPadrao } = require('./escopo-ci.js');

const SEM_CODEQL = { codeql_python: false, codeql_javascript_typescript: false, codeql_actions: false };
const TUDO_CODEQL = { codeql_python: true, codeql_javascript_typescript: true, codeql_actions: true };
const codeqlDe = (arquivos) => decidirCodeql({ evento: 'pull_request', baseRef: 'dev', listar: () => arquivos });

const TUDO = { python: true, node: true, docker: true, navegador: true };
const NADA = { python: false, node: false, docker: false, navegador: false };

const rodar = (arquivos) => decidir({ evento: 'pull_request', baseRef: 'dev', listar: () => arquivos });

test('só documentação não dispara nenhum job', () => {
  assert.deepEqual(rodar(['README.md', 'docs/nota com espaço.md', '.agents/skills/x/LICENSE']), NADA);
});

test('só scripts/implantar.sh: navegador e docker ficam falsos', () => {
  const r = rodar(['scripts/implantar.sh']);
  assert.equal(r.navegador, false);
  assert.equal(r.docker, false);
  assert.equal(r.node, true);
});

test('só view Python do servidor: navegador false, backend e docker true', () => {
  const r = rodar(['servidor/projeto/views.py']);
  assert.equal(r.navegador, false);
  assert.equal(r.python, true);
  assert.equal(r.docker, true);
});

test('só template do servidor: navegador true', () => {
  assert.equal(rodar(['servidor/projeto/templates/projeto/entrar.html']).navegador, true);
});

test('JS de static do servidor: node e navegador true', () => {
  const r = rodar(['servidor/projeto/static/projeto/mapa.js']);
  assert.equal(r.node, true);
  assert.equal(r.navegador, true);
});

test('navegador/ e playwright.config.js: navegador true, docker false', () => {
  const r = rodar(['navegador/mapa.spec.js', 'playwright.config.js']);
  assert.equal(r.navegador, true);
  assert.equal(r.docker, false);
});

test('package.json da raiz: navegador e node true, docker false', () => {
  const r = rodar(['package.json']);
  assert.equal(r.navegador, true);
  assert.equal(r.node, true);
  assert.equal(r.docker, false);
});

test('.github muda: tudo roda', () => {
  assert.deepEqual(rodar(['.github/workflows/ci.yml']), TUDO);
});

test('mistura de documentação e servidor: só o que o servidor aciona', () => {
  const r = rodar(['README.md', 'servidor/projeto/views.py']);
  assert.equal(r.python, true);
  assert.equal(r.docker, true);
  assert.equal(r.navegador, false);
});

test('md dentro de servidor/ é lido por pytest: python e docker true', () => {
  const r = rodar(['servidor/projeto/contrato_mapa.md']);
  assert.equal(r.python, true);
  assert.equal(r.docker, true);
});

test('hook em .claude: só node (par arquivo-teste), docker e navegador false', () => {
  assert.deepEqual(rodar(['.claude/hooks/rtk-enforce.js']), { python: false, node: true, docker: false, navegador: false });
});

test('.githooks: só node', () => {
  assert.deepEqual(rodar(['.githooks/pre-commit']), { python: false, node: true, docker: false, navegador: false });
});

test('arquivo desconhecido na raiz: tudo roda (falha fechada)', () => {
  assert.deepEqual(rodar(['arquivo-novo.xyz']), TUDO);
});

test('lista vazia: tudo roda', () => {
  assert.deepEqual(rodar([]), TUDO);
});

test('erro do git: tudo roda', () => {
  const r = decidir({
    evento: 'pull_request',
    baseRef: 'dev',
    listar: () => {
      throw new Error('fatal: ambiguous argument');
    },
  });
  assert.deepEqual(r, TUDO);
});

test('evento push: tudo roda e nem consulta o git', () => {
  let chamou = false;
  const r = decidir({ evento: 'push', baseRef: '', listar: () => { chamou = true; return []; } });
  assert.deepEqual(r, TUDO);
  assert.equal(chamou, false);
});

test('base ausente: tudo roda e nem consulta o git', () => {
  let chamou = false;
  const r = decidir({ evento: 'pull_request', baseRef: '', listar: () => { chamou = true; return ['README.md']; } });
  assert.deepEqual(r, TUDO);
  assert.equal(chamou, false);
});

test('base com caractere de shell: tudo roda (não é nome de branch válido)', () => {
  let chamou = false;
  const r = decidir({ evento: 'pull_request', baseRef: 'dev;rm -rf /', listar: () => { chamou = true; return ['README.md']; } });
  assert.deepEqual(r, TUDO);
  assert.equal(chamou, false);
});

// Cada arquivo lido por um teste tem de acionar o job desse teste. Medido com preload que registra fs.*Sync por arquivo
// (`--require` com `readFileSync`/`existsSync`/`openSync`...) e, onde o teste lê por código, com a linha citada.
const LEITURAS = [
  ['servidor/compose.yaml', 'node', 'scripts/implantacao.test.js:1814 (readFileSync)'],
  ['servidor/projeto/static/projeto/agrion/tokens/colors.css', 'node', 'scripts/contraste-tokens.test.js:11 (readFileSync)'],
  ['servidor/projeto/static/projeto/estilo_base.json', 'node', 'servidor/projeto/static/projeto/fundo-aberto.test.js:7 (readFileSync)'],
  ['servidor/projeto/templates/camadas_envio.html', 'node', 'servidor/projeto/static/projeto/camadas.test.js:91 (readFileSync via TEMPLATES)'],
  ['servidor/projeto/templates/redefinir_senha.html', 'node', 'servidor/projeto/static/projeto/redefinir-senha.test.js (medido em execução)'],
  ['servidor/pacote/referencia/fundo.pmtiles', 'node', '.githooks/verificar-vazamento.test.js:194 (readFileSync)'],
  ['servidor/projeto/static/projeto/redefinir-senha.js', 'python', 'servidor/projeto/testes/test_paginas.py:32 (read_text)'],
  ['servidor/projeto/static/projeto/terceiros/pmtiles/pmtiles.js', 'python', 'servidor/projeto/testes/test_pmtiles_terceiros.py:32 (read_text)'],
  ['.github/workflows/ci.yml', 'python', 'servidor/projeto/testes/test_ci_portas.py:22 (read_text, fora de servidor/)'],
];
for (const [arquivo, job, origem] of LEITURAS) {
  test(`leitura de ${arquivo} (${origem}) aciona o job ${job}`, () => {
    assert.equal(rodar([arquivo])[job], true, `${arquivo} não aciona ${job}`);
  });
}

test('nomes hostis (espaço e quebra de linha) são classificados pelo caminho inteiro', () => {
  const r = rodar(['docs/a b.md', 'scripts/linha\nquebrada.js']);
  assert.deepEqual(r, { python: false, node: true, docker: false, navegador: false });
});

test('ci.yml: sem paths, e cada job tem needs escopo com !cancelled() e a condição do seu grupo', () => {
  const texto = fs.readFileSync(path.join(__dirname, '..', '.github', 'workflows', 'ci.yml'), 'utf8');
  assert.doesNotMatch(texto, /^\s*paths(-ignore)?:/m);
  const blocos = {};
  let atual = null;
  for (const linha of texto.split('\n')) {
    const cabecalho = /^  ([a-z-]+):\s*$/.exec(linha);
    if (cabecalho) atual = blocos[cabecalho[1]] = [];
    else if (atual) atual.push(linha);
  }
  assert.ok(blocos.escopo, 'job escopo existe');
  const condicoes = { testes: /needs\.escopo\.outputs\.python != 'false' \|\| needs\.escopo\.outputs\.node != 'false'/, docker: /needs\.escopo\.outputs\.docker != 'false'/, navegador: /needs\.escopo\.outputs\.navegador != 'false'/ };
  for (const [job, condicao] of Object.entries(condicoes)) {
    const bloco = (blocos[job] ?? []).join('\n');
    assert.match(bloco, /^    needs: escopo\s*$/m, `${job} precisa de needs: escopo`);
    assert.match(bloco, /^    if: \$\{\{ !cancelled\(\) && .*\}\}\s*$/m, `${job} precisa de if com !cancelled()`);
    assert.match(bloco, condicao, `${job} sem a condição do seu grupo`);
  }
});

test('CLI: grava as saídas no GITHUB_OUTPUT (evento push)', () => {
  const pasta = fs.mkdtempSync(path.join(os.tmpdir(), 'escopo-'));
  const saida = path.join(pasta, 'saida');
  const r = spawnSync(process.execPath, [path.join(__dirname, 'escopo-ci.js')], {
    env: { ...process.env, GITHUB_EVENT_NAME: 'push', GITHUB_OUTPUT: saida },
    encoding: 'utf8',
  });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(fs.readFileSync(saida, 'utf8'), 'python=true\nnode=true\ndocker=true\nnavegador=true\ncodeql_python=true\ncodeql_javascript_typescript=true\ncodeql_actions=true\n');
});

test('codeql: só .py ativa a análise de python', () => {
  assert.deepEqual(codeqlDe(['servidor/projeto/views.py']), { codeql_python: true, codeql_javascript_typescript: false, codeql_actions: false });
});

test('codeql: só documentação não analisa linguagem nenhuma', () => {
  assert.deepEqual(codeqlDe(['README.md', 'docs/nota.md']), SEM_CODEQL);
});

test('codeql: JS e HTML ativam javascript-typescript', () => {
  assert.equal(codeqlDe(['scripts/x.js']).codeql_javascript_typescript, true);
  assert.equal(codeqlDe(['servidor/projeto/templates/projeto/entrar.html']).codeql_javascript_typescript, true);
});

test('codeql: .github ativa actions', () => {
  assert.equal(codeqlDe(['.github/workflows/codeql.yml']).codeql_actions, true);
});

test('codeql: arquivo desconhecido analisa tudo', () => {
  assert.deepEqual(codeqlDe(['arquivo-novo.xyz']), TUDO_CODEQL);
});

test('codeql: push analisa tudo sem consultar o git', () => {
  const r = decidirCodeql({ evento: 'push', baseRef: '', listar: () => { throw new Error('não deveria ser chamado'); } });
  assert.deepEqual(r, TUDO_CODEQL);
});

test('codeql.yml: sem paths, job escopo próprio, analisar com needs escopo e passos de análise filtrados', () => {
  const texto = fs.readFileSync(path.join(__dirname, '..', '.github', 'workflows', 'codeql.yml'), 'utf8');
  assert.doesNotMatch(texto, /^\s*paths(-ignore)?:/m);
  assert.match(texto, /^  escopo:\s*$/m);
  assert.match(texto, /^  analisar:\n    needs: escopo\n    if: \$\{\{ !cancelled\(\) \}\}\n/m);
  const ifs = texto.split('\n').filter((l) => /^        if: /.test(l));
  assert.equal(ifs.length, 2);
  for (const l of ifs) assert.match(l, /github\.event_name != 'pull_request'/);
});

test('ci.yml: cada passo Python só roda com python, cada passo Node só com node', () => {
  const texto = fs.readFileSync(path.join(__dirname, '..', '.github', 'workflows', 'ci.yml'), 'utf8');
  const inicio = texto.indexOf('\n  testes:\n');
  const fim = texto.indexOf('\n  docker:\n');
  const passos = texto.slice(inicio, fim).split(/\n(?=      - )/).slice(1);
  assert.ok(passos.length > 10, 'passos do job testes');
  for (const passo of passos) {
    const cabeca = passo.split('\n')[0];
    if (/pytest|pyright|pip install|manage\.py|setup-python|diff-cover|psql|docker (build|pull)|apt-get|pmtiles/.test(passo)) {
      assert.match(passo, /outputs\.python != 'false'/, cabeca);
    }
    if (/npm ci|node --test|trava-flock/.test(passo)) {
      assert.match(passo, /outputs\.node != 'false'/, cabeca);
    }
  }
});

test('CLI: fora de um repositório git, o erro do git vira tudo true e exit 0', () => {
  const pasta = fs.mkdtempSync(path.join(os.tmpdir(), 'escopo-'));
  const saida = path.join(pasta, 'saida');
  const r = spawnSync(process.execPath, [path.join(__dirname, 'escopo-ci.js')], {
    cwd: pasta,
    env: { ...process.env, GITHUB_EVENT_NAME: 'pull_request', GITHUB_BASE_REF: 'dev', GITHUB_OUTPUT: saida },
    encoding: 'utf8',
  });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(fs.readFileSync(saida, 'utf8'), 'python=true\nnode=true\ndocker=true\nnavegador=true\ncodeql_python=true\ncodeql_javascript_typescript=true\ncodeql_actions=true\n');
});

// PATH hostil: um `git` falso na frente do PATH não pode ser executado (S4036). O git real vem por caminho fixo.
function gitFalsoEmPath() {
  const pasta = fs.mkdtempSync(path.join(os.tmpdir(), 'escopo-path-'));
  const marca = path.join(pasta, 'marca');
  fs.writeFileSync(path.join(pasta, 'git'), `#!/bin/sh\ntouch "$MARCA"\necho fake.md\n`, { mode: 0o755 });
  return { pasta, marca };
}
const rodarListagemComPath = (cwd, falso) => spawnSync(process.execPath, ['-e', `
  const { listarPadrao } = require(${JSON.stringify(path.join(__dirname, 'escopo-ci.js'))});
  try { process.stdout.write(JSON.stringify(listarPadrao('dev'))); } catch (e) { process.stdout.write('ERRO'); }
`], { cwd, env: { PATH: falso.pasta, MARCA: falso.marca }, encoding: 'utf8' });

test('listarPadrao com PATH hostil: usa o git real e não executa o git falso', () => {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), 'escopo-repo-'));
  const git = (...a) => spawnSync('/usr/bin/git', ['-c', 'user.name=t', '-c', 'user.email=t@t', ...a], { cwd: repo, encoding: 'utf8' });
  assert.equal(git('init', '-q').status, 0);
  fs.writeFileSync(path.join(repo, 'base.md'), 'x');
  assert.equal(git('add', '-A').status, 0);
  assert.equal(git('commit', '-q', '-m', 'base').status, 0);
  assert.equal(git('update-ref', 'refs/remotes/origin/dev', 'HEAD').status, 0);
  fs.writeFileSync(path.join(repo, 'a b.md'), 'y');
  assert.equal(git('add', '-A').status, 0);
  assert.equal(git('commit', '-q', '-m', 'mudanca').status, 0);
  const falso = gitFalsoEmPath();
  const r = rodarListagemComPath(repo, falso);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stdout, '["a b.md"]');
  assert.equal(fs.existsSync(falso.marca), false, 'o git falso do PATH foi executado');
});

test('listarPadrao fora de repositório com PATH hostil: erra e não executa o git falso', () => {
  const pasta = fs.mkdtempSync(path.join(os.tmpdir(), 'escopo-sem-repo-'));
  const falso = gitFalsoEmPath();
  const r = rodarListagemComPath(pasta, falso);
  assert.equal(r.stdout, 'ERRO');
  assert.equal(fs.existsSync(falso.marca), false, 'o git falso do PATH foi executado');
});

// R9 (spec 011): o job de testes do CI roda na mesma minor do Python da imagem do servidor (servidor/Dockerfile).
test('CI: python-version do job testes é a minor do FROM python do servidor/Dockerfile', () => {
  const raiz = path.join(__dirname, '..');
  const ci = fs.readFileSync(path.join(raiz, '.github', 'workflows', 'ci.yml'), 'utf8').replace(/\r\n/g, '\n');
  const dockerfile = fs.readFileSync(path.join(raiz, 'servidor', 'Dockerfile'), 'utf8');
  const versoesCi = [...ci.matchAll(/python-version: "(\d+\.\d+)"/g)].map((m) => m[1]);
  const imagem = dockerfile.match(/^FROM python:(\d+\.\d+)-slim/m);
  assert.equal(versoesCi.length, 1, 'esperava um python-version no ci.yml');
  assert.ok(imagem, 'Dockerfile sem FROM python:<minor>-slim');
  assert.equal(versoesCi[0], imagem[1]);
});
