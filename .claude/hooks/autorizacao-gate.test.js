#!/usr/bin/env node
// Suite do autorizacao-gate.
//
// Metade negativa e obrigatoria: um gate que bloqueia trabalho legitimo e
// desligado na primeira vez que atrapalha, e ai nao protege mais nada. Os casos
// read-only abaixo existem porque o AGENTS.md declara read-only SEMPRE permitido
// como regra petrea — se um deles falhar, o hook esta errado, nao o teste.

'use strict';

const { execFileSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test, after } = require('node:test');
const assert = require('node:assert/strict');

const HOOK = path.join(__dirname, 'autorizacao-gate.js');

// `ambiente` sobrepõe o do processo; sem `PHATI_GATE_WORKTREE` explícita, a variável sai do ambiente do filho
// (o teste não herda a configuração da máquina de quem roda). `cwd` vai no payload, como o Claude Code faz.
function rodar(command, ambiente = {}, cwd) {
  const env = { ...process.env, ...ambiente };
  if (!('PHATI_GATE_WORKTREE' in ambiente)) delete env.PHATI_GATE_WORKTREE;
  const saida = execFileSync('node', [HOOK], {
    input: JSON.stringify({
      hook_event_name: 'PreToolUse',
      tool_name: 'Bash',
      cwd,
      tool_input: { command },
    }),
    encoding: 'utf8',
    env,
  });
  if (!saida.trim()) return null;
  return JSON.parse(saida).hookSpecificOutput;
}

// [comando, regra esperada ou null se deve passar]
const CASOS = [
  // --- BLOQUEIA: forma direta ---
  ['git commit -m "x"', 'commit-sem-autorizacao'],
  ['git commit -F - <<EOF', 'commit-sem-autorizacao'],
  ['rtk git commit -F msg.txt', 'commit-sem-autorizacao'],
  ['git commit --amend', 'amend-proibido'],
  ['git push --force origin dev', 'push-force'],
  ['git push -f origin dev', 'push-force'],
  ['sudo apt-get install jq', 'pacote-novo'],
  ['apt install tree', 'pacote-novo'],
  ['shutdown -h now', 'vm-desligamento'],
  ['sudo reboot', 'vm-desligamento'],
  ['ssh maruko sudo poweroff', 'vm-desligamento'],
  ['systemctl reboot', 'vm-desligamento'],

  // --- BLOQUEIA: evasoes que as regras declarativas NAO pegam ---
  // Sao a razao de este hook existir; cada uma foi medida escapando em 2026-09-10.
  ['/usr/bin/git commit -m "x"', 'commit-sem-autorizacao'],
  ['git -C . commit -m "x"', 'commit-sem-autorizacao'],
  ['git -c user.name=x commit -m "y"', 'commit-sem-autorizacao'],
  // Valor de -c ou -C com espaço entre aspas: a normalização antiga cortava no espaço
  // e o `commit` escapava. Medido como defeito antes da correção (2026-11-27).
  ["git -c user.name='A B' -c user.email=x commit -m y", 'commit-sem-autorizacao'],
  ['git -c user.name="A B" -c user.email=x commit -m y', 'commit-sem-autorizacao'],
  ["git -c 'user.name=A B' commit -m y", 'commit-sem-autorizacao'],
  ["git -C '../phati specs' commit -F -", 'commit-sem-autorizacao'],
  ['git -C "../phati specs" commit -F -', 'commit-sem-autorizacao'],
  // Prefixo de variável inline não tira o commit da pergunta.
  ['PHATI_GATE_BRANCH=0 git commit -m x', 'commit-sem-autorizacao'],
  ["PHATI_GATE_BRANCH=0 git -C ../phati-specs -c user.name='A B' commit -F -", 'commit-sem-autorizacao'],
  ["git -c user.name='A B' -c user.email=x commit --amend", 'amend-proibido'],
  ["git -c user.name='A B' -c user.email=x push --force origin feat/x", 'push-force'],
  ['git -C "../phati specs" push -f origin feat/x', 'push-force'],
  ['git --git-dir=/repo/.git commit -m "x"', 'commit-sem-autorizacao'],
  ["git 'commit' -m x", 'commit-sem-autorizacao'],
  ['bash -lc "cd /tmp && git commit -m x"', 'commit-sem-autorizacao'],
  ['echo "$(git commit -m x)"', 'commit-sem-autorizacao'],
  ['rtk git status && git commit -m x', 'commit-sem-autorizacao'],
  ['/usr/bin/git commit --amend', 'amend-proibido'],
  ['bash -lc "sudo apt-get install jq"', 'pacote-novo'],

  // --- PASSA: read-only, petreo no AGENTS.md ---
  ['rtk git status', null],
  ['rtk git diff AGENTS.md', null],
  ['rtk git log --oneline -5', null],
  ['git show HEAD', null],
  ['git worktree list', null],
  ['ssh maruko docker ps', null],
  ['ssh maruko docker logs site-prod-app', null],
  ['ssh maruko docker inspect site-prod-app', null],

  // --- PASSA: abrir PR sozinho nao empurra (o push e que pergunta) ---
  ['gh pr create --base dev --title x', null],
  ['git push origin feat/x', null],
  ['rtk git push -u origin feat/x', null],

  // --- PASSA: trabalho comum ---
  ['rtk rg "termo" servidor', null],
  ['rtk git fetch origin', null],
  ['node .claude/hooks/autorizacao-gate.test.js', null],
  ['python -m pytest -q', null],
  ['apt list --installed', null],

  // --- PASSA: dado, nao execucao ---
  // Achado da propria suite (2026-09-10): a primeira versao bloqueava estes,
  // porque testava o texto sem distinguir argumento literal de comando. Falso
  // positivo assim e o que faz um gate ser desligado — e ai ele nao protege
  // mais nada. A distincao dado-vs-execucao e a mesma que o destructive_command_guard
  // faz ("nao bloqueia grep 'rm -rf', bloqueia rm -rf /").
  ['echo "git commit e o assunto do texto"', null],
  ["echo 'rode git worktree add depois'", null],
  ['rtk rg "git commit" docs', null],

  // --- BLOQUEIA: merge (git merge, gh pr merge), com prefixo rtk e dentro de shell ---
  ['git merge origin/dev', 'merge-sem-autorizacao'],
  ['rtk git merge origin/dev', 'merge-sem-autorizacao'],
  ['gh pr merge 78 --squash', 'merge-sem-autorizacao'],
  ['rtk gh pr merge 78', 'merge-sem-autorizacao'],
  ["bash -lc 'git merge x'", 'merge-sem-autorizacao'],
  ['sh -c "git merge x"', 'merge-sem-autorizacao'],
  ['/usr/bin/git merge origin/dev', 'merge-sem-autorizacao'],

  // --- PASSA: parecido com merge, mas não é merge ---
  ['git merge-base HEAD origin/dev', null],
  ['git log --merges --oneline', null],
  ['gh pr view 78', null],

  // --- BLOQUEIA: substituicao dentro de echo executa de verdade ---
  ['echo "$(git commit -m x)"', 'commit-sem-autorizacao'],

  // A variavel de desligamento antiga (PHATI_GATE_WORKTREE) nao muda mais nada:
  // com ela setada, commit, pacote e push seguem pedindo ou negando.
  ['git commit -m x', 'commit-sem-autorizacao', { PHATI_GATE_WORKTREE: '0' }],
  ['sudo apt install foo', 'pacote-novo', { PHATI_GATE_WORKTREE: '0' }],
  ['git push --force origin dev', 'push-force', { PHATI_GATE_WORKTREE: '0' }],
];

