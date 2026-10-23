#!/usr/bin/env node
// git-commit-msg-gate — PreToolUse(Bash): BLOQUEIA `git commit` cuja sintaxe de
// mensagem vaza caractere literal para dentro do commit.
//
// Incidente que originou (2026-07-29, branch feat/089-fase-8, commit 342f28e):
// o agente escreveu `git commit -m @'...'@` — a forma de here-string do
// PowerShell — mas o Bash tool roda Git Bash (POSIX sh), que não conhece essa
// sintaxe. Resultado: o `@` virou a PRIMEIRA LINHA do commit e o título real
// (`fix(downloads): ...`) desceu para o corpo. Commit ilegível em `git log` e no
// PR. Como `--amend` é proibido pela regra pétrea do AGENTS.md, o conserto exige
// `reset --soft` + reautorização do mantenedor — retrabalho puro.
//
// Por que um hook e não só documentação: a regra "use heredoc no Bash, here-string
// no PowerShell" já existia implicitamente (o system prompt do Bash tool avisa
// "Do not use PowerShell here-strings (@'...'@) here"). O agente errou de todo
// jeito, porque o mesmo repo usa PowerShell em outras chamadas e a memória
// muscular vaza entre as duas ferramentas. Prevenção que depende de lembrar não
// é prevenção — mesmo raciocínio do check_dockerfile_workspace_deps.mjs.
//
// Escopo deliberadamente estreito: só `git commit`. Não tenta validar Conventional
// Commits, tamanho de linha, nem conteúdo — só barra sintaxe que corrompe a
// mensagem de forma silenciosa e difícil de desfazer.

// `git commit` tem que ser COMANDO, não substring citada. Sem esta âncora o gate
// bloqueia `rg "git commit --amend" AGENTS.md` — falso-positivo observado no
// primeiro minuto de vida do hook (2026-07-29): buscar a regra no doc disparava a
// regra. `git` no início do comando ou depois de `&&`/`;`/`|`/`(`.

const { lerPayload } = require(require('node:path').join(__dirname, 'ler-payload.js'));
const GIT_COMMIT = String.raw`(?:^|[;&|(]\s*|\s&&\s*)git\s+commit\b`;

const RULES = [
  {
    name: 'powershell-herestring-no-bash',
    // `-m @'` ou `-m @"` — abertura de here-string do PowerShell. No Bash o `@`
    // é literal e entra na mensagem.
    test: new RegExp(`${GIT_COMMIT}[^\\n]*-m\\s*@['"]`),
    why: 'Bash tool roda Git Bash (POSIX sh), não PowerShell. `-m @\'...\'@` faz o `@` virar a primeira linha do commit e empurra o título real pro corpo (incidente 342f28e).',
    fix: 'Use heredoc POSIX:\n'
      + '  git commit -F - <<\'EOF\'\n'
      + '  fix(escopo): titulo\n'
      + '\n'
      + '  Corpo.\n'
      + '  EOF\n'
      + '\nOu, se preferir a PowerShell tool, mantenha `@\'...\'@` lá — mas não misture as duas.',
  },
  {
    name: 'herestring-terminator-vazado',
    // Fecha here-string (`'@` no início de linha) sem ter aberto no Bash: mesmo
    // vazamento, direção inversa.
    test: new RegExp(`${GIT_COMMIT}[\\s\\S]*\\n\\s*['"]@\\s*(?:\\n|$)`),
    why: 'Terminador de here-string do PowerShell (`\'@`) num comando Bash — entra literal na mensagem do commit.',
    fix: 'Troque por heredoc POSIX (`<<\'EOF\' ... EOF`) e verifique com `git log -1 --format=%B` depois.',
  },
  {
    name: 'amend-proibido',
    // Regra pétrea do AGENTS.md: `--amend` proibido sem exceção. Reescreve commit
    // sem autorização nova e força push --force-with-lease sobre branch já em
    // review — bots e mantenedor perdem o rastro do que já viram.
    test: new RegExp(`${GIT_COMMIT}[^\\n]*--amend`),
    why: 'AGENTS.md (regra pétrea): `git commit --amend` é PROIBIDO, sem exceção. Reescreve histórico de branch possivelmente já em review e força push --force.',
    fix: 'Faça commit NOVO em cima (`git commit -m "..."`) e push normal fast-forward.\n'
      + 'Se o mantenedor pediu explicitamente para "corrigir o commit", pergunte se é commit novo (padrão) ou reescrita por outro método autorizado nominalmente.',
  },
];

lerPayload((raw) => {
  let command = '';
  try {
    command = JSON.parse(raw)?.tool_input?.command ?? '';
  } catch {
    process.exit(0); // payload ilegível nunca bloqueia trabalho
  }
  if (!command || !new RegExp(GIT_COMMIT).test(command)) process.exit(0);

  for (const rule of RULES) {
    if (!rule.test.test(command)) continue;
    console.log(JSON.stringify({
      hookSpecificOutput: {
        hookEventName: 'PreToolUse',
        permissionDecision: 'deny',
        permissionDecisionReason:
          `[git-commit-msg-gate/${rule.name}] ${rule.why}\n\n${rule.fix}`,
      },
    }));
    process.exit(0);
  }

  process.exit(0);
});
