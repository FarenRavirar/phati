#!/usr/bin/env node
// implantacao-gate — PreToolUse(Bash): NEGA a execução direta dos scripts de implantação
// na VM, e PERGUNTA antes do trocar-banco.sh.
//
// Regras:
//   1. deny `implantar-direto`: implantar.sh (inclui as funções reverter e trocar dele),
//      restaurar.sh e backup.sh. A implantação passa só pelo workflow GitHub Actions
//      `implantar`: `gh workflow run implantar -f sha=<SHA>`.
//   2. ask `trocar-banco`: trocar-banco.sh não tem workflow; cada execução é decisão do
//      mantenedor, então pergunta em vez de negar.
//
// Por que existe: as regras declarativas do settings casam o texto do comando, e
// `sudo -n /opt/phati/bin/implantar.sh`, `bash scripts/x.sh` ou `bash -lc "sudo ..."`
// escapam delas. Este hook enxerga o comando depois de desembrulhar os prefixos.
//
// Técnica: o comando vira segmentos simples (corta em `;`, `&&`, `||`, `|`, `&`, parênteses e
// `$(`/crase), as aspas saem, e de cada segmento se tira o que só embrulha o comando real
// (rtk, sudo, env, ssh <host>, bash -c, etc.). Quem decide é a palavra de comando que
// sobra, por basename. Argumento de busca (`rtk rg implantar.sh scripts`) não é execução,
// porque a palavra de comando é `rg`. `bash -n` só checa sintaxe, então passa.
//
// shortcut: o desembrulho cobre rtk/bypass/proxy, sudo, env, nohup, exec, command, time, ssh
//   e bash/sh (-c e arquivo). Outros embrulhos (timeout, xargs, find -exec) não são seguidos.
//   Upgrade: incluir o embrulho quando um caso real escapar.
// shortcut: o split ignora heredoc e substituição aninhada além de um nível. Upgrade: parser de shell.
//
// Falha aberta: payload ilegível, comando vazio ou erro interno saem com 0 sem saída. Um gate que
// derruba o turno é desligado na primeira vez que atrapalha.

'use strict';

const path = require('node:path');
const { lerPayload } = require(path.join(__dirname, 'ler-payload.js'));

const REGRAS = [
  {
    nome: 'implantar-direto',
    decisao: 'deny',
    scripts: ['implantar.sh', 'restaurar.sh', 'backup.sh'],
    porque: 'A implantação na VM passa só pelo workflow GitHub Actions `implantar`, com o SHA de dev que já está com CI verde. Execução direta de script de implantação na VM fica barrada. Use: gh workflow run implantar -f sha=<SHA>',
  },
  {
    nome: 'trocar-banco',
    decisao: 'ask',
    scripts: ['trocar-banco.sh'],
    porque: 'trocar-banco.sh não tem workflow no GitHub Actions. Cada execução na VM exige a decisão do mantenedor, por ação: confirme antes de rodar.',
  },
];

const EMBRULHOS = new Set(['rtk', 'bypass', 'proxy', 'sudo', 'env', 'nohup', 'exec', 'command', 'time']);
// sudo: opções que levam argumento logo depois (`sudo -u root cmd`).
const SUDO_COM_ARG = new Set(['-u', '-g', '-p', '-C', '-D', '-r', '-t', '-T', '-U']);
const SHELLS = new Set(['bash', 'sh', 'zsh', 'dash']);
// ssh: opções que levam argumento; depois delas vem o host e o resto é o comando remoto.
const SSH_COM_ARG = new Set(['-p', '-i', '-l', '-o', '-F', '-J', '-b', '-c', '-D', '-E', '-e', '-I', '-L', '-m', '-O', '-Q', '-R', '-S', '-W', '-w']);
const ATRIBUICAO = /^[A-Za-z_][A-Za-z0-9_]*=/;

// Desembrulha um segmento e devolve a palavra de comando efetiva, ou null quando o segmento não executa nada.
function palavraDeComando(tokens) {
  let i = 0;
  while (i < tokens.length) {
    const w = tokens[i];
    const base = path.basename(w);
    if (ATRIBUICAO.test(w)) {
      i += 1;
    } else if (EMBRULHOS.has(base)) {
      i += 1;
      while (i < tokens.length && tokens[i].startsWith('-')) {
        if (base === 'sudo' && SUDO_COM_ARG.has(tokens[i])) i += 1;
        i += 1;
      }
    } else if (base === 'ssh') {
      i += 1;
      while (i < tokens.length && tokens[i].startsWith('-')) {
        if (SSH_COM_ARG.has(tokens[i])) i += 1;
        i += 1;
      }
      i += 1; // host
    } else if (SHELLS.has(base)) {
      i += 1;
      let inline = false;
      let semExecucao = false;
      while (i < tokens.length && tokens[i].startsWith('-')) {
        const opt = tokens[i];
        if (!opt.startsWith('--')) {
          if (opt.includes('c')) inline = true;
          if (opt.includes('n')) semExecucao = true;
        }
        i += 1;
      }
      if (semExecucao && !inline) return null; // `bash -n arq`: só checa sintaxe
      if (!inline) return tokens[i] ?? null; // `bash arq`: o arquivo é o comando
      // `bash -c "..."`: o restante já está em tokens, então o laço segue desembrulhando
    } else {
      return w;
    }
  }
  return null;
}

// Separa o comando em segmentos simples. Quebra em `$(` e crase antes de tirar as aspas, para
// que `echo "$(...)"` ainda seja visto. Argumento literal de echo/printf é dado, não execução.
function segmentos(comando) {
  const sem = comando
    .replace(/\b(?:echo|printf)\s+(['"])(?:(?!\1)[^$\\]|\\.)*\1/g, ' ')
    .replace(/\$\(|`/g, '\n');
  return sem
    .split(/\n|&&|\|\||[;&|()]/)
    .map((s) => s.replace(/['"]/g, ' ').trim().split(/\s+/).filter(Boolean))
    .filter((t) => t.length > 0);
}

// Devolve { regra, alvo } da primeira regra que casa algum segmento, ou null.
function decidir(comando) {
  const achados = [];
  for (const tokens of segmentos(comando)) {
    const palavra = palavraDeComando(tokens);
    if (palavra) achados.push(path.basename(palavra));
  }
  for (const regra of REGRAS) {
    const alvo = achados.find((nome) => regra.scripts.includes(nome));
    if (alvo) return { regra, alvo };
  }
  return null;
}

if (require.main === module) {
  lerPayload((raw) => {
    let payload;
    try {
      payload = JSON.parse(raw);
    } catch {
      process.exit(0); // payload ilegível nunca bloqueia trabalho
    }
    const comando = payload?.tool_input?.command ?? '';
    if (typeof comando !== 'string' || !comando.trim()) process.exit(0);

    const veredito = decidir(comando);
    if (veredito) {
      const { regra, alvo } = veredito;
      const motivo = `[implantacao-gate/${regra.nome}] ${alvo}: ${regra.porque}`;
      console.log(JSON.stringify({
        hookSpecificOutput: {
          hookEventName: 'PreToolUse',
          permissionDecision: regra.decisao,
          permissionDecisionReason: motivo,
        },
      }));
    }
    process.exit(0);
  });
}

module.exports = { decidir, palavraDeComando, segmentos };
