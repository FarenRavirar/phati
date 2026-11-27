#!/usr/bin/env node
// Analisador de shell compartilhado pelo branch-gate e pelo autorizacao-gate.
//
// Por que existe: os dois hooks decidiam por texto cru (regex) ou cortavam o comando em
// separadores sem entender aspas, subshell, redirecionamento, heredoc e prefixos (sudo, env).
// Cada forma nova virava um furo. Aqui há um lexer, um analisador sintático e um percorredor;
// cada hook só decide sobre os comandos simples que o shell de fato executaria.
//
// Contrato: percorrer(texto, cwds, visitar) chama visitar para cada comando simples com
//   { nome, palavras, cwds, prefixo }
// `nome` é o executável real (sem sudo, env, rtk, palavras de controle e redirecionamentos);
// `palavras` são os argumentos `{ v, din }` (`din`: depende de variável ou substituição);
// `cwds` são os diretórios em que roda (`null` = não determinável); `prefixo` são as
// atribuições inline (`PHATI_GATE_BRANCH=0 git ...`).
// Profundidade além de PROFUNDIDADE_MAX chama visitar({ profundidade: true, texto }).
//
// shortcut: nome de comando vindo de variável ($CMD commit) não é analisado, e `bash script.sh`
//   não lê o script. Upgrade: negar quando o texto mencionar git ou quando o alvo for variável.
// shortcut: corpo de heredoc só é analisado quando o receptor é shell (`bash <<EOF`); heredoc
//   que chega a shell por pipe (`cat <<EOF | bash`) não é seguido.

'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const PROFUNDIDADE_MAX = 4;
const SHELLS = new Set(['bash', 'sh', 'zsh', 'dash', 'ksh', 'mksh', 'ash', 'fish']);
// Não executam o texto que recebem: o argumento é dado, não comando.
const DADO = new Set(['echo', 'printf', 'rg', 'grep', 'ag', 'ack']);
// Palavras que só envolvem o comando, sem opções: `rtk git`, `if git`, `! git`, `time git`.
const ENVOLTORIOS = new Set([
  'rtk', 'bypass', 'command', 'builtin', 'exec', 'nohup', 'time', '!', '{', '}',
  'if', 'then', 'else', 'elif', 'fi', 'do', 'done', 'while', 'until',
]);
const SUDO_COM_VALOR = new Set(['-u', '-g', '-C', '-h', '-p', '-r', '-t', '-T', '-U',
  '--user', '--group', '--close-from', '--host', '--prompt', '--role', '--type', '--other-user', '--chdir']);
const TIMEOUT_COM_VALOR = new Set(['-s', '--signal', '-k', '--kill-after']);
const GLOBAIS_GIT_COM_VALOR = new Set(['-C', '-c', '--git-dir', '--work-tree', '--namespace',
  '--exec-path', '--super-prefix', '--config-env']);
const ATRIBUICAO = /^[A-Za-z_]\w*=/;
const REDIRECIONAMENTO = /^(?:&>>|&>|<<<|<<-|<<|<&|<>|>>|>&|>\||>|<)/;

// Fim de substituição. Cada função recebe o índice logo após a abertura e devolve o índice
// do caractere de fechamento. Aspas e crases dentro da substituição são respeitadas: `)` entre
// aspas não fecha `$( )` (achado 9 do review).
function fimAspas(t, j) {
  for (; j < t.length; j++) {
    const c = t[j];
    if (c === '\\') j++;
    else if (c === '"') return j;
    else if (c === '$' && t[j + 1] === '(') j = fimSub(t, j + 2);
    else if (c === '`') j = fimCrase(t, j + 1);
  }
  return t.length;
}

function fimCrase(t, j) {
  for (; j < t.length; j++) {
    if (t[j] === '\\') j++;
    else if (t[j] === '`') return j;
  }
  return t.length;
}

function fimSub(t, j) {
  let prof = 1;
  for (; j < t.length; j++) {
    const c = t[j];
    if (c === '\\') j++;
    else if (c === "'") {
      const f = t.indexOf("'", j + 1);
      if (f === -1) return t.length;
      j = f;
    } else if (c === '"') j = fimAspas(t, j + 1);
    else if (c === '`') j = fimCrase(t, j + 1);
    else if (c === '(') prof++;
    else if (c === ')' && --prof === 0) return j;
  }
  return t.length;
}