let ok = 0;
const falhas = [];

for (const [cmd, esperado, ambiente] of CASOS) {
  let obtido = null;
  try {
    const r = rodar(cmd, ambiente);
    obtido = r ? r.permissionDecisionReason.match(/\[autorizacao-gate\/([^\]]+)\]/)?.[1] : null;
  } catch (e) {
    falhas.push(`ERRO  ${cmd} -> ${e.message}`);
    continue;
  }
  if (obtido === esperado) {
    ok += 1;
  } else {
    falhas.push(`FALHA ${cmd}\n        esperado: ${esperado ?? '(passar)'}\n        obtido:   ${obtido ?? '(passou)'}`);
  }
}

// Qual DECISAO cada regra emite. Os casos acima verificam so QUAL regra casou,
// e foi por isso que o bug de 2026-09-10 passou: as 8 regras emitiam `deny`,
// inclusive as 5 que o AGENTS.md classifica como `ask`, e a suite ficou 48/48
// enquanto commitar era impossivel por este harness mesmo com autorizacao dada.
// Casar a regra certa nao prova nada se a decisao estiver errada.
const DECISOES = [
  ['sudo shutdown -h now', 'deny'],
  ['git commit --' + 'amend', 'deny'],
  ['git push --' + 'force origin dev', 'deny'],
  ['git commit -m x', 'ask'],
  ['rtk git commit -F m.txt', 'ask'],
  ['sudo apt install foo', 'ask'],
  ['git merge origin/dev', 'ask'],
  ['rtk gh pr merge 78', 'ask'],
  // Negativos de deny: desligar a VM e reescrever historico seguem negados por este hook.
  ['ssh maruko sudo poweroff', 'deny'],
  ['systemctl reboot', 'deny'],
  ['git push -f origin feat/x', 'deny'],
  // Regras removidas em 2026-11-22 (worktree e escrita na VM): passam sem decisao.
  ['git work' + 'tree add ../x', null],
  ['ssh maruko docker restart app', null],
];

// Config: o que o hook nao cobre (merge nao tem regra aqui) vem do `permissions` de
// .claude/settings.json. Checagem de presenca na lista, nao simulacao do casamento de
// wildcard do Claude Code: prova que a entrada existe, nao que casa o comando.
const PERMISSOES = JSON.parse(fs.readFileSync(path.join(__dirname, '..', 'settings.json'), 'utf8')).permissions;
const DEVE_PERGUNTAR = ['Bash(git commit:*)', 'Bash(git merge:*)', 'Bash(gh pr merge:*)'];
const DEVE_NEGAR = ['Bash(*commit --amend*)', 'Bash(*push --force*)', 'Bash(*ssh maruko*shutdown*)', 'Bash(*poweroff*)', 'Bash(*reboot*)'];
const total = CASOS.length + DECISOES.length + DEVE_PERGUNTAR.length + DEVE_NEGAR.length;

