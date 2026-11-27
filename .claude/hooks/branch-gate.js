#!/usr/bin/env node
// branch-gate — PreToolUse(Bash): NEGA `git commit` feito em branch fora da regra do AGENTS.md §Git.
//
// Alvo de cada commit: o repositório que o próprio comando escolhe (cwd do payload, `cd`,
// `git -C`, `--git-dir`, `--work-tree`). A análise do shell é do shell-analise.js, compartilhado
// com o autorizacao-gate. Alvo que não se determina (variável, substituição, `cd -`, diretório
// que pode nascer no próprio comando) nega quando há commit. Vários commits: nega se qualquer um negar.
//
// Regras, por commit (a primeira que casa decide):
//   0. alvo indeterminado: nega (fail closed). Profundidade além do limite também nega.
//   1. branch `dev` ou `main` do repositório-alvo: nada é commitado direto nelas.
//   2. nome fora de `^(feat|fix|chore|docs|infra)/[a-z0-9][a-z0-9._-]*$`.
//   3. HEAD é ancestral de origin/dev e diferente dele: branch já mergeada, reuso proibido.
//   4. phati-specs: o repositório para onde aponta o symlink `specs` da raiz do projeto
//      (CLAUDE_PROJECT_DIR, ou derivado de __dirname; sem caminho fixo). Só `main`, e o commit
//      exige o prefixo inline `PHATI_GATE_BRANCH=0` e identidade git. Sem o prefixo nega e
//      mostra o comando pronto; o prefixo vale só para este repositório. A autorização do
//      mantenedor continua sendo pedida pelo autorizacao-gate, por ação.
//   5. o mesmo comando troca de ramo ou de refs (switch, checkout, reset, merge...) antes do
//      commit: o ramo que o commit verá não é o lido agora. Nega.
//
// Por que existe: o autorizacao-gate pergunta antes de cada commit, mas não sabe em
// qual branch o commit cai. Este hook barra o commit na branch errada antes de chegar
// ao prompt. Branch errada só aparece tarde, no PR.
//
// shortcut: a regra 3 não detecta squash merge nem origin/dev desatualizado (exigiria
//   `git fetch` ou `gh`). Upgrade: consultar `gh pr list --state merged` quando houver rede.
// shortcut: troca de ramo em OUTRA chamada do Bash, entre a leitura deste hook e o commit, não
//   é vista: PreToolUse não é atômico. Upgrade: pre-commit no próprio phati-specs conferindo ramo.
//
// Falha aberta: payload ilegível, fora de repositório, HEAD destacado, sem origin/dev local e git com erro não negam.
// Exceção: alvo com --git-dir/--work-tree que não se lê como repositório nega, porque o commit
// iria para um lugar que o hook não confere.
//
// `PHATI_GATE_BRANCH=0` no ambiente do processo desliga esta regra inteira (só o valor exato `0`).
// Como prefixo inline do comando, vale só para o commit no phati-specs (regra 4).

'use strict';

const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const path = require('node:path');

const { lerPayload } = require(path.join(__dirname, 'ler-payload.js'));
const { percorrer, desmontarGit, resolverDir } = require(path.join(__dirname, 'shell-analise.js'));

const MOLDE = /^(feat|fix|chore|docs|infra)\/[a-z0-9][a-z0-9._-]*$/;
const BRANCHES_PROTEGIDAS = ['dev', 'main'];
const DICA = 'Crie branch nova: git fetch origin && git switch -c <tipo>/<escopo> --no-track origin/dev (mudanças não commitadas vão junto).';
const PREFIXO_SPECS = 'PHATI_GATE_BRANCH=0';
// Subcomandos que trocam o HEAD ou as refs: o ramo que um commit seguinte verá muda.
const MUDA_RAMO = new Set(['switch', 'checkout', 'reset', 'rebase', 'pull', 'cherry-pick', 'revert',
  'am', 'merge', 'update-ref', 'symbolic-ref', 'branch']);

function negar(regra, motivo) {
  return { regra, motivo };
}

// Aspas simples no valor, com a aspa interna escapada: o comando sugerido é copiado para o shell.
const shq = (s) => `'${s.replace(/'/g, "'\\''")}'`;

