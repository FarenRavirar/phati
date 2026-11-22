#!/usr/bin/env node
// branch-gate — PreToolUse(Bash): NEGA `git commit` feito em branch fora da regra do AGENTS.md §Git.
//
// Regras, nesta ordem (a primeira que casa decide):
//   1. branch `dev` ou `main`: nada é commitado direto nelas.
//   2. nome fora de `^(feat|fix|chore|docs|infra)/[a-z0-9][a-z0-9._-]*$`.
//   3. HEAD é ancestral de origin/dev e diferente dele: branch já mergeada, reuso proibido.
//
// Por que existe: o autorizacao-gate pergunta antes de cada commit, mas não sabe em
// qual branch o commit cai. Este hook barra o commit na branch errada antes de chegar
// ao prompt. Branch errada só aparece tarde, no PR.
//
// Técnica de detecção: a mesma do autorizacao-gate (normaliza o texto antes de casar),
// para pegar `rtk git commit`, caminho absoluto do git, flags -C/-c/--git-dir e a forma
// dentro de `bash -lc "..."`. Não importada: o autorizacao-gate não exporta o helper e
// rodar lerPayload no require o tornaria inútil como módulo.
//
// shortcut: a branch é lida no cwd do payload. `git -C <dir>` e `cd <dir> && git commit`
//   dentro do comando não são seguidos, então o commit pode cair em outra branch que a
//   medida. Upgrade: resolver o diretório do commit a partir do comando.
// shortcut: a regra 3 não detecta squash merge nem origin/dev desatualizado (exigiria
//   `git fetch` ou `gh`). Upgrade: consultar `gh pr list --state merged` quando houver rede.
//
// Falha aberta: payload ilegível, fora de repositório, HEAD destacado, sem origin/dev
// local e git com erro não negam. Um gate que derruba o turno sem motivo é desligado na
// primeira vez que atrapalha.
//
// `PHATI_GATE_BRANCH=0` desliga esta regra inteira (só o valor exato `0`).

'use strict';

const { spawnSync } = require('node:child_process');
const path = require('node:path');

const { lerPayload } = require(path.join(__dirname, 'ler-payload.js'));

const MOLDE = /^(feat|fix|chore|docs|infra)\/[a-z0-9][a-z0-9._-]*$/;
const BRANCHES_PROTEGIDAS = ['dev', 'main'];
const DICA = 'Crie branch nova: git fetch origin && git switch -c <tipo>/<escopo> --no-track origin/dev (mudanças não commitadas vão junto).';
const COMMIT = /(?:^|[;&|(`"'$]\s*)(?:rtk\s+)?git\s+commit\b/;

// Normaliza antes de casar. Argumento literal de echo/printf/rg/grep é dado, não
// execução, então sai do texto. Caminho absoluto do git e flags de configuração
// viram `git`, e aspas em volta do subcomando somem.
function normalizar(cmd) {
  return cmd
    .replace(/\b(?:echo|printf)\s+(['"])(?:(?!\1)[^$\\]|\\.)*\1/g, ' ')
    .replace(/\b(?:rg|grep|ag|ack|rtk\s+rg|rtk\s+grep)\s+(?:-\S+\s+)*(['"])(?:(?!\1)[^$\\]|\\.)*\1/g, ' ')
    .replace(/(^|[\s;&|(`$"'])(?:\/[\w.\-/]*\/)?(?=git\b)/g, '$1')
    .replace(/\bgit(?:\s+-(?:C|c|-git-dir|-work-tree|-namespace|-exec-path)(?:=\S+|\s+\S+))+/g, 'git')
    .replace(/(^|\s)(['"])([\w-]+)\2/g, '$1$3');
}

// Retorna { status, out }. status -1 quando o binário nem roda (git ausente).
function git(cwd, args) {
  const r = spawnSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
  return { status: r.error ? -1 : r.status, out: (r.stdout || '').trim() };
}

function negar(regra, motivo) {
  return { regra, motivo };
}

function decidir(comando, cwd, ambiente) {
  if (ambiente.PHATI_GATE_BRANCH === '0') return null;
  if (!COMMIT.test(normalizar(comando))) return null;

  const dir = cwd || process.cwd();

  // symbolic-ref (e não rev-parse --abbrev-ref) porque funciona em branch sem commit
  // ainda; detached HEAD sai com status 1 e passa por falha aberta.
  const ramo = git(dir, ['symbolic-ref', '--short', '-q', 'HEAD']);
  if (ramo.status !== 0 || !ramo.out) return null;
  const nome = ramo.out;

  if (BRANCHES_PROTEGIDAS.includes(nome)) {
    return negar('protegida', `Commit direto em ${nome} é proibido (AGENTS.md §Git). ${DICA}`);
  }
  if (!MOLDE.test(nome)) {
    return negar('nome', `Branch ${nome} fora do molde <tipo>/<escopo> (feat, fix, chore, docs, infra). ${DICA}`);
  }

  // shortcut: sem origin/dev local a checagem de mergeada não roda (ver cabeçalho).
  const dev = git(dir, ['rev-parse', '--verify', '--quiet', 'refs/remotes/origin/dev']);
  if (dev.status !== 0) return null;
  const head = git(dir, ['rev-parse', 'HEAD']);
  if (head.status !== 0 || head.out === dev.out) return null;
  // --is-ancestor: status 0 = é ancestral; 1 = não é; outro = erro. Só o 0 nega.
  const ancestral = git(dir, ['merge-base', '--is-ancestor', 'HEAD', 'origin/dev']);
  if (ancestral.status !== 0) return null;
  return negar('mergeada', `Branch ${nome} já foi mergeada em dev. ${DICA}`);
}

lerPayload((raw) => {
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    process.exit(0); // payload ilegível nunca bloqueia trabalho
  }
  const comando = payload?.tool_input?.command ?? '';
  if (!comando) process.exit(0);

  const veredito = decidir(comando, payload.cwd, process.env);
  if (veredito) {
    console.log(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason: `[branch-gate/${veredito.regra}] ${veredito.motivo}`,
      },
    }));
  }
  process.exit(0);
});
