#!/usr/bin/env node
// branch-gate — PreToolUse(Bash): NEGA `git commit` feito em branch fora da regra do AGENTS.md §Git.
//
// Alvo de cada commit: o repositório que o próprio comando escolhe. Parte do cwd do payload
// e segue `cd <dir> &&` e `git -C <dir>` encadeados (relativos ao cwd atual). `bash -c "..."`
// e `$(...)`/crase são analisados por dentro. Diretório não resolvível (variável) cai no cwd
// do payload. Vários commits no comando: nega se qualquer um negar.
//
// Regras, por commit (a primeira que casa decide):
//   1. branch `dev` ou `main` do repositório-alvo: nada é commitado direto nelas.
//   2. nome fora de `^(feat|fix|chore|docs|infra)/[a-z0-9][a-z0-9._-]*$`.
//   3. HEAD é ancestral de origin/dev e diferente dele: branch já mergeada, reuso proibido.
//   4. phati-specs: o repositório para onde aponta o symlink `specs` da raiz do projeto
//      (CLAUDE_PROJECT_DIR, ou derivado de __dirname; sem caminho fixo). Só `main`, e o commit
//      exige o prefixo inline `PHATI_GATE_BRANCH=0` e identidade git. Sem o prefixo nega e
//      mostra o comando pronto; o prefixo vale só para este repositório. A autorização do
//      mantenedor continua sendo pedida pelo autorizacao-gate, por ação.
//
// Por que existe: o autorizacao-gate pergunta antes de cada commit, mas não sabe em
// qual branch o commit cai. Este hook barra o commit na branch errada antes de chegar
// ao prompt. Branch errada só aparece tarde, no PR.
//
// Técnica: tokeniza o comando (aspas, separadores, substituições), em vez de casar texto.
// Assim `-c user.name='A B'`, `-C "dir com espaço"` e `echo "git commit"` (dado) saem certos.
// Não importa o autorizacao-gate: ele roda lerPayload no require e não exporta o helper.
//
// shortcut: diretório que é variável (`git -C "$X" commit`) é avaliado no cwd do payload; o
//   commit pode cair em outro repositório. Upgrade: resolver as variáveis do próprio comando.
// shortcut: a regra 3 não detecta squash merge nem origin/dev desatualizado (exigiria
//   `git fetch` ou `gh`). Upgrade: consultar `gh pr list --state merged` quando houver rede.
// shortcut: substituição `$(...)` é analisada com o cwd do fim do comando, não do ponto exato.
//
// Falha aberta: payload ilegível, fora de repositório, HEAD destacado, sem origin/dev
// local e git com erro não negam. Um gate que derruba o turno sem motivo é desligado na
// primeira vez que atrapalha.
//
// `PHATI_GATE_BRANCH=0` no ambiente do processo desliga esta regra inteira (só o valor exato `0`).
// Como prefixo inline do comando, vale só para o commit no phati-specs (regra 4).

'use strict';

const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const { lerPayload } = require(path.join(__dirname, 'ler-payload.js'));

const MOLDE = /^(feat|fix|chore|docs|infra)\/[a-z0-9][a-z0-9._-]*$/;
const BRANCHES_PROTEGIDAS = ['dev', 'main'];
const DICA = 'Crie branch nova: git fetch origin && git switch -c <tipo>/<escopo> --no-track origin/dev (mudanças não commitadas vão junto).';
const PREFIXO_SPECS = 'PHATI_GATE_BRANCH=0';
const PROFUNDIDADE_MAX = 4;
const SEPARADORES = new Set([';', '|', '&', '(', ')', '\n']);
// Palavras que só envolvem o comando (não são o comando): `rtk git`, `env X=1 git`.
const ATALHOS = new Set(['rtk', 'bypass', 'env', 'command']);
const SHELLS = new Set(['bash', 'sh', 'zsh']);
const GLOBAIS_COM_VALOR = new Set(['--git-dir', '--work-tree', '--namespace', '--exec-path']);

