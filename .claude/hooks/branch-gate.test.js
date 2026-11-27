#!/usr/bin/env node
// Suite do branch-gate. Repositórios git temporários de verdade: a regra depende de
// branch, de HEAD e de ancestralidade em relação a origin/dev, e mock aqui reproduziria
// a lógica testada. origin/dev é criado com `git update-ref`, como um fetch deixaria.
//
// Metade negativa é a maior: um gate que bloqueia commit legítimo é desligado na
// primeira vez que atrapalha.

'use strict';

const { test, after } = require('node:test');
const assert = require('node:assert/strict');
const { execFileSync, spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const HOOK = path.join(__dirname, 'branch-gate.js');
const TMP = [];

after(() => {
  for (const d of TMP) fs.rmSync(d, { recursive: true, force: true });
});

const ENV_GIT = {
  ...process.env,
  GIT_AUTHOR_NAME: 'teste',
  GIT_AUTHOR_EMAIL: 'teste@exemplo.invalid',
  GIT_COMMITTER_NAME: 'teste',
  GIT_COMMITTER_EMAIL: 'teste@exemplo.invalid',
};

// Projeto sem symlink `specs`: CLAUDE_PROJECT_DIR padrão dos testes, para o phati-specs real
// do ambiente de quem roda não interferir.
const SEM_SPECS = fs.mkdtempSync(path.join(os.tmpdir(), 'branch-gate-sem-specs-'));
TMP.push(SEM_SPECS);

function git(cwd, ...args) {
  return execFileSync('git', ['-c', 'commit.gpgsign=false', ...args], {
    cwd,
    env: ENV_GIT,
    stdio: ['ignore', 'pipe', 'pipe'],
    encoding: 'utf8',
  }).trim();
}

// Repositório com um commit na branch `base` (padrão dev). Sem origin/dev até pedir.
function repo(base = 'dev') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'branch-gate-'));
  TMP.push(dir);
  git(dir, 'init', '-q');
  git(dir, 'symbolic-ref', 'HEAD', `refs/heads/${base}`);
  git(dir, 'commit', '-q', '--allow-empty', '-m', 'base');
  return dir;
}

const commitVazio = (dir, msg = 'x') => git(dir, 'commit', '-q', '--allow-empty', '-m', msg);
const origemDev = (dir, ref = 'HEAD') => git(dir, 'update-ref', 'refs/remotes/origin/dev', ref);

// Repositório em feat/x, já à frente de origin/dev: branch válida para o cwd do payload.
function repoFeat() {
  const dir = repo('dev');
  origemDev(dir);
  git(dir, 'switch', '-q', '-c', 'feat/x');
  commitVazio(dir, 'trabalho');
  return dir;
}

// Repositório que faz o papel de phati-specs: branch `base` (padrão main) e identidade local.
function repoSpecs(base = 'main', comIdentidade = true) {
  const dir = repo(base);
  if (comIdentidade) {
    git(dir, 'config', 'user.name', 'Usuario Teste');
    git(dir, 'config', 'user.email', 'usuario@exemplo.invalid');
  }
  return dir;
}

// Projeto com o symlink `specs` apontando para dentro de `specsDir`, como o phati-dev aponta
// para o phati-specs (`specs -> ../phati-specs/specs`).
function projetoCom(specsDir) {
  const proj = fs.mkdtempSync(path.join(os.tmpdir(), 'branch-gate-proj-'));
  TMP.push(proj);
  const alvo = path.join(specsDir, 'specs');
  fs.mkdirSync(alvo, { recursive: true });
  fs.symlinkSync(alvo, path.join(proj, 'specs'));
  return proj;
}

