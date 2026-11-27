#!/usr/bin/env node
// Camada 3 da trava de autorizacao do AGENTS.md §Decisao, pausa e duvida.
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
// Antes de testar as regras, o comando passa pelo percorredor compartilhado
// (shell-analise.js, o mesmo do branch-gate): cada comando simples vira um texto canônico,
// sem aspas, prefixos (sudo, env, rtk, palavras de controle), opções globais do git, corpo de
// heredoc, nem o argumento de echo/grep (dado). Assim o regex das regras casa a forma real.
//
// Escopo deliberadamente estreito: este hook NAO reimplementa a lista inteira do
// AGENTS.md. As regras declarativas ja cobrem o caso comum e mostram o prompt ao
// mantenedor, que e o comportamento desejado. Aqui ficam so as acoes cujo
// escape e (a) plausivel na pratica e (b) caro de reverter. Regra que a camada
// declarativa ja cobre bem nao se duplica aqui: duplicar espalha a manutencao e
// faz as duas divergirem com o tempo.
//
// Decisao do mantenedor: COMMIT e MERGE (`git merge`, `gh pr merge`) pedem autorizacao nominal, por acao. `git push` e
// `gh pr create` nao aparecem abaixo, porque so acontecem depois de um commit autorizado; o merge tambem fica no
// `permissions.ask` de .claude/settings.json (segunda camada). Sem regra de SQL: nao ha banco de producao local.
//
// Falha aberta, deliberadamente: payload ilegivel ou erro interno sai com 0. Um
// gate que derruba o turno e desligado na primeira vez que atrapalha, e ai nao
// protege mais nada. Exceção: profundidade além do limite com git/gh/sistema dentro nega.

'use strict';

const { spawnSync } = require('node:child_process');
const path = require('node:path');
const { lerPayload } = require(path.join(__dirname, 'ler-payload.js'));
const { percorrer, desmontarGit } = require(path.join(__dirname, 'shell-analise.js'));

// Lê branch atual, último commit e o aviso que vai no prompt de commit. Falha aberta:
// qualquer erro (cwd inválido, fora de repositório, HEAD destacado) vira `null` e o
// `ask` segue, só sem o dado. Não reaproveita o branch-gate: ele roda lerPayload no
// require e não exporta nada, então importá-lo dispararia a leitura de stdin.
function contextoRepo(cwd) {
  try {
    const dir = typeof cwd === 'string' && cwd ? cwd : process.cwd();
    const git = (args) => {
      const r = spawnSync('git', args, { cwd: dir, encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });
      return r.status === 0 ? (r.stdout || '').trim() || null : null;
    };
    return {
      branch: git(['symbolic-ref', '--short', '-q', 'HEAD']),
      ultimo: git(['log', '-1', '--format=%h %s']),
    };
  } catch {
    return { branch: null, ultimo: null };
  }
}

function avisoCommit({ branch, ultimo }) {
  const onde = branch
    ? `Branch atual: ${branch}.`
    : 'Atenção: branch não identificada (HEAD destacado, fora de repositório ou erro de leitura).';
  const commit = ultimo ? `Último commit: ${ultimo}.` : 'Último commit não identificado.';
  return `\n\n${onde} ${commit} Confira se esta é a branch certa para este assunto antes de aprovar.`;
}

// Usado só quando a profundidade estoura: o texto cru mencionando estes comandos nega.
const AMPLO = /git|gh|apt|shutdown|reboot|poweroff|halt|systemctl/;

// Texto canônico do que o shell executa: um trecho por comando simples, separado por ` ; `.
// `profundo` marca texto além do limite de aninhamento, que não foi lido por inteiro.
function canonico(texto) {
  const trechos = [];
  let profundo = false;
  percorrer(texto, [null], (cmd) => {
    if (cmd.profundidade) {
      if (AMPLO.test(cmd.texto)) profundo = true;
      return;
    }
    if (cmd.dado) {
      // echo/rg com argumento citado é dado (não entra). Argumento não citado continua texto,
      // como no normalizar antigo: `echo git commit` pergunta (medido contra o HEAD, 2026-11-27).
      trechos.push([cmd.nome, ...cmd.palavras.filter((p) => !p.citado).map((p) => p.v)].join(' '));
    } else if (cmd.nome === 'git') {
      const g = desmontarGit(cmd.palavras);
      trechos.push(['git', g.sub, ...g.resto.map((p) => p.v)].filter((x) => x !== undefined).join(' '));
    } else {
      trechos.push([cmd.nome, ...cmd.palavras.map((p) => p.v)].join(' '));
    }
  });
  return { alvo: trechos.join(' ; '), profundo };
}

