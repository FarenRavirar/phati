#!/usr/bin/env node
// Suíte do rtk-enforce. Roda com: node rtk-enforce.test.js
//
// Existe pelo mesmo motivo de `git-commit-msg-gate.test.js`: regra de hook que
// bloqueia comando precisa de teste, porque um falso-positivo trava trabalho
// legítimo e ninguém descobre até doer. Os casos "passa" importam mais que os
// "bloqueia" — cada um deles é um modo de falha em que o gate atrapalharia.

const { execFileSync } = require('node:child_process');
const path = require('node:path');

const HOOK = path.join(__dirname, 'rtk-enforce.js');

const CASES = [
  // --- leitura-parcial-crua (regra nova, 2026-08-07) ---
  { cmd: `sed -n '1,50p' arquivo.ts`, deny: true, rule: 'leitura-parcial-crua' },
  { cmd: `sed -n '300,345p' .github/workflows/exemplo.yml`, deny: true, rule: 'leitura-parcial-crua' },
  { cmd: `sed -n "1,20p" src/app.ts`, deny: true, rule: 'leitura-parcial-crua' },
  { cmd: `awk 'NR<50' x.ts`, deny: true, rule: 'leitura-parcial-crua' },

  // Filtro de pipe NÃO é leitura de arquivo — bloquear aqui quebraria o jeito
  // canônico de filtrar segredo da saída da VM (AGENTS.md §Autorização).
  { cmd: `ssh maruko 'sed "s/=.*/=<omitido>/" /opt/phati/.env'`, deny: false },
  { cmd: `cat x.md | sed 's/a/b/'`, deny: false },
  { cmd: `git log | awk '{print $1}'`, deny: false },
  { cmd: `rtk read x.ts`, deny: false },
  // Substituição in-place não é leitura.
  { cmd: `sed -i 's/foo/bar/' x.ts`, deny: false },

  // --- regras pré-existentes: não podem regredir ---
  { cmd: `pnpm verify:api`, deny: true, rule: 'pnpm-script-sem-run' },
  { cmd: `pnpm test`, deny: true, rule: 'pnpm-script-sem-run' },
  { cmd: `pnpm run lint`, deny: true, rule: 'script-pesado-sem-rtk' },
  { cmd: `pnpm --filter @phati/exemplo test`, deny: true, rule: 'pnpm-filter' },
  { cmd: `rtk pnpm run lint`, deny: false },
  { cmd: `rtk pnpm verify:api`, deny: false },
  { cmd: `pnpm install`, deny: false },
  { cmd: `cd apps/exemplo && rtk tsc -p tsconfig.json`, deny: false },
  { cmd: `rtk tsc`, deny: true, rule: 'rtk-subcomando-quebrado-no-turbo' },

  // --- rtk-grep-em-diretorio (spec 101 F3.0) ---
  // Medido: `rtk grep "AGENTS" specs` -> "grep: specs: Is a directory".
  { cmd: `rtk grep "termo" apps`, deny: true },
  { cmd: `rtk grep "padrao" packages/ui`, deny: true },
  // Com -r o grep nativo funciona: nao e o caso que o gate mira.
  { cmd: `rtk grep -r "termo" apps`, deny: false },
  { cmd: `rtk grep -rn "termo" apps`, deny: false },
  // Arquivo unico e uso legitimo do grep, mas sem -r o gate nao distingue
  // arquivo de diretorio; `rtk rg` cobre os dois, entao a correcao serve igual.
  { cmd: `rtk rg "termo" apps`, deny: false },

  // --- rtk-diff-solto (spec 101 F3.0) ---
  { cmd: `rtk diff AGENTS.md`, deny: true },
  { cmd: `rtk diff`, deny: true },
  { cmd: `rtk git diff AGENTS.md`, deny: false },
  { cmd: `rtk git diff --stat`, deny: false },
  // Falso-positivo a evitar: mencionar a regra nao dispara a regra.
  { cmd: `rtk rg "rtk diff" AGENTS.md`, deny: false },
];

let failed = 0;

for (const testCase of CASES) {
  let out = '';
  try {
    out = execFileSync(process.execPath, [HOOK], {
      input: JSON.stringify({ tool_input: { command: testCase.cmd } }),
      encoding: 'utf8',
    });
  } catch {
    console.log(`ERRO ao executar: ${testCase.cmd}`);
    failed += 1;
    continue;
  }

  const denied = out.includes('"permissionDecision":"deny"');

  if (denied !== testCase.deny) {
    console.log(`FALHOU  ${testCase.cmd}`);
    console.log(`        esperado ${testCase.deny ? 'DENY' : 'passar'}, obteve ${denied ? 'DENY' : 'passou'}`);
    failed += 1;
    continue;
  }

  if (denied && testCase.rule) {
    const reason = JSON.parse(out).hookSpecificOutput.permissionDecisionReason;
    if (!reason.includes(testCase.rule)) {
      console.log(`FALHOU  ${testCase.cmd}`);
      console.log(`        regra esperada ${testCase.rule}, motivo: ${reason.split('\n')[0]}`);
      failed += 1;
      continue;
    }
  }

  console.log(`ok      ${denied ? '[DENY]' : '[pass]'} ${testCase.cmd}`);
}

console.log('');
if (failed > 0) {
  console.log(`${failed} de ${CASES.length} falharam`);
  process.exit(1);
}
console.log(`${CASES.length}/${CASES.length} passaram`);