// Roda o hook como o Claude Code faz: payload JSON no stdin, cwd no payload.
// Devolve { decisao, regra, motivo } ou null (passou). Falha se o hook sair != 0.
function rodar(comando, { cwd, ambiente = {}, raw } = {}) {
  const env = { ...process.env };
  for (const chave of ['PHATI_GATE_BRANCH', 'GIT_AUTHOR_NAME', 'GIT_AUTHOR_EMAIL', 'GIT_COMMITTER_NAME', 'GIT_COMMITTER_EMAIL']) {
    delete env[chave];
  }
  Object.assign(env, {
    CLAUDE_PROJECT_DIR: SEM_SPECS,
    GIT_CONFIG_GLOBAL: '/dev/null',
    GIT_CONFIG_NOSYSTEM: '1',
  }, ambiente);
  const entrada = raw ?? JSON.stringify({
    hook_event_name: 'PreToolUse',
    tool_name: 'Bash',
    cwd,
    tool_input: { command: comando },
  });
  const r = spawnSync('node', [HOOK], { input: entrada, encoding: 'utf8', env });
  assert.equal(r.status, 0, `hook saiu com ${r.status}: ${r.stderr}`);
  if (!r.stdout.trim()) return null;
  const saida = JSON.parse(r.stdout).hookSpecificOutput;
  return {
    decisao: saida.permissionDecision,
    regra: saida.permissionDecisionReason.match(/\[branch-gate\/([^\]]+)\]/)?.[1] ?? null,
    motivo: saida.permissionDecisionReason,
  };
}

function assertNegado(resultado, regra) {
  assert.ok(resultado, 'esperava deny, hook passou');
  assert.equal(resultado.decisao, 'deny');
  assert.equal(resultado.regra, regra);
  assert.match(resultado.motivo, /git switch -c <tipo>\/<escopo> --no-track origin\/dev/);
}

// --- BLOQUEIA ---

test('commit em dev nega (regra protegida)', () => {
  const dir = repo('dev');
  assertNegado(rodar('git commit -m x', { cwd: dir }), 'protegida');
});

test('commit em main nega (regra protegida)', () => {
  const dir = repo('main');
  assertNegado(rodar('git commit -m x', { cwd: dir }), 'protegida');
});

test('branch minha-branch fora do molde nega (regra nome)', () => {
  const dir = repo('dev');
  git(dir, 'switch', '-q', '-c', 'minha-branch');
  assertNegado(rodar('git commit -m x', { cwd: dir }), 'nome');
});

test('branch com maiúscula fora do molde nega (regra nome)', () => {
  const dir = repo('dev');
  origemDev(dir);
  git(dir, 'switch', '-q', '-c', 'feat/Maiuscula');
  commitVazio(dir, 'antes');
  assertNegado(rodar('git commit -m x', { cwd: dir }), 'nome');
});

test('branch já mergeada em origin/dev nega (regra mergeada)', () => {
  const dir = repo('dev');
  git(dir, 'switch', '-q', '-c', 'feat/x'); // HEAD = base
  git(dir, 'switch', '-q', 'dev');
  commitVazio(dir, 'avanca dev');
  origemDev(dir); // origin/dev está à frente de feat/x: feat/x é ancestral
  git(dir, 'switch', '-q', 'feat/x');
  assertNegado(rodar('git commit -m x', { cwd: dir }), 'mergeada');
});

test('forma rtk git commit -F - em dev nega', () => {
  const dir = repo('dev');
  assertNegado(rodar('rtk git commit -F -', { cwd: dir }), 'protegida');
});

test('bash -lc "cd ... && git commit" em dev nega', () => {
  const dir = repo('dev');
  assertNegado(rodar(`bash -lc "cd ${dir} && git commit -m x"`, { cwd: dir }), 'protegida');
});

test('caminho absoluto /usr/bin/git commit em dev nega', () => {
  const dir = repo('dev');
  assertNegado(rodar('/usr/bin/git commit -m x', { cwd: dir }), 'protegida');
});

test('git -C . commit em dev nega (flag antes do subcomando)', () => {
  const dir = repo('dev');
  assertNegado(rodar('git -C . commit -m x', { cwd: dir }), 'protegida');
});

test('cwd em feat/x: git -C de repositório em main que não é phati-specs nega', () => {
  const outro = repo('main');
  assertNegado(rodar(`git -C ${outro} commit -m x`, { cwd: repoFeat() }), 'protegida');
});

test('cwd em feat/x: cd para repositório em dev e commit nega', () => {
  const outro = repo('dev');
  assertNegado(rodar(`cd ${outro} && git commit -m x`, { cwd: repoFeat() }), 'protegida');
});

test('git -c user.name com espaço entre aspas em dev nega (a leitura não quebra)', () => {
  const dir = repo('dev');
  assertNegado(rodar("git -c user.name='A B' -c user.email=x commit -m x", { cwd: dir }), 'protegida');
});

test('diretório de variável não resolvível avalia o cwd: dev nega', () => {
  const dir = repo('dev');
  assertNegado(rodar('git -C "$ALVO" commit -m x', { cwd: dir }), 'protegida');
});

