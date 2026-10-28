'use strict';
// Suíte da promoção dev -> main: scripts de invariante e de promoção, e o contrato dos workflows que os chamam.
// Roda com: node --test scripts/
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { execFileSync, spawnSync } = require('node:child_process');

const CAMINHO_VALIDAR = path.join(__dirname, 'validar-invariante-ramos.sh');
const CAMINHO_PROMOVER = path.join(__dirname, 'promover-dev-para-main.sh');
const CAMINHO_ATUALIZAR_PR = path.join(__dirname, 'atualizar-pr-promocao.sh');
const PASTA_DOS_FLUXOS = path.join(__dirname, '..', '.github', 'workflows');
const CONFIRMACAO = 'PROMOTE_DEV_TO_MAIN';

// Remoto bare com main e dev (dev à frente), uma cópia de trabalho e uma segunda cópia para divergir main.
function criarCenario() {
  const raiz = fs.mkdtempSync(path.join(os.tmpdir(), 'promocao-'));
  const remoto = path.join(raiz, 'remoto.git');
  const trabalho = path.join(raiz, 'trabalho');
  const outro = path.join(raiz, 'outro');
  const git = (cwd, ...argumentos) => execFileSync('git', argumentos, { cwd, stdio: 'pipe', encoding: 'utf8' }).trim();
  const commitar = (cwd, arquivo) => {
    fs.writeFileSync(path.join(cwd, arquivo), `${arquivo}\n`);
    git(cwd, 'add', arquivo);
    git(cwd, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', arquivo);
  };
  execFileSync('git', ['init', '-q', '--bare', '-b', 'main', remoto]);
  execFileSync('git', ['clone', '-q', remoto, trabalho], { stdio: 'pipe' });
  git(trabalho, 'switch', '-q', '-c', 'main');
  commitar(trabalho, 'base');
  git(trabalho, 'push', '-q', 'origin', 'main');
  git(trabalho, 'switch', '-q', '-c', 'dev');
  commitar(trabalho, 'so-dev');
  git(trabalho, 'push', '-q', 'origin', 'dev');
  const divergirMain = () => {
    execFileSync('git', ['clone', '-q', remoto, outro], { stdio: 'pipe' });
    git(outro, 'switch', '-q', 'main');
    commitar(outro, 'so-main');
    git(outro, 'push', '-q', 'origin', 'main');
  };
  const shaRemoto = (ramo) => git(remoto, 'rev-parse', ramo);
  const executar = (...argumentos) => spawnSync('bash', argumentos, { cwd: trabalho, encoding: 'utf8' });
  const limpar = () => fs.rmSync(raiz, { recursive: true, force: true });
  return { divergirMain, shaRemoto, executar, limpar };
}

test('invariante: main ancestral de dev passa; main com commit fora de dev bloqueia', () => {
  const { divergirMain, executar, limpar } = criarCenario();
  try {
    const ok = executar(CAMINHO_VALIDAR);
    assert.equal(ok.status, 0, ok.stderr);
    assert.match(ok.stdout, /invariante_ramos_ok=true/);
    divergirMain();
    const quebrada = executar(CAMINHO_VALIDAR);
    assert.equal(quebrada.status, 1);
    assert.match(quebrada.stderr, /não é ancestral/);
  } finally {
    limpar();
  }
});

test('promoção: confirmação inválida não muda main', () => {
  const { shaRemoto, executar, limpar } = criarCenario();
  try {
    const antes = shaRemoto('main');
    const resultado = executar(CAMINHO_PROMOVER, 'errada');
    assert.equal(resultado.status, 1);
    assert.match(resultado.stderr, /PROMOTE_DEV_TO_MAIN/);
    assert.equal(shaRemoto('main'), antes, 'main intacta');
  } finally {
    limpar();
  }
});

test('promoção: histórico divergente não muda main', () => {
  const { divergirMain, shaRemoto, executar, limpar } = criarCenario();
  try {
    divergirMain();
    const antes = shaRemoto('main');
    const resultado = executar(CAMINHO_PROMOVER, CONFIRMACAO);
    assert.equal(resultado.status, 1);
    assert.match(resultado.stderr, /não é ancestral/);
    assert.equal(shaRemoto('main'), antes, 'main intacta');
  } finally {
    limpar();
  }
});

test('promoção: válida leva main ao mesmo SHA de dev', () => {
  const { shaRemoto, executar, limpar } = criarCenario();
  try {
    const shaDoDev = shaRemoto('dev');
    assert.notEqual(shaRemoto('main'), shaDoDev, 'main começa atrás de dev');
    const resultado = executar(CAMINHO_PROMOVER, CONFIRMACAO);
    assert.equal(resultado.status, 0, resultado.stderr);
    assert.equal(shaRemoto('main'), shaDoDev, 'fast-forward preserva o SHA de dev');
  } finally {
    limpar();
  }
});

// Contrato dos workflows: o que o YAML precisa dizer para os scripts testados acima valerem.
const ler = (nome) => fs.readFileSync(path.join(PASTA_DOS_FLUXOS, nome), 'utf8').replace(/\r\n/g, '\n');

test('workflow do guard: dispara em push em main e chama o script de invariante', () => {
  const texto = ler('vigiar-ancestralidade-main.yml');
  assert.match(texto, /on:\n {2}push:\n {4}branches:\n {6}- main\n/);
  assert.match(texto, /bash scripts\/validar-invariante-ramos\.sh/);
});

test('workflow de promoção: dispatch com confirmacao, só chama o script e nunca dá push direto', () => {
  const texto = ler('promover-dev-para-main.yml');
  assert.match(texto, /workflow_dispatch:\n {4}inputs:\n {6}confirmacao:/);
  assert.match(texto, /bash scripts\/promover-dev-para-main\.sh "\$CONFIRMACAO"/);
  assert.match(texto, /contents: write/);
  assert.doesNotMatch(texto, /git push/);
});

test('PR permanente: o workflow dispara em push em dev e só chama o script', () => {
  const texto = ler('pr-permanente-promocao.yml');
  assert.match(texto, /on:\n {2}push:\n {4}branches:\n {6}- dev\n/);
  assert.match(texto, /bash scripts\/atualizar-pr-promocao\.sh/);
  assert.match(texto, /DONO: \$\{\{ github\.repository_owner \}\}/);
});

// `gh` falso: grava cada chamada em um arquivo e responde com o que o teste define.
function criarGhFalso({ lista = '', statusEditar = 0, statusCriar = 0 }) {
  const raiz = fs.mkdtempSync(path.join(os.tmpdir(), 'gh-falso-'));
  const registro = path.join(raiz, 'chamadas.log');
  fs.writeFileSync(
    path.join(raiz, 'gh'),
    `#!/usr/bin/env bash
printf '%s\\n' "$*" >> "${registro.replace(/\\/g, '/')}"
case "$1 $2" in
  "pr list") printf '%s' "${lista}" ;;
  "pr edit") exit ${statusEditar} ;;
  "pr create") exit ${statusCriar} ;;
esac
`,
    { mode: 0o755 },
  );
  const executar = () =>
    spawnSync('bash', [CAMINHO_ATUALIZAR_PR], {
      encoding: 'utf8',
      env: { ...process.env, PATH: `${raiz}${path.delimiter}${process.env.PATH}`, DONO: 'dono-do-repo' },
    });
  const chamadas = () => fs.readFileSync(registro, 'utf8').split('\n').filter(Boolean);
  const limpar = () => fs.rmSync(raiz, { recursive: true, force: true });
  return { executar, chamadas, limpar };
}

test('PR permanente: sem PR aberta, cria com base main e cabeça dev', () => {
  const { executar, chamadas, limpar } = criarGhFalso({ lista: '' });
  try {
    const resultado = executar();
    assert.equal(resultado.status, 0, resultado.stderr);
    assert.match(resultado.stdout, /pr_promocao=criada/);
    const listar = chamadas()[0];
    assert.match(listar, /pr list --base main --head dev --state open/);
    assert.ok(listar.includes('headRepositoryOwner.login == "dono-do-repo"'), 'filtra o dono da PR');
    const criar = chamadas().find((c) => c.startsWith('pr create'));
    assert.match(criar, /--base main --head dev/);
    assert.ok(!chamadas().some((c) => c.startsWith('pr edit')), 'não edita quando não há PR');
  } finally {
    limpar();
  }
});

test('PR permanente: com PR aberta, edita o número encontrado e não cria outra', () => {
  const { executar, chamadas, limpar } = criarGhFalso({ lista: '7\n' });
  try {
    const resultado = executar();
    assert.equal(resultado.status, 0, resultado.stderr);
    assert.match(resultado.stdout, /pr_promocao=7/);
    assert.match(chamadas().find((c) => c.startsWith('pr edit')), /^pr edit 7 --title/);
    assert.ok(!chamadas().some((c) => c.startsWith('pr create')), 'não cria quando já existe');
  } finally {
    limpar();
  }
});

test('PR permanente: falha ao editar ou criar vira aviso e não derruba o job', () => {
  for (const falha of [{ lista: '7', statusEditar: 1 }, { lista: '', statusCriar: 1 }]) {
    const { executar, limpar } = criarGhFalso(falha);
    try {
      const resultado = executar();
      assert.equal(resultado.status, 0, resultado.stderr);
      assert.match(resultado.stdout, /::warning::/);
    } finally {
      limpar();
    }
  }
});