// Lexer: devolve tokens { t: 'p' (palavra), 'op' (; && || | &), 'r' (redirecionamento), '(' , ')' }.
// Palavra: { t, v (sem aspas), din, subs (textos de $( ) e crases), citado }.
function lexar(texto) {
  const toks = [];
  const pendentes = []; // redirecionamentos `<<` cujo corpo vem na linha seguinte
  let pal = null;
  let aguardaDelim = null;
  const marca = () => {
    pal ??= { v: '', din: false, subs: [], citado: false };
    return pal;
  };
  const fimPal = () => {
    if (pal === null) return;
    if (aguardaDelim) {
      Object.assign(aguardaDelim, { delim: pal.v, citado: pal.citado });
      pendentes.push(aguardaDelim);
      aguardaDelim = null;
    }
    toks.push({ t: 'p', v: pal.v, din: pal.din, subs: pal.subs, citado: pal.citado });
    pal = null;
  };
  const sub = (inicio, crase) => {
    const fim = crase ? fimCrase(texto, inicio) : fimSub(texto, inicio);
    const p = marca();
    p.subs.push(texto.slice(inicio, fim));
    p.din = true;
    return fim + 1;
  };

  let i = 0;
  while (i < texto.length) {
    const c = texto[i];
    if (c === "'") {
      const f = texto.indexOf("'", i + 1);
      const ate = f === -1 ? texto.length : f;
      const p = marca();
      p.citado = true;
      p.v += texto.slice(i + 1, ate);
      i = ate + 1;
    } else if (c === '"') {
      const p = marca();
      p.citado = true;
      i++;
      while (i < texto.length && texto[i] !== '"') {
        const d = texto[i];
        if (d === '\\' && i + 1 < texto.length) {
          const n = texto[i + 1];
          p.v += '"\\$`\n'.includes(n) ? n : '\\' + n;
          i += 2;
        } else if (d === '$' && texto[i + 1] === '(') {
          i = sub(i + 2, false);
        } else if (d === '`') {
          i = sub(i + 1, true);
        } else {
          if (d === '$') p.din = true;
          p.v += d;
          i++;
        }
      }
      i++;
    } else if (c === '\\') {
      if (i + 1 < texto.length) marca().v += texto[i + 1];
      i += 2;
    } else if (c === '$' && texto[i + 1] === '(') {
      i = sub(i + 2, false);
    } else if (c === '`') {
      i = sub(i + 1, true);
    } else if (c === ' ' || c === '\t') {
      fimPal();
      i++;
    } else if (c === '\n') {
      fimPal();
      toks.push({ t: 'op', v: ';' });
      i++;
      // Corpo de heredoc: linhas até a linha que é só o delimitador. Não é tokenizado.
      for (const r of pendentes.splice(0)) {
        const linhas = [];
        while (i < texto.length) {
          let fl = texto.indexOf('\n', i);
          if (fl === -1) fl = texto.length;
          const linha = texto.slice(i, fl);
          i = fl + 1;
          if ((r.tabs ? linha.replace(/^\t+/, '') : linha) === r.delim) break;
          linhas.push(linha);
        }
        r.corpo = linhas.map((l) => `${l}\n`).join('');
      }
    } else if (c === '<' || c === '>' || (c === '&' && texto[i + 1] === '>')) {
      // `2>&1`: o descritor numérico antes do operador não é palavra.
      if (pal && !pal.citado && /^\d+$/.test(pal.v) && c !== '&') pal = null;
      else fimPal();
      const op = REDIRECIONAMENTO.exec(texto.slice(i))[0];
      i += op.length;
      const tok = { t: 'r', op, tabs: op === '<<-', corpo: undefined, delim: null, citado: false };
      toks.push(tok);
      if (op === '<<' || op === '<<-') aguardaDelim = tok;
    } else if (c === '(' || c === ')') {
      fimPal();
      toks.push({ t: c });
      i++;
    } else if (c === ';' || c === '|' || c === '&') {
      fimPal();
      const v = /^(?:&&|\|\||\|&|;;|;|\||&)/.exec(texto.slice(i))[0];
      i += v.length;
      toks.push({ t: 'op', v: v === '|&' ? '|' : v === ';;' ? ';' : v });
    } else {
      const p = marca();
      if (c === '$') p.din = true;
      p.v += c;
      i++;
    }
  }
  fimPal();
  return toks;
}