// Corta o texto em segmentos (separados por ; | & ( ) e quebra de linha) e cada segmento em
// palavras, sem aspas. Substituições `$(...)` e crases viram textos à parte, para análise
// recursiva. `dinamica` marca palavra com `$` ou substituição: o valor não se conhece aqui.
function tokenizar(texto) {
  const segmentos = [];
  const subs = [];
  let seg = [];
  let pal = null;
  let dinamica = false;
  const fimPal = () => {
    if (pal !== null) seg.push({ valor: pal, dinamica });
    pal = null;
    dinamica = false;
  };
  const fimSeg = () => {
    fimPal();
    if (seg.length) segmentos.push(seg);
    seg = [];
  };
  const add = (t) => {
    pal = (pal ?? '') + t;
  };
  // i aponta logo após a abertura. Devolve o índice logo após o fechamento.
  const lerSub = (i, crase) => {
    let prof = 1;
    let j = i;
    for (; j < texto.length; j++) {
      const ch = texto[j];
      if (crase) {
        if (ch === '`') break;
      } else if (ch === '(') {
        prof++;
      } else if (ch === ')' && --prof === 0) {
        break;
      }
    }
    subs.push(texto.slice(i, j));
    pal = pal ?? '';
    dinamica = true;
    return j + 1;
  };

  let i = 0;
  while (i < texto.length) {
    const c = texto[i];
    if (c === "'") {
      const fim = texto.indexOf("'", i + 1);
      const ate = fim === -1 ? texto.length : fim;
      add(texto.slice(i + 1, ate));
      i = ate + 1;
    } else if (c === '"') {
      pal = pal ?? '';
      i++;
      while (i < texto.length && texto[i] !== '"') {
        const d = texto[i];
        if (d === '\\' && i + 1 < texto.length) {
          add(texto[i + 1]);
          i += 2;
        } else if (d === '$' && texto[i + 1] === '(') {
          i = lerSub(i + 2, false);
        } else if (d === '`') {
          i = lerSub(i + 1, true);
        } else {
          if (d === '$') dinamica = true;
          add(d);
          i++;
        }
      }
      i++;
    } else if (c === '\\') {
      if (i + 1 < texto.length) add(texto[i + 1]);
      i += 2;
    } else if (c === '$' && texto[i + 1] === '(') {
      i = lerSub(i + 2, false);
    } else if (c === '`') {
      i = lerSub(i + 1, true);
    } else if (c === ' ' || c === '\t') {
      fimPal();
      i++;
    } else if (SEPARADORES.has(c)) {
      fimSeg();
      i++;
    } else {
      if (c === '$') dinamica = true;
      add(c);
      i++;
    }
  }
  fimSeg();
  return { segmentos, subs };
}

const ehAtribuicao = (v) => /^[A-Za-z_]\w*=/.test(v);

// Lista de commits do comando: { dir, cfg, prefixo }. `dir` é o repositório-alvo (absoluto).
// `cfg` são os `-c chave=valor` do próprio commit; `prefixo` são as atribuições inline
// (`PHATI_GATE_BRANCH=0 git ...`), que valem só para aquele segmento.
function commitsDo(texto, raiz, profund = 0) {
  if (profund > PROFUNDIDADE_MAX) return [];
  const { segmentos, subs } = tokenizar(texto);
  const achados = [];
  let cwd = raiz;
  // Diretório de palavra: variável cai no cwd do payload (regra: não resolvível avalia o cwd).
  const resolver = (p, base) => {
    if (p.dinamica) return raiz;
    const v = p.valor === '~' || p.valor.startsWith('~/') ? os.homedir() + p.valor.slice(1) : p.valor;
    return path.resolve(base, v);
  };

  for (const seg of segmentos) {
    const prefixo = {};
    let k = 0;
    for (;;) {
      const v = seg[k]?.valor;
      if (v === undefined) break;
      if (ehAtribuicao(v)) {
        const eq = v.indexOf('=');
        prefixo[v.slice(0, eq)] = v.slice(eq + 1);
        k++;
      } else if (ATALHOS.has(v)) {
        k++;
      } else {
        break;
      }
    }
    if (k >= seg.length) continue;

    const primeiro = seg[k].valor;
    if (primeiro === 'cd') {
      cwd = seg[k + 1] ? resolver(seg[k + 1], cwd) : os.homedir();
      continue;
    }
    if (SHELLS.has(path.basename(primeiro))) {
      const idx = seg.findIndex((t, j) => j > k && /^-\w*c\w*$/.test(t.valor));
      if (idx !== -1 && seg[idx + 1]) achados.push(...commitsDo(seg[idx + 1].valor, cwd, profund + 1));
      continue;
    }
    if (path.basename(primeiro) !== 'git') continue;

    let dir = cwd;
    const cfg = {};
    let j = k + 1;
    for (;;) {
      const t = seg[j]?.valor;
      if (t === '-C' && seg[j + 1]) {
        dir = resolver(seg[j + 1], dir);
        j += 2;
      } else if (t === '-c' && seg[j + 1]) {
        const kv = seg[j + 1].valor;
        const eq = kv.indexOf('=');
        cfg[eq === -1 ? kv : kv.slice(0, eq)] = eq === -1 ? '' : kv.slice(eq + 1);
        j += 2;
      } else if (GLOBAIS_COM_VALOR.has(t) && seg[j + 1]) {
        j += 2;
      } else if (/^--(git-dir|work-tree|namespace|exec-path)=/.test(t ?? '')) {
        j++;
      } else {
        break;
      }
    }
    if (seg[j]?.valor === 'commit') achados.push({ dir, cfg, prefixo });
  }
  for (const s of subs) achados.push(...commitsDo(s, cwd, profund + 1));
  return achados;
}