test('prefixo PHATI_GATE_BRANCH=0 inline não libera commit em main fora de phati-specs (git -C)', () => {
  const outro = repo('main');
  assertNegado(rodar(`PHATI_GATE_BRANCH=0 git -C ${outro} commit -m x`, { cwd: repoFeat() }), 'protegida');
});

test('prefixo PHATI_GATE_BRANCH=0 inline não libera commit em dev de repositório comum', () => {
  const dir = repo('dev');
  assertNegado(rodar('PHATI_GATE_BRANCH=0 git commit -m x', { cwd: dir }), 'protegida');
});

test('phati-specs sem prefixo nega com o comando pronto (cd e identidade já configurada)', () => {
  const specs = repoSpecs('main');
  const proj = projetoCom(specs);
  const r = rodar(`cd ${specs} && git commit -m x`, { cwd: repoFeat(), ambiente: { CLAUDE_PROJECT_DIR: proj } });
  assert.equal(r.decisao, 'deny');
  assert.equal(r.regra, 'specs-sem-parametro');
  const rel = path.relative(proj, specs);
  assert.ok(r.motivo.includes(`PHATI_GATE_BRANCH=0 git -C ${rel} commit -F -`), r.motivo);
  assert.ok(r.motivo.includes('autorização do mantenedor'), r.motivo);
});

test('git -C phati-specs sem prefixo nega mesmo com identidade (de cwd em dev)', () => {
  const specs = repoSpecs('main');
  const proj = projetoCom(specs);
  const r = rodar(`git -C ${specs} commit -m x`, { cwd: repo('dev'), ambiente: { CLAUDE_PROJECT_DIR: proj } });
  assert.equal(r.regra, 'specs-sem-parametro');
});

test('phati-specs fora de main nega mesmo com prefixo (regra specs-branch)', () => {
  const specs = repoSpecs('dev');
  const proj = projetoCom(specs);
  const r = rodar(`PHATI_GATE_BRANCH=0 git -C ${specs} commit -m x`, { cwd: repo('dev'), ambiente: { CLAUDE_PROJECT_DIR: proj } });
  assert.equal(r.decisao, 'deny');
  assert.equal(r.regra, 'specs-branch');
  assert.ok(r.motivo.includes('trabalha só em main'), r.motivo);
});

test('phati-specs em main com prefixo e sem identidade nega com -c no comando pronto', () => {
  const specs = repoSpecs('main', false);
  const proj = projetoCom(specs);
  const r = rodar(`PHATI_GATE_BRANCH=0 git -C ${specs} commit -m x`, { cwd: repo('dev'), ambiente: { CLAUDE_PROJECT_DIR: proj } });
  assert.equal(r.decisao, 'deny');
  assert.equal(r.regra, 'specs-identidade');
  assert.ok(r.motivo.includes("-c user.name='teste' -c user.email='teste@exemplo.invalid'"), r.motivo);
});

test('vários commits: phati-specs liberado e git commit em dev sem prefixo nega', () => {
  const specs = repoSpecs('main');
  const proj = projetoCom(specs);
  const r = rodar(`PHATI_GATE_BRANCH=0 git -C ${specs} commit -m a && git commit -m b`, {
    cwd: repo('dev'),
    ambiente: { CLAUDE_PROJECT_DIR: proj },
  });
  assertNegado(r, 'protegida');
});

test('commit de phati-specs com -c sem o prefixo ainda nega (o prefixo é o que libera)', () => {
  const specs = repoSpecs('main');
  const proj = projetoCom(specs);
  const r = rodar(`git -c user.name='A B' -C ${specs} commit -m x`, { cwd: repo('dev'), ambiente: { CLAUDE_PROJECT_DIR: proj } });
  assert.equal(r.regra, 'specs-sem-parametro');
});

// --- PASSA ---

test('feat/x à frente de origin/dev passa', () => {
  const dir = repo('dev');
  origemDev(dir);
  git(dir, 'switch', '-q', '-c', 'feat/x');
  commitVazio(dir, 'trabalho');
  assert.equal(rodar('git commit -m x', { cwd: dir }), null);
});

test('branch recém-criada sem commits, HEAD == origin/dev, passa', () => {
  const dir = repo('dev');
  origemDev(dir);
  git(dir, 'switch', '-q', '-c', 'feat/nova');
  assert.equal(rodar('git commit -m x', { cwd: dir }), null);
});

