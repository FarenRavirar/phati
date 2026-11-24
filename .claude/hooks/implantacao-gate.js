#!/usr/bin/env node
// implantacao-gate — PreToolUse(Bash): NEGA a execução direta dos scripts de implantação
// na VM, e PERGUNTA antes do trocar-banco.sh.
//
// Regras:
//   1. deny `implantar-direto`: implantar.sh (inclui as funções reverter e trocar dele),
//      restaurar.sh e backup.sh. A implantação passa só pelo workflow GitHub Actions
//      `implantar`: `gh workflow run implantar --ref main -f sha=<SHA>` (o `--ref main` é
//      obrigatório: sem ele o Environment recusa).
//   2. ask `trocar-banco`: trocar-banco.sh não tem workflow; cada execução é decisão do
//      mantenedor, então pergunta em vez de negar.
//
// Desenho (inverte o parse antigo, que só seguia embrulhos e deixava escapar `source`,
// `eval`, `timeout`, `xargs`, `ln`, `<(...)` e `echo x | bash`):
//   a) Um segmento (corte em `;`, `&&`, `||`, `|`, `&`, parênteses, `$(` e crase) que
//      MENCIONA um script protegido, por basename, é negado, salvo quando a palavra de
//      comando efetiva dele é verbo de leitura/teste (LEITURA, git log|diff|..., sed -n,
//      bash -n, node --test). Os embrulhos (rtk, sudo, env, exec, ssh, bash -c) saem antes.
//   b) Quem executa o que recebe pelo stdin (shell sem arquivo, `source`, `eval`, `xargs`)
//      é negado quando o comando inteiro cita script protegido, porque o texto citado é o
//      que roda. Cobre `echo scripts/x | bash`, `bash <(cat scripts/x)`, `source <(...)`.
//   c) Texto de mensagem não executa: corpo de heredoc e valor de -m/-F/--body/--title/--body-file
//      saem da análise (separarTexto), e só os `$(...)` e crases dentro deles seguem sendo vistos.
//      Assim `git commit -m "fix: implantar.sh"` passa e `git commit -m "$(scripts/implantar.sh x)"` nega.
//   Com isso `ln -s scripts/implantar.sh /tmp/x` nega (ln não é leitura e o nome está no
//   segmento), e `gh workflow run implantar` passa (não cita script). `gh` com script citado
//   nega pela regra (a), porque gh não é verbo de leitura.
//
// shortcut: o desembrulho cobre rtk/bypass/proxy, sudo, env, nohup, exec, command, time, ssh
//   e bash/sh (-c e arquivo). `timeout` e `nice` não são seguidos: `timeout 5 cat scripts/x` nega
//   (falha fechada). Upgrade: incluir o embrulho quando um caso real pedir.
// shortcut: nomes de script que entram por stdin de comando que não cita o nome
//   (`ls scripts | xargs bash`, `find ... -exec bash {} \;`) não são vistos. Upgrade: parser de shell.
// shortcut: `sed -n` com o comando `e` do GNU e comando montado em arquivo antes
//   (`printf 'scripts/implantar.sh' > /tmp/x; sh /tmp/x`) não são vistos. Upgrade: parser de shell.
// shortcut: o split ignora heredoc e substituição aninhada além de um nível. Upgrade: parser de shell.
//
// Falha aberta: payload ilegível, comando vazio ou erro interno saem com 0 sem saída. Decisão de
// projeto: nunca bloquear trabalho por payload ilegível. Um gate que derruba o turno é desligado na
// primeira vez que atrapalha.

'use strict';

const path = require('node:path');
const { lerPayload } = require(path.join(__dirname, 'ler-payload.js'));

