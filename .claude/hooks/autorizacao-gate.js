#!/usr/bin/env node
// Camada 3 da trava de autorizacao do AGENTS.md §Autorizacao. Portado do projeto artificio (autorizacao-gate.js).
//
// Por que existe, em uma frase: as regras declarativas dos tres harnesses
// (permissions.deny/ask no Claude Code, .codex/rules/governanca.rules no Codex,
// permission.bash no OpenCode) casam o comando pelo texto que o agente escreve,
// e a propria documentacao do Claude Code declara o limite — uma regra de Bash
// "isn't a security boundary around the program". Este hook e o que enxerga o
// que elas nao enxergam.
//
// O que escapa das regras declarativas, medido em 2026-09-10:
//   - caminho absoluto:      /usr/bin/git commit         (nenhuma das tres casa)
//   - flag antes do subcomando: git -C . commit          (matchedRules vazio no Codex)
//   - aninhado em shell:     bash -lc "cd /x && git commit"
//   - substituicao:          echo "$(git commit -m x)"
// O hook alcanca os quatro porque le `tool_input.command` — o texto integral da
// chamada, inclusive o que esta dentro das aspas de um `bash -lc`.
//
// Escopo deliberadamente estreito: este hook NAO reimplementa a lista inteira do
// AGENTS.md. As regras declarativas ja cobrem o caso comum e mostram o prompt ao
// mantenedor, que e o comportamento desejado. Aqui ficam so as acoes cujo
// escape e (a) plausivel na pratica e (b) caro de reverter. Regra que a camada
// declarativa ja cobre bem nao se duplica aqui: duplicar espalha a manutencao e
// faz as duas divergirem com o tempo.
//
// No phati o AGENTS.md exige autorizacao nominal tambem para `git push` e merge, entao push pergunta
// (no artificio push e PR estao liberados; aqui nao). Nao ha banco de producao local: sem regra de SQL.
//
// Falha aberta, deliberadamente: payload ilegivel ou erro interno sai com 0. Um
// gate que derruba o turno e desligado na primeira vez que atrapalha, e ai nao
// protege mais nada.

'use strict';

const { lerPayload } = require(require('node:path').join(__dirname, 'ler-payload.js'));