test('sem origin/dev local, branch com nome válido passa (falha aberta da regra mergeada)', () => {
  const dir = repo('dev');
  git(dir, 'switch', '-q', '-c', 'feat/x');
  commitVazio(dir, 'trabalho');
  assert.equal(rodar('git commit -m x', { cwd: dir }), null);
});

test('HEAD destacado passa, mesmo ancestral de origin/dev', () => {
  const dir = repo('dev');
  commitVazio(dir, 'avanca');
  origemDev(dir);
  git(dir, 'checkout', '-q', '--detach', 'HEAD~1'); // ancestral e diferente de origin/dev
  assert.equal(rodar('git commit -m x', { cwd: dir }), null);
});

test('comando que não é git commit passa, mesmo em dev', () => {
  const dir = repo('dev');
  assert.equal(rodar('rtk git status', { cwd: dir }), null);
  assert.equal(rodar('git log --oneline -3', { cwd: dir }), null);
});

test('echo com texto "git commit" passa, mesmo em dev (dado, não execução)', () => {
  const dir = repo('dev');
  assert.equal(rodar('echo "git commit é o assunto"', { cwd: dir }), null);
});

test('fora de repositório git passa (falha aberta)', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'branch-gate-semrepo-'));
  TMP.push(dir);
  assert.equal(rodar('git commit -m x', { cwd: dir }), null);
});

test('payload ilegível passa', () => {
  assert.equal(rodar('', { raw: 'não é json' }), null);
});

test('payload sem comando passa', () => {
  assert.equal(rodar('', { raw: JSON.stringify({ tool_input: {} }) }), null);
});

test('PHATI_GATE_BRANCH=0 desliga: commit em dev passa', () => {
  const dir = repo('dev');
  assert.equal(rodar('git commit -m x', { cwd: dir, ambiente: { PHATI_GATE_BRANCH: '0' } }), null);
});

test('PHATI_GATE_BRANCH=0 desliga: nome fora do molde passa', () => {
  const dir = repo('dev');
  git(dir, 'switch', '-q', '-c', 'minha-branch');
  assert.equal(rodar('git commit -m x', { cwd: dir, ambiente: { PHATI_GATE_BRANCH: '0' } }), null);
});

test('PHATI_GATE_BRANCH com valor diferente de 0 mantém a regra ativa', () => {
  const dir = repo('dev');
  assertNegado(rodar('git commit -m x', { cwd: dir, ambiente: { PHATI_GATE_BRANCH: '1' } }), 'protegida');
  assertNegado(rodar('git commit -m x', { cwd: dir, ambiente: { PHATI_GATE_BRANCH: '' } }), 'protegida');
});

test('phati-specs em main com prefixo e identidade passa, de cwd em dev (git -C)', () => {
  const specs = repoSpecs('main');
  const proj = projetoCom(specs);
  const r = rodar(`PHATI_GATE_BRANCH=0 git -C ${specs} commit -F -`, { cwd: repo('dev'), ambiente: { CLAUDE_PROJECT_DIR: proj } });
  assert.equal(r, null);
});

test('phati-specs em main com prefixo passa por cd, de cwd em feat/x', () => {
  const specs = repoSpecs('main');
  const proj = projetoCom(specs);
  const r = rodar(`cd ${specs} && PHATI_GATE_BRANCH=0 git commit -m x`, { cwd: repoFeat(), ambiente: { CLAUDE_PROJECT_DIR: proj } });
  assert.equal(r, null);
});

test("phati-specs com prefixo e -c user.name com espaço entre aspas passa", () => {
  const specs = repoSpecs('main', false);
  const proj = projetoCom(specs);
  const cmd = `PHATI_GATE_BRANCH=0 git -C ${specs} -c user.name='A B' -c user.email=x commit -F -`;
  assert.equal(rodar(cmd, { cwd: repo('dev'), ambiente: { CLAUDE_PROJECT_DIR: proj } }), null);
});

test('git -c user.name com espaço em feat/x passa (a leitura não cria falso negativo)', () => {
  assert.equal(rodar("git -c user.name='A B' -c user.email=x commit -m x", { cwd: repoFeat() }), null);
});

test('projeto sem symlink specs: prefixo inline não muda nada, repositório comum segue a regra', () => {
  const outro = repo('dev');
  assertNegado(rodar(`PHATI_GATE_BRANCH=0 git -C ${outro} commit -m x`, { cwd: repoFeat() }), 'protegida');
});