const REGRAS = [
  {
    nome: 'implantar-direto',
    decisao: 'deny',
    scripts: ['implantar.sh', 'restaurar.sh', 'backup.sh'],
    porque: 'A implantação na VM passa só pelo workflow GitHub Actions `implantar`, com o SHA de dev que já está com CI verde. Execução direta de script de implantação na VM fica barrada. Use: gh workflow run implantar --ref main -f sha=<SHA>',
  },
  {
    nome: 'trocar-banco',
    decisao: 'ask',
    scripts: ['trocar-banco.sh'],
    porque: 'trocar-banco.sh não tem workflow no GitHub Actions. Cada execução na VM exige a decisão do mantenedor, por ação: confirme antes de rodar.',
  },
];
const PROTEGIDOS = new Set(REGRAS.flatMap((r) => r.scripts));

const EMBRULHOS = new Set(['rtk', 'bypass', 'proxy', 'sudo', 'env', 'nohup', 'exec', 'command', 'time']);
// Opções que levam argumento logo depois, por embrulho: `sudo -u root cmd`, `env -u VAR cmd`, `exec -a nome cmd`.
const ARG_DO_EMBRULHO = {
  sudo: new Set(['-u', '-g', '-p', '-C', '-D', '-r', '-t', '-T', '-U']),
  env: new Set(['-u', '-C']),
  exec: new Set(['-a']),
};
const SHELLS = new Set(['bash', 'sh', 'zsh', 'dash']);
// ssh: opções que levam argumento; depois delas vem o host e o resto é o comando remoto.
const SSH_COM_ARG = new Set(['-p', '-i', '-l', '-o', '-F', '-J', '-b', '-c', '-D', '-E', '-e', '-I', '-L', '-m', '-O', '-Q', '-R', '-S', '-W', '-w']);
const ATRIBUICAO = /^[A-Za-z_][A-Za-z0-9_]*=/;
// Verbos que só leem, listam ou checam. Só valem para segmento que cita script protegido.
const LEITURA = new Set(['rg', 'grep', 'cat', 'head', 'tail', 'less', 'ls', 'wc', 'stat', 'file', 'echo', 'printf', 'shellcheck', 'read']);
// git add/commit/push/status/restore só mexem em índice, histórico ou rede: o nome do script é caminho
// ou mensagem, não execução. `checkout` só vale com `--` (restaura arquivo, não troca de branch).
const GIT_LEITURA = new Set(['log', 'diff', 'show', 'grep', 'blame', 'status', 'add', 'commit', 'push', 'restore']);
const GH_PR_LEITURA = new Set(['create', 'edit', 'view', 'checks']);
// Quem executa o que recebe como comando ou pelo stdin.
const CONSUMIDORES = new Set(['source', '.', 'eval', 'xargs']);
// Corpo de heredoc e valor de -m/-F/--body/--title/--body-file são texto de mensagem: não executam.
// Só o `$(...)` e a crase dentro deles executam, e esses saem para análise (ver separarTexto).
const HEREDOC = /<<-?\s*(['"]?)(\w+)\1([^\n]*)\n([\s\S]*?)\n\s*\2[ \t]*(?=\n|$)/g;
const VALOR_TEXTO = /(^|\s)(?:-m|-F|--body-file|--body|--title)(?:\s+|=)("(?:[^"\\]|\\.)*"|'[^']*'|[^\s;&|()]+)/g;
const SUBSTITUICAO = /\$\(((?:[^()]|\([^()]*\))*)\)|`([^`]*)`/g;

// Tira embrulhos, prefixos de atribuição e o `-c` dos shells. Devolve a palavra de comando efetiva:
// { cmd (basename), resto (tokens dela em diante), semExecucao, alimentaShell }, ou null.
// `bash -n` só checa sintaxe. Shell sem arquivo nem -c lê o comando do stdin (`alimentaShell`).
function efetivo(tokens) {
  let i = 0;
  while (i < tokens.length) {
    const w = tokens[i];
    const base = path.basename(w);
    if (ATRIBUICAO.test(w)) {
      i += 1;
    } else if (EMBRULHOS.has(base)) {
      const comArg = ARG_DO_EMBRULHO[base];
      i += 1;
      while (i < tokens.length && tokens[i].startsWith('-')) {
        if (comArg?.has(tokens[i])) i += 1;
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
      let j = i + 1;
      let inline = false;
      let semExecucao = false;
      while (j < tokens.length && tokens[j].startsWith('-')) {
        const opt = tokens[j];
        if (!opt.startsWith('--')) {
          if (opt.includes('c')) inline = true;
          if (opt.includes('n')) semExecucao = true;
        }
        j += 1;
      }
      if (inline) {
        i = j; // `bash -c "..."`: o restante já está em tokens, o laço segue desembrulhando
        continue;
      }
      const alimentaShell = !semExecucao && (j >= tokens.length || tokens[j].startsWith('<'));
      return { cmd: base, resto: tokens.slice(i), semExecucao, alimentaShell };
    } else {
      return { cmd: base, resto: tokens.slice(i), semExecucao: false, alimentaShell: false };
    }
  }
  return null;
}

// Verbo que só lê, lista ou checa: citar script protegido nele não executa nada.
function ehLeitura(e) {
  if (e.semExecucao) return true; // bash -n / sh -n
  const args = e.resto.slice(1);
  if (LEITURA.has(e.cmd)) return !args.some((t) => t === '--pre' || t.startsWith('--pre=')); // rg --pre roda um programa por arquivo
  if (e.cmd === 'sed') return args[0] === '-n' && !args.some((t) => /^-\w*i/.test(t) || t.startsWith('--in-place'));
  if (e.cmd === 'git') return GIT_LEITURA.has(args[0]) || (args[0] === 'checkout' && args.includes('--'));
  if (e.cmd === 'gh') return args[0] === 'pr' && GH_PR_LEITURA.has(args[1]);
  if (e.cmd === 'node') return args[0] === '--test';
  return false;
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

// Tira o texto de mensagem (heredoc e -m/-F/--body/--title/--body-file) e devolve o comando que executa.
// Os `$(...)` e as crases de dentro do texto viram comandos no fim, para continuarem sendo vistos.
function separarTexto(comando) {
  const ignorado = [];
  let exec = comando.replace(HEREDOC, (_, _aspas, _marca, resto, corpo) => {
    ignorado.push(corpo);
    return resto;
  });
  exec = exec.replace(VALOR_TEXTO, (_, pre, valor) => {
    ignorado.push(valor);
    return pre;
  });
  const substituidos = [];
  for (const texto of ignorado) {
    for (const m of texto.matchAll(SUBSTITUICAO)) substituidos.push(m[1] ?? m[2]);
  }
  return [exec, ...substituidos].join('\n');
}

// Tokens do texto inteiro, sem o echo literal removido: `echo 'x' | bash` ainda cita o script.
function tokensDoTexto(comando) {
  return comando.split(/[\s;&|()<>`'"]+/).filter(Boolean);
}

function alvosProtegidos(tokens) {
  return tokens.map((t) => path.basename(t)).filter((n) => PROTEGIDOS.has(n));
}

// Devolve { regra, alvo } da primeira regra (na ordem de REGRAS) que casa algum alvo, ou null.
function decidir(comando) {
  const executavel = separarTexto(comando);
  const alvosNoTexto = alvosProtegidos(tokensDoTexto(executavel));
  if (alvosNoTexto.length === 0) return null;

  const alvos = [];
  for (const tokens of segmentos(executavel)) {
    const e = efetivo(tokens);
    if (!e || !ehLeitura(e)) alvos.push(...alvosProtegidos(tokens));
    if (e && (CONSUMIDORES.has(e.cmd) || e.alimentaShell)) alvos.push(...alvosNoTexto);
  }

  const regra = REGRAS.find((r) => r.scripts.some((n) => alvos.includes(n)));
  if (!regra) return null;
  return { regra, alvo: regra.scripts.find((n) => alvos.includes(n)) };
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

module.exports = { decidir, efetivo, segmentos };