for (const [cmd, esperada] of DECISOES) {
  let obtida = null;
  try {
    const r = rodar(cmd);
    obtida = r ? r.permissionDecision : null;
  } catch (e) {
    falhas.push(`ERRO  decisao ${cmd} -> ${e.message}`);
    continue;
  }
  if (obtida === esperada) {
    ok += 1;
  } else {
    falhas.push(`FALHA decisao ${cmd}\n        esperada: ${esperada}\n        obtida:   ${obtida ?? '(passou sem decisao)'}`);
  }
}

for (const p of DEVE_PERGUNTAR) {
  if (PERMISSOES.ask.includes(p)) ok += 1;
  else falhas.push(`FALHA config: ask ausente  ${p}`);
}
for (const p of DEVE_NEGAR) {
  if (PERMISSOES.deny.includes(p)) ok += 1;
  else falhas.push(`FALHA config: deny ausente ${p}`);
}

console.log(`autorizacao-gate: ${ok}/${total} casos`);
if (falhas.length) {
  console.log(falhas.join('\n'));
  process.exit(1);
}

// --- Contexto do prompt de commit: branch atual e último commit ---
// Repositórios git temporários de verdade, como no branch-gate.test.js: mock reproduziria a leitura testada.
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

function git(cwd, ...args) {
  return execFileSync('git', ['-c', 'commit.gpgsign=false', ...args], {
    cwd,
    env: ENV_GIT,
    stdio: ['ignore', 'pipe', 'pipe'],
    encoding: 'utf8',
  }).trim();
}

// Repositório com um commit de assunto conhecido, já na branch pedida.
function repoComCommit(branch) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'autorizacao-gate-'));
  TMP.push(dir);
  git(dir, 'init', '-q');
  git(dir, 'symbolic-ref', 'HEAD', `refs/heads/${branch}`);
  git(dir, 'commit', '-q', '--allow-empty', '-m', 'assunto de teste');
  return dir;
}

const FRASE_CONFERENCIA = 'Confira se esta é a branch certa para este assunto antes de aprovar.';

test('commit em feat/x: ask mostra a branch, o último commit e a frase de conferência', () => {
  const dir = repoComCommit('feat/x');
  const hash = git(dir, 'log', '-1', '--format=%h');
  const r = rodar('git commit -m x', {}, dir);
  assert.equal(r.permissionDecision, 'ask');
  assert.match(r.permissionDecisionReason, /Branch atual: feat\/x\./);
  assert.ok(r.permissionDecisionReason.includes(`Último commit: ${hash} assunto de teste.`), r.permissionDecisionReason);
  assert.ok(r.permissionDecisionReason.includes(FRASE_CONFERENCIA), r.permissionDecisionReason);
});

test('HEAD destacado: ask continua com o aviso "branch não identificada"', () => {
  const dir = repoComCommit('dev');
  git(dir, 'checkout', '-q', '--detach');
  const r = rodar('git commit -m x', {}, dir);
  assert.equal(r.permissionDecision, 'ask');
  assert.ok(r.permissionDecisionReason.includes('branch não identificada'), r.permissionDecisionReason);
  assert.ok(r.permissionDecisionReason.includes(FRASE_CONFERENCIA));
});

test('cwd fora de repositório: ask sem exceção, com "branch não identificada"', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'autorizacao-gate-semrepo-'));
  TMP.push(dir);
  const r = rodar('git commit -m x', {}, dir);
  assert.equal(r.permissionDecision, 'ask');
  assert.ok(r.permissionDecisionReason.includes('branch não identificada'), r.permissionDecisionReason);
});

test('cwd inexistente: ask sem exceção (leitura de branch falha aberta)', () => {
  const inexistente = path.join(os.tmpdir(), 'autorizacao-gate-nao-existe-' + process.pid);
  const r = rodar('git commit -m x', {}, inexistente);
  assert.equal(r.permissionDecision, 'ask');
  assert.ok(r.permissionDecisionReason.includes('branch não identificada'), r.permissionDecisionReason);
});

test('comando que não é commit não recebe o aviso de branch', () => {
  const dir = repoComCommit('feat/x');
  assert.equal(rodar('rtk git status', {}, dir), null);
  const merge = rodar('git merge origin/dev', {}, dir);
  assert.equal(merge.permissionDecision, 'ask');
  assert.ok(!merge.permissionDecisionReason.includes(FRASE_CONFERENCIA), merge.permissionDecisionReason);
});

test('commit --amend continua deny, sem o aviso de branch', () => {
  const dir = repoComCommit('feat/x');
  const r = rodar('git commit --amend', {}, dir);
  assert.equal(r.permissionDecision, 'deny');
  assert.match(r.permissionDecisionReason, /\[autorizacao-gate\/amend-proibido\]/);
  assert.ok(!r.permissionDecisionReason.includes(FRASE_CONFERENCIA));
});