// Normaliza o texto antes de testar, para que o padrao nao precise antecipar
// cada forma de escrever o mesmo comando. Sem isto, cada regra viraria uma
// regex barroca e as evasoes passariam pelo que ela esquecesse.
function normalizar(cmd) {
  return cmd
    // Argumento de `echo`/`printf` e dado, nao execucao: `echo "git commit e o
    // assunto"` nao commita nada, e bloquear isso e o tipo de falso positivo que
    // faz o mantenedor desligar o gate. So a forma literal cai fora — uma
    // substituicao como `echo "$(git commit)"` executa de verdade e por isso e
    // preservada pelo negative lookahead do $(.
    .replace(/\b(?:echo|printf)\s+(['"])(?:(?!\1)[^$\\]|\\.)*\1/g, ' ')
    // Mesma logica para o padrao de busca: `rtk rg "git commit" docs` procura o
    // texto, nao commita. Achado pela propria suite em 2026-09-10.
    .replace(/\b(?:rg|grep|ag|ack|rtk\s+rg|rtk\s+grep)\s+(?:-\S+\s+)*(['"])(?:(?!\1)[^$\\]|\\.)*\1/g, ' ')
    // Caminho absoluto vira o executavel nu: /usr/bin/git -> git.
    .replace(/(^|[\s;&|(`$])(?:\/[\w.\-/]*\/)?(?=(?:git|gh|docker|apt-get|apt|scp|rsync|ssh|shutdown|reboot|poweroff|halt)\b)/g, '$1')
    // Aspas em torno do subcomando: git 'commit' -> git commit.
    .replace(/(^|\s)(['"])([\w-]+)\2/g, '$1$3')
    // Flags de configuracao entre o executavel e o subcomando:
    // git -C . commit / git -c k=v commit -> git commit.
    .replace(/\bgit(?:\s+-(?:C|c|-git-dir|-work-tree|-namespace|-exec-path)(?:=\S+|\s+\S+))+/g, 'git')
    .replace(/\s+/g, ' ');
}

const REGRAS = [
  // --- `deny`: bloqueio sem prompt. Nenhum pedido autoriza por interpretacao ---
  {
    nome: 'vm-desligamento',
    decisao: 'deny',
    // Ancorado em `ssh` ou em comando de sistema solto: derrubar a VM maruko tira
    // producao inteira do ar (todos os subdominios, o SSO e os bancos) e quem
    // religa e o mantenedor, manualmente, no painel da Oracle.
    test: /(^|[\s;&|(`])(?:sudo\s+)?(?:shutdown|reboot|poweroff|halt|init\s+[06])\b|systemctl\s+(?:poweroff|reboot|halt)\b/,
    porque: 'AGENTS.md (petrea): NUNCA desligar, reiniciar ou suspender a VM maruko. A VM hospeda producao inteira e nao ha caminho de volta pelo agente. Se o alvo e a maquina Windows local, rode no prompt local, nunca por aqui.',
  },
  {
    nome: 'amend-proibido',
    decisao: 'deny',
    // Duplicado de proposito com o git-commit-msg-gate: la o padrao e o texto
    // literal `--amend`; aqui ele passa pela normalizacao, entao tambem pega
    // `/usr/bin/git commit --amend` e a forma dentro de `bash -lc`.
    test: /\bgit\s+commit\b[^;&|]*--amend/,
    porque: 'AGENTS.md (petrea, sem excecao): `git commit --amend` e PROIBIDO. Reescreve commit ja em review e forca push --force. Faca commit novo.',
  },
  {
    nome: 'push-force',
    decisao: 'deny',
    test: /\bgit\s+push\b[^;&|]*(?:--force(?!-with-lease)|--force-with-lease|\s-f\b)/,
    porque: 'AGENTS.md: push que reescreve historico de branch em review exige aprovacao nominal do mantenedor, nunca por inercia.',
  },

  // --- `ask`: exige autorizacao nominal por acao (§Autorizacao) ---
  //
  // Estas PERGUNTAM ao mantenedor; nao bloqueiam. Emitiam `deny` ate 2026-09-10,
  // o que tornava a acao impossivel por este harness mesmo com a autorizacao ja
  // dada: o gate nao distinguia "nao autorizado" de "autorizado", porque nunca
  // chegava a perguntar. O AGENTS.md ja dizia o correto — "commit, worktree,
  // escrita na VM, SQL write e pacote novo sao `ask`" — e era o hook que
  // divergia do texto que implementa. Achado ao tentar commitar a propria
  // spec 101 (F5), com autorizacao nominal dada e recusada pelo gate.
  {
    nome: 'commit-sem-autorizacao',
    decisao: 'ask',
    test: /\bgit\s+commit\b/,
    porque: 'AGENTS.md §Autorizacao: cada commit exige autorizacao nominal do mantenedor — nao acumula entre commits, mesmo em branch ja pushada, mesmo no mesmo PR, mesmo na mesma conversa. "pode seguir"/"corrija"/"documente" NAO autorizam commit.',
  },
  {
    nome: 'push-sem-autorizacao',
    decisao: 'ask',
    test: /\bgit\s+push\b/,
    porque: 'AGENTS.md §Autorizacao: `git push` exige autorizacao nominal do mantenedor, a cada vez. Abrir a PR e a mesma acao do push. Depois de empurrar, parar: sem checks, sem polling.',
  },
  {
    nome: 'worktree-sem-aprovacao',
    decisao: 'ask',
    test: /\bgit\s+worktree\s+(?:add|move|remove)\b/,
    porque: 'AGENTS.md §Autorizacao: criar/mover/remover worktree exige aprovacao nominal PREVIA. Explique antes por que o cwd nao pode ser usado, o caminho exato, e como o trabalho volta. `git worktree list` e livre.',
  },
  {
    nome: 'vm-escrita',
    decisao: 'ask',
    // `ssh maruko` com subcomando de mutacao. Read-only na VM e livre por regra
    // petrea e nao pode cair aqui — dai a lista fechada de verbos de escrita.
    test: /\bssh\s+maruko\b[^;&|]*\b(?:docker\s+(?:restart|stop|start|rm|kill|compose\s+(?:up|down))|systemctl\s+(?:start|stop|restart)|rm\s+-|mv\s|cp\s|tee\s|>\s*\/)/,
    porque: 'AGENTS.md §Autorizacao: escrita na VM maruko exige aprovacao nominal a cada vez. Inspecao read-only (docker ps|logs|inspect, cat, ls) e SEMPRE permitida e nao passa por aqui.',
  },
  {
    nome: 'pacote-novo',
    decisao: 'ask',
    test: /(?:^|[\s;&|(`])(?:sudo\s+)?apt(?:-get)?\s+install\b/,
    porque: 'AGENTS.md §Autorizacao: pacote apt novo exige PERGUNTAR antes — qual pacote, por que e necessario, alternativa ja existente no repo, e impacto. So instala depois da resposta.',
  },
];

lerPayload((raw) => {
  let command = '';
  try {
    command = JSON.parse(raw)?.tool_input?.command ?? '';
  } catch {
    process.exit(0); // payload ilegivel nunca bloqueia trabalho
  }
  if (!command) process.exit(0);

  const alvo = normalizar(command);

  for (const regra of REGRAS) {
    if (!regra.test.test(alvo)) continue;

    console.log(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: regra.decisao,
        permissionDecisionReason:
          `[autorizacao-gate/${regra.nome}] ${regra.porque}`
          // No `ask`, o proprio prompt E o pedido de autorizacao: mandar o agente
          // "pedir antes de reemitir" faria ele pedir duas vezes a mesma coisa.
          // No `deny` nao ha prompt, entao a saida de escape precisa vir no texto.
          + (regra.decisao === 'ask'
            ? ''
            : `\n\nPeca a autorizacao ao mantenedor no formato "APROVACAO NECESSARIA" `
              + `(Acao / Motivo / Risco / Rollback / Escopo / Comandos) antes de reemitir.`),
      },
    }));
    process.exit(0);
  }

  process.exit(0);
});