// Analisador sintático: lista = pipelines separados por ; && || &; pipeline = elementos
// separados por |; elemento = ( lista ) ou comando simples. Redirecionamento e o alvo dele
// são guardados à parte, fora das palavras.
function analisar(toks) {
  let i = 0;
  const elemento = () => {
    if (toks[i]?.t === '(') {
      i++;
      const itens = lista(true);
      if (toks[i]?.t === ')') i++;
      return { tipo: 'sub', itens };
    }
    return simples();
  };
  const pipeline = () => {
    const elems = [];
    for (;;) {
      elems.push(elemento());
      if (toks[i]?.t === 'op' && toks[i].v === '|') {
        i++;
        continue;
      }
      return elems;
    }
  };
  const simples = () => {
    const palavras = [];
    const redirs = [];
    while (i < toks.length) {
      const t = toks[i];
      if (t.t === 'op' || t.t === '(' || t.t === ')') break;
      if (t.t === 'r') {
        i++;
        const alvo = toks[i]?.t === 'p' ? toks[i++] : null;
        redirs.push({ tok: t, alvo });
        continue;
      }
      palavras.push(t);
      i++;
    }
    return { tipo: 'cmd', palavras, redirs };
  };
  const lista = (dentroParen) => {
    const itens = [];
    while (i < toks.length) {
      const t = toks[i];
      if (t.t === ')') {
        if (dentroParen) break;
        i++;
        continue;
      }
      if (t.t === 'op' && t.v !== '|') {
        i++;
        continue;
      }
      const antes = i;
      const pipe = pipeline();
      if (i === antes) {
        i++;
        continue;
      }
      const prox = toks[i];
      let op = null;
      if (prox?.t === 'op' && prox.v !== '|') {
        op = prox.v;
        i++;
      }
      itens.push({ pipe, op });
    }
    return itens;
  };
  return lista(false);
}

// Diretório de um valor: `null` quando não se conhece (variável, `cd -`, base desconhecida).
function resolverDir(p, base) {
  if (!p || p.din) return null;
  let v = p.v;
  if (v === '~' || v.startsWith('~/')) v = os.homedir() + v.slice(1);
  else if (v.startsWith('~')) return null;
  if (path.isAbsolute(v)) return path.resolve(v);
  return base === null ? null : path.resolve(base, v);
}

function existeDir(p) {
  try {
    return fs.statSync(p).isDirectory();
  } catch {
    return false;
  }
}

// Pula opções que podem trazer valor (`-u X`), até a primeira que não é opção. Devolve o índice.
function pularOpcoes(palavras, k, comValor) {
  for (;;) {
    const t = palavras[k]?.v;
    if (t === undefined || t === '-' || !t.startsWith('-')) return k;
    if (t === '--') return k + 1;
    k += comValor.has(t) ? 2 : 1;
  }
}

// Tira o que vem antes do executável: atribuições, palavras de controle, sudo/env/nice/timeout
// e seus opcionais. `env -C dir` muda o diretório do comando, então devolve os cwds dele.
function pularPrefixo(palavras, cwds) {
  const prefixo = {};
  let cwdsCmd = cwds;
  let k = 0;
  const v = (j) => palavras[j]?.v;
  for (;;) {
    const t = v(k);
    if (t === undefined) break;
    if (ATRIBUICAO.test(t)) {
      const eq = t.indexOf('=');
      prefixo[t.slice(0, eq)] = t.slice(eq + 1);
      k++;
      continue;
    }
    if (ENVOLTORIOS.has(t)) {
      k++;
      continue;
    }
    const base = path.basename(t);
    if (base === 'sudo') {
      k = pularOpcoes(palavras, k + 1, SUDO_COM_VALOR);
      continue;
    }
    if (base === 'env') {
      k++;
      for (;;) {
        const u = v(k);
        if (u === undefined) break;
        if (ATRIBUICAO.test(u)) {
          const eq = u.indexOf('=');
          prefixo[u.slice(0, eq)] = u.slice(eq + 1);
          k++;
        } else if (u === '-u' || u === '--unset') {
          k += 2;
        } else if (u === '-C' || u === '--chdir') {
          const dir = palavras[k + 1];
          cwdsCmd = cwdsCmd.map((c) => resolverDir(dir, c));
          k += 2;
        } else if (u === '--') {
          k++;
          break;
        } else if (u.startsWith('-')) {
          k++;
        } else {
          break;
        }
      }
      continue;
    }
    if (base === 'nice') {
      k++;
      if (v(k) === '-n') k += 2;
      else if (/^-\d+$/.test(v(k) ?? '')) k++;
      continue;
    }
    if (base === 'timeout') {
      k = pularOpcoes(palavras, k + 1, TIMEOUT_COM_VALOR) + 1; // +1: a duração
      continue;
    }
    break;
  }
  return { k, prefixo, cwdsCmd };
}