// Roda git no repositório-alvo, com os mesmos --git-dir/--work-tree do comando avaliado.
// Retorna { status, out }. status -1 quando o binário nem roda (git ausente).
function git(alvo, args) {
  const extra = [];
  if (alvo.gitDir) extra.push(`--git-dir=${alvo.gitDir}`);
  if (alvo.workTree) extra.push(`--work-tree=${alvo.workTree}`);
  const r = spawnSync('git', [...extra, ...args], { cwd: alvo.dir, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
  return { status: r.error ? -1 : r.status, out: (r.stdout || '').trim() };
}

function configurado(alvo, chave) {
  const r = git(alvo, ['config', '--get', chave]);
  return r.status === 0 && r.out !== '';
}

// Raiz real do repositório do alvo, ou null (fora de repositório ou diretório inexistente).
function raizDoAlvo(alvo) {
  const r = git(alvo, ['rev-parse', '--show-toplevel']);
  if (r.status !== 0 || !r.out) return null;
  try {
    return fs.realpathSync(r.out);
  } catch {
    return null;
  }
}

// phati-specs: repositório para onde aponta o symlink `specs` da raiz do projeto. Descoberto em
// tempo de execução. Sem o symlink, ou sem repositório atrás dele: null.
function infoSpecs(ambiente) {
  const raizProjeto = ambiente.CLAUDE_PROJECT_DIR || path.resolve(__dirname, '..', '..');
  let real;
  try {
    real = fs.realpathSync(path.join(raizProjeto, 'specs'));
  } catch {
    return null;
  }
  const top = raizDoAlvo({ dir: real, gitDir: null, workTree: null });
  return top ? { top } : null;
}

// Identidade efetiva: config do repositório, `-c` do próprio commit, ou o par GIT_AUTHOR_* +
// GIT_COMMITTER_* do ambiente (processo ou prefixo inline).
function temIdentidade(alvo, ambiente) {
  const env = { ...ambiente, ...alvo.prefixo };
  return {
    nome: !!alvo.cfg['user.name'] || configurado(alvo, 'user.name')
      || (!!env.GIT_AUTHOR_NAME && !!env.GIT_COMMITTER_NAME),
    email: !!alvo.cfg['user.email'] || configurado(alvo, 'user.email')
      || (!!env.GIT_AUTHOR_EMAIL && !!env.GIT_COMMITTER_EMAIL),
  };
}

// Comando pronto para o mantenedor copiar: caminho absoluto entre aspas, identidade que falta
// como `-c` (com nome e e-mail do último commit do próprio phati-specs) e heredoc para a mensagem.
function comandoPronto(specs, alvo, tem) {
  const r = git(alvo, ['log', '-1', '--format=%an%x1f%ae']);
  const [nome, email] = r.status === 0 && r.out ? r.out.split('\x1f') : [];
  const cfg = [];
  if (!tem.nome) cfg.push(`-c ${shq(`user.name=${nome || '<nome>'}`)}`);
  if (!tem.email) cfg.push(`-c ${shq(`user.email=${email || '<email>'}`)}`);
  const opcoes = cfg.map((c) => ` ${c}`).join('');
  return `${PREFIXO_SPECS} git -C ${shq(specs.top)}${opcoes} commit -F - <<'FIM'\n<mensagem do commit>\nFIM`;
}

function decidirSpecs(alvo, ctx) {
  const ramo = git(alvo, ['symbolic-ref', '--short', '-q', 'HEAD']);
  // HEAD destacado: falha aberta, como nos outros repositórios.
  if (ramo.status !== 0 || !ramo.out) return null;
  if (ramo.out !== 'main') {
    return negar('specs-branch', `phati-specs trabalha só em main (AGENTS.md §Git): branch ${ramo.out} não recebe commit.`);
  }
  const tem = temIdentidade(alvo, ctx.ambiente);
  if (alvo.prefixo.PHATI_GATE_BRANCH !== '0') {
    return negar('specs-sem-parametro', `Commit no phati-specs exige o prefixo inline do hook. Comando pronto: ${comandoPronto(ctx.specs, alvo, tem)}. Exige autorização do mantenedor, por ação.`);
  }
  if (!tem.nome || !tem.email) {
    return negar('specs-identidade', `Commit no phati-specs sem identidade git (user.name/user.email). Comando pronto: ${comandoPronto(ctx.specs, alvo, tem)}. Exige autorização do mantenedor, por ação.`);
  }
  return null;
}

function decidirBranch(alvo) {
  // symbolic-ref (e não rev-parse --abbrev-ref) porque funciona em branch sem commit
  // ainda; detached HEAD sai com status 1 e passa por falha aberta.
  const ramo = git(alvo, ['symbolic-ref', '--short', '-q', 'HEAD']);
  if (ramo.status !== 0 || !ramo.out) return null;
  const nome = ramo.out;

  if (BRANCHES_PROTEGIDAS.includes(nome)) {
    return negar('protegida', `Commit direto em ${nome} é proibido (AGENTS.md §Git). ${DICA}`);
  }
  if (!MOLDE.test(nome)) {
    return negar('nome', `Branch ${nome} fora do molde <tipo>/<escopo> (feat, fix, chore, docs, infra). ${DICA}`);
  }

  // shortcut: sem origin/dev local a checagem de mergeada não roda (ver cabeçalho).
  const dev = git(alvo, ['rev-parse', '--verify', '--quiet', 'refs/remotes/origin/dev']);
  if (dev.status !== 0) return null;
  const head = git(alvo, ['rev-parse', 'HEAD']);
  if (head.status !== 0 || head.out === dev.out) return null;
  // --is-ancestor: status 0 = é ancestral; 1 = não é; outro = erro. Só o 0 nega.
  const ancestral = git(alvo, ['merge-base', '--is-ancestor', 'HEAD', 'origin/dev']);
  if (ancestral.status !== 0) return null;
  return negar('mergeada', `Branch ${nome} já foi mergeada em dev. ${DICA}`);
}

function decidirCommit(alvo, ctx) {
  const top = raizDoAlvo(alvo);
  if (!top) {
    // Fora de repositório: falha aberta. Com --git-dir/--work-tree explícito, o commit iria
    // para um alvo que o hook não consegue ler: nega.
    if (alvo.gitDir || alvo.workTree) {
      return negar('alvo-indeterminado', `git --git-dir/--work-tree aponta para ${alvo.gitDir || alvo.workTree}, que o hook não lê como repositório.`);
    }
    return null;
  }
  if (ctx.specs && top === ctx.specs.top) return decidirSpecs(alvo, ctx);
  return decidirBranch(alvo);
}

// Alvo de um commit: diretório-base (cwd candidato) mais as opções globais do git. `null` em
// qualquer ponto = não determinável (variável, substituição, cwd desconhecido).
function alvoDoCommit(globais, base, prefixo) {
  const alvo = { dir: base, gitDir: null, workTree: null, cfg: {}, prefixo, indeterminado: base === null };
  const resolve = (valor) => {
    const r = resolverDir(valor, alvo.dir);
    if (r === null) alvo.indeterminado = true;
    return r;
  };
  for (const gl of globais) {
    if (gl.opcao === '-C') {
      alvo.dir = resolve(gl.valor);
    } else if (gl.opcao === '-c') {
      const kv = gl.valor.v;
      const eq = kv.indexOf('=');
      alvo.cfg[eq === -1 ? kv : kv.slice(0, eq)] = eq === -1 ? '' : kv.slice(eq + 1);
    } else if (gl.opcao === '--git-dir') {
      alvo.gitDir = resolve(gl.valor);
    } else if (gl.opcao === '--work-tree') {
      alvo.workTree = resolve(gl.valor);
    }
  }
  return alvo;
}

// Commits do comando (com alvo) e se algum subcomando troca de ramo ou refs.
function coletar(comando, raiz) {
  const achados = [];
  let mudaRamo = false;
  percorrer(comando, [raiz], (cmd) => {
    if (cmd.profundidade) {
      // Além do limite não há como ler o comando: nega se o texto mencionar git ou commit.
      if (/git|commit/.test(cmd.texto)) achados.push({ profundidade: true });
      return;
    }
    if (cmd.nome !== 'git') return;
    const g = desmontarGit(cmd.palavras);
    if (MUDA_RAMO.has(g.sub)) mudaRamo = true;
    if (g.sub !== 'commit') return;
    for (const base of cmd.cwds) achados.push(alvoDoCommit(g.globais, base, cmd.prefixo));
  });
  return { achados, mudaRamo };
}

function decidir(comando, cwd, ambiente) {
  if (ambiente.PHATI_GATE_BRANCH === '0') return null;
  const { achados, mudaRamo } = coletar(comando, cwd || process.cwd());
  if (!achados.length) return null;
  const ctx = { ambiente, specs: infoSpecs(ambiente) };
  for (const alvo of achados) {
    if (alvo.profundidade) {
      return negar('profundidade', 'Comando aninhado além do limite de análise do hook, com git ou commit dentro. Rode o commit em um comando simples.');
    }
    if (alvo.indeterminado) {
      return negar('alvo-indeterminado', 'Commit com diretório que o hook não consegue determinar (variável, substituição, cd -, ou cd para diretório que pode ser criado no próprio comando). Use caminho literal em git -C.');
    }
    const veredito = decidirCommit(alvo, ctx);
    if (veredito) return veredito;
  }
  if (mudaRamo) {
    return negar('ramo-muda-no-comando', 'O mesmo comando troca de ramo ou de refs (switch, checkout, reset, merge...) antes do commit, e o ramo que o commit verá não é o lido agora. Separe a troca e o commit em comandos diferentes, cada um com a branch conferida.');
  }
  return null;
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