// Retorna { status, out }. status -1 quando o binário nem roda (git ausente).
function git(cwd, args) {
  const r = spawnSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
  return { status: r.error ? -1 : r.status, out: (r.stdout || '').trim() };
}

function configurado(dir, chave) {
  const r = git(dir, ['config', '--get', chave]);
  return r.status === 0 && r.out !== '';
}

// Raiz real do repositório que contém `dir`, ou null (fora de repositório ou diretório inexistente).
function raizRepo(dir) {
  const r = git(dir, ['rev-parse', '--show-toplevel']);
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
  const top = raizRepo(real);
  if (!top) return null;
  return { top, rel: path.relative(raizProjeto, top) || '.' };
}

function negar(regra, motivo) {
  return { regra, motivo };
}

// Identidade efetiva: config do repositório, `-c` do próprio commit, ou o par GIT_AUTHOR_* +
// GIT_COMMITTER_* do ambiente (processo ou prefixo inline).
function temIdentidade(commit, dir, ambiente) {
  const env = { ...ambiente, ...commit.prefixo };
  return {
    nome: !!commit.cfg['user.name'] || configurado(dir, 'user.name')
      || (!!env.GIT_AUTHOR_NAME && !!env.GIT_COMMITTER_NAME),
    email: !!commit.cfg['user.email'] || configurado(dir, 'user.email')
      || (!!env.GIT_AUTHOR_EMAIL && !!env.GIT_COMMITTER_EMAIL),
  };
}

// Comando pronto para o mantenedor copiar. Identidade que falta vira `-c`, com nome e e-mail
// do último commit do próprio phati-specs.
function comandoPronto(specs, dir, tem) {
  const r = git(dir, ['log', '-1', '--format=%an%x1f%ae']);
  const [nome, email] = r.status === 0 && r.out ? r.out.split('\x1f') : [];
  const cfg = [];
  if (!tem.nome) cfg.push(`-c user.name='${nome || '<nome>'}'`);
  if (!tem.email) cfg.push(`-c user.email='${email || '<email>'}'`);
  return [`${PREFIXO_SPECS} git -C ${specs.rel}`, ...cfg, 'commit -F -'].join(' ');
}

function decidirSpecs(commit, ctx) {
  const ramo = git(commit.dir, ['symbolic-ref', '--short', '-q', 'HEAD']);
  // HEAD destacado: falha aberta, como nos outros repositórios.
  if (ramo.status !== 0 || !ramo.out) return null;
  if (ramo.out !== 'main') {
    return negar('specs-branch', `phati-specs trabalha só em main (AGENTS.md §Git): branch ${ramo.out} não recebe commit.`);
  }
  const tem = temIdentidade(commit, commit.dir, ctx.ambiente);
  if (commit.prefixo.PHATI_GATE_BRANCH !== '0') {
    return negar('specs-sem-parametro', `Commit no phati-specs exige o prefixo inline do hook. Comando pronto: ${comandoPronto(ctx.specs, commit.dir, tem)}. Exige autorização do mantenedor, por ação.`);
  }
  if (!tem.nome || !tem.email) {
    return negar('specs-identidade', `Commit no phati-specs sem identidade git (user.name/user.email). Comando pronto: ${comandoPronto(ctx.specs, commit.dir, tem)}. Exige autorização do mantenedor, por ação.`);
  }
  return null;
}

function decidirBranch(dir) {
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

function decidirCommit(commit, ctx) {
  const top = raizRepo(commit.dir);
  if (!top) return null; // fora de repositório: falha aberta
  if (ctx.specs && top === ctx.specs.top) return decidirSpecs(commit, ctx);
  return decidirBranch(commit.dir);
}

function decidir(comando, cwd, ambiente) {
  if (ambiente.PHATI_GATE_BRANCH === '0') return null;
  const raiz = cwd || process.cwd();
  const commits = commitsDo(comando, raiz);
  if (!commits.length) return null;
  const ctx = { ambiente, specs: infoSpecs(ambiente) };
  for (const commit of commits) {
    const veredito = decidirCommit(commit, ctx);
    if (veredito) return veredito;
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