// `cd` muda o cwd dos comandos seguintes. Diretório que não existe agora pode existir quando o
// comando rodar (um `mkdir` antes, na mesma linha): então o original e `null` continuam
// candidatos (achado 3). `cd -` depende do OLDPWD, que o hook não conhece.
function cdAplicar(args, cwds) {
  let k = 0;
  while (args[k] && /^-[LPe@]+$/.test(args[k].v)) k++;
  if (args[k]?.v === '--') k++;
  const alvo = args[k];
  const novos = [];
  for (const c of cwds) {
    let dst;
    if (!alvo) dst = os.homedir();
    else if (alvo.v === '-' && !alvo.din) dst = null;
    else dst = resolverDir(alvo, c);
    if (dst === null) novos.push(null);
    else if (existeDir(dst)) novos.push(dst);
    else novos.push(c, null);
  }
  return [...new Set(novos)];
}

function avaliarCmd(cmd, cwds, visitar, profund) {
  // Substituições e alvos de redirecionamento rodam antes do comando, no cwd deste ponto.
  for (const p of cmd.palavras) for (const s of p.subs) percorrer(s, cwds, visitar, profund + 1);
  for (const r of cmd.redirs) for (const s of r.alvo?.subs ?? []) percorrer(s, cwds, visitar, profund + 1);

  const { k, prefixo, cwdsCmd } = pularPrefixo(cmd.palavras, cwds);
  const nomeTok = cmd.palavras[k];
  if (!nomeTok || nomeTok.din) return cwds; // shortcut do cabeçalho: nome por variável
  const nome = path.basename(nomeTok.v);
  const args = cmd.palavras.slice(k + 1);
  if (nome === 'cd') return cdAplicar(args, cwds);
  // Dado: o argumento não é executado. O visitante decide se o texto não citado ainda conta.
  if (DADO.has(nome)) {
    visitar({ nome, palavras: args, cwds: cwdsCmd, prefixo, dado: true });
    return cwds;
  }
  if (SHELLS.has(nome)) {
    const c = args.findIndex((a) => /^-\w*c\w*$/.test(a.v));
    if (c !== -1 && args[c + 1]) percorrer(args[c + 1].v, cwdsCmd, visitar, profund + 1);
    const hd = cmd.redirs.find((r) => r.tok.corpo !== undefined && r.tok.op.startsWith('<<') && r.tok.op !== '<<<');
    if (hd) percorrer(hd.tok.corpo, cwdsCmd, visitar, profund + 1);
    return cwds;
  }
  visitar({ nome, palavras: args, cwds: cwdsCmd, prefixo });
  return cwds;
}

// Subshell `( )` e pipeline com mais de um elemento (ou `&`) rodam em subshell: o cd deles não
// vaza para o comando seguinte (achado 7).
function avaliarPipe(elems, op, cwds, visitar, profund) {
  let depois = cwds;
  for (const el of elems) {
    if (el.tipo === 'sub') {
      avaliarLista(el.itens, cwds, visitar, profund);
    } else {
      const novo = avaliarCmd(el, cwds, visitar, profund);
      if (elems.length === 1 && op !== '&') depois = novo;
    }
  }
  return depois;
}

function avaliarLista(itens, cwds, visitar, profund) {
  let atual = cwds;
  for (const { pipe, op } of itens) atual = avaliarPipe(pipe, op, atual, visitar, profund);
  return atual;
}

function percorrer(texto, cwds, visitar, profund = 0) {
  if (profund > PROFUNDIDADE_MAX) {
    visitar({ profundidade: true, texto });
    return;
  }
  avaliarLista(analisar(lexar(texto)), cwds, visitar, profund);
}

// Argumentos de `git` (depois do executável) separados em opções globais, subcomando e resto.
// Opções globais `-C`, `-c`, `--git-dir`, `--work-tree` e as sem valor (`--no-pager`) são
// todas puladas, para que o subcomando apareça (achado 1 e 18 do review).
function desmontarGit(palavras) {
  const globais = [];
  let k = 0;
  for (;;) {
    const p = palavras[k];
    if (!p) break;
    if (GLOBAIS_GIT_COM_VALOR.has(p.v) && palavras[k + 1]) {
      globais.push({ opcao: p.v, valor: palavras[k + 1] });
      k += 2;
    } else if (/^--(git-dir|work-tree|namespace|exec-path|super-prefix|config-env)=/.test(p.v)) {
      const igual = p.v.indexOf('=');
      globais.push({ opcao: p.v.slice(0, igual), valor: { v: p.v.slice(igual + 1), din: p.din } });
      k++;
    } else if (p.v.startsWith('-')) {
      k++;
    } else {
      break;
    }
  }
  return { globais, sub: palavras[k]?.v, resto: palavras.slice(k + 1) };
}

module.exports = { percorrer, desmontarGit, resolverDir, PROFUNDIDADE_MAX };