// [nome, decisao, motivo]. Ordem importa: a primeira que casa decide.
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
    // literal `--amend`; aqui ele passa pelo texto canônico, entao tambem pega
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

  // --- `ask`: exige autorizacao nominal por acao (§Decisao, pausa e duvida) ---
  //
  // Estas PERGUNTAM ao mantenedor; nao bloqueiam. Emitiam `deny` ate 2026-09-10,
  // o que tornava a acao impossivel por este harness mesmo com a autorizacao ja
  // dada: o gate nao distinguia "nao autorizado" de "autorizado", porque nunca
  // chegava a perguntar. Achado ao tentar commitar a propria spec 101 (F5), com
  // autorizacao nominal dada e recusada pelo gate.
  // Politica do mantenedor: so commit e merge pedem autorizacao aqui. Worktree e escrita na VM ficaram de fora.
  {
    nome: 'commit-sem-autorizacao',
    decisao: 'ask',
    test: /\bgit\s+commit\b/,
    porque: 'AGENTS.md §Decisao, pausa e duvida: cada commit exige autorizacao nominal do mantenedor — nao acumula entre commits, mesmo em branch ja pushada, mesmo no mesmo PR, mesmo na mesma conversa. "pode seguir"/"corrija"/"documente" NAO autorizam commit.',
  },
  {
    nome: 'merge-sem-autorizacao',
    decisao: 'ask',
    // `(?![\w-])` deixa passar `git merge-base`; `git log --merges` e `gh pr view` não casam.
    test: /\bgit\s+merge(?![\w-])|\bgh\s+pr\s+merge(?![\w-])/,
    porque: 'AGENTS.md §Decisao, pausa e duvida: merge (git merge, gh pr merge) exige autorizacao nominal do mantenedor, por acao. "pode seguir"/"corrija" NAO autorizam merge.',
  },
  {
    nome: 'pacote-novo',
    decisao: 'ask',
    test: /(?:^|[\s;&|(`])(?:sudo\s+)?apt(?:-get)?\s+install\b/,
    porque: 'AGENTS.md §Decisao, pausa e duvida: pacote apt novo exige PERGUNTAR antes — qual pacote, por que e necessario, alternativa ja existente no repo, e impacto. So instala depois da resposta.',
  },
];

// Tira a regra que o ambiente desligou. Regra sem `desligavel` é sempre ativa.
function regrasAtivas(ambiente) {
  return REGRAS.filter((regra) => !regra.desligavel || ambiente[regra.desligavel] !== '0');
}

function emitir(nome, decisao, porque, extra = '') {
  console.log(JSON.stringify({
    hookSpecificOutput: {
      hookEventName: 'PreToolUse',
      permissionDecision: decisao,
      permissionDecisionReason:
        `[autorizacao-gate/${nome}] ${porque}`
        // No `ask`, o proprio prompt E o pedido de autorizacao: mandar o agente
        // "pedir antes de reemitir" faria ele pedir duas vezes a mesma coisa.
        // No `deny` nao ha prompt, entao a saida de escape precisa vir no texto.
        + (decisao === 'ask'
          ? ''
          : `\n\nPeca a autorizacao ao mantenedor no formato "APROVACAO NECESSARIA" `
            + `(Acao / Motivo / Risco / Rollback / Escopo / Comandos) antes de reemitir.`)
        + extra,
    },
  }));
}

lerPayload((raw) => {
  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    process.exit(0); // payload ilegivel nunca bloqueia trabalho
  }
  const command = payload?.tool_input?.command ?? '';
  if (!command) process.exit(0);

  const { alvo, profundo } = canonico(command);
  if (profundo) {
    emitir('profundidade', 'deny', 'Comando aninhado além do limite de análise do hook, com git, gh ou comando de sistema dentro. Rode em comando simples.');
    process.exit(0);
  }

  for (const regra of regrasAtivas(process.env)) {
    if (!regra.test.test(alvo)) continue;

    // Só o commit mostra branch e último commit: é a ação em que o mantenedor precisa
    // conferir a branch antes de aprovar. O `ask` do commit segue mesmo sem leitura.
    const aviso = regra.nome === 'commit-sem-autorizacao' ? avisoCommit(contextoRepo(payload?.cwd)) : '';
    emitir(regra.nome, regra.decisao, regra.porque, aviso);
    process.exit(0);
  }

  process.exit(0);
});
